import sqlite3

import pytest

from app.db import Database


def test_real_idea_schema_is_versioned_and_isolated(tmp_path):
    db = Database(tmp_path / "evaluation.sqlite")
    db.init_schema()
    assert db.schema_version() >= 1
    assert db.table_names() >= {
        "real_idea_batches", "real_idea_samples",
        "real_idea_budget_allocations", "real_idea_transport_reservations",
        "real_idea_feedback", "real_idea_annotations",
    }
    assert db.public_project_schema_has_no_evaluation_identity_input()


def _insert_batch_and_sample(db: Database, batch_id: str, sample_id: str, allocation_id: str):
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO real_idea_batches(batch_id,batch_key,status,manifest_sha256,source_commit,deployment_id,model,prompt_hash,schema_hash,completeness_contract_version,questionnaire_version,sample_count,provider_policy_version,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, batch_id, "CREATED", "m", "c", "d", "model", "p", "s", "v", "q", 3, "policy", "now", "actor"),
        )
        connection.execute(
            "INSERT INTO real_idea_budget_allocations(allocation_id,batch_id,authorized_total,batch_earmark,sample_cap,quickstart_cap,solutions_cap,purpose,state,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (allocation_id, batch_id, 6, 6, 2, 1, 1, "evaluation", "ACTIVE", "now", "actor"),
        )
        connection.execute(
            "INSERT INTO real_idea_samples(sample_id,batch_id,sample_key,source_type,raw_idea_sha256,redaction_version,state,sample_manifest_sha256,budget_allocation_id,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sample_id, batch_id, "REAL_IDEA_01", "user_input", "raw", "r1", "SLOT_CREATED", "manifest", allocation_id, "now", "actor"),
        )


def test_failed_migration_rolls_back_tables_and_version(tmp_path, monkeypatch):
    from app.migrations import real_idea_evaluation_v1 as migration

    path = tmp_path / "rollback.sqlite"
    with sqlite3.connect(path) as connection:
        monkeypatch.setattr(
            migration,
            "MIGRATION_SQL",
            migration.MIGRATION_SQL + "\nCREATE TABLE migration_fault_probe(id TEXT);\nTHIS IS INVALID SQL;",
        )
        with pytest.raises(sqlite3.OperationalError):
            migration.apply(connection)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'real_idea_batches'"
        ).fetchone() is None
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0


def test_child_rows_cannot_cross_batch_or_allocation_binding(tmp_path):
    db = Database(tmp_path / "bindings.sqlite")
    db.init_schema()
    _insert_batch_and_sample(db, "batch-1", "sample-1", "allocation-1")
    _insert_batch_and_sample(db, "batch-2", "sample-2", "allocation-2")

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO real_idea_transport_reservations(reservation_id,batch_id,sample_id,stage,ordinal,idempotency_key,state,reserved_at,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
            ("reservation-1", "batch-2", "sample-1", "QUICKSTART", 1, "key-1", "RESERVED", "now", "actor"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO real_idea_samples(sample_id,batch_id,sample_key,source_type,raw_idea_sha256,redaction_version,state,sample_manifest_sha256,budget_allocation_id,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("sample-3", "batch-2", "REAL_IDEA_02", "user_input", "raw", "r1", "SLOT_CREATED", "manifest", "allocation-1", "now", "actor"),
        )


def test_artifact_bindings_require_existing_rows(tmp_path):
    db = Database(tmp_path / "artifacts.sqlite")
    db.init_schema()
    _insert_batch_and_sample(db, "batch-1", "sample-1", "allocation-1")

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE real_idea_samples SET brief_version_id='missing-brief', solutions_evaluation_id='missing-run', selected_solution_id='missing-solution', snapshot_id='missing-snapshot', prd_version_id='missing-prd', techdoc_version_id='missing-techdoc', handoff_run_id='missing-handoff' WHERE sample_id='sample-1'"
        )


def test_database_rejects_invalid_sample_key_and_immutable_audit_changes(tmp_path):
    db = Database(tmp_path / "immutability.sqlite")
    db.init_schema()
    _insert_batch_and_sample(db, "batch-1", "sample-1", "allocation-1")

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO real_idea_samples(sample_id,batch_id,sample_key,source_type,raw_idea_sha256,redaction_version,state,sample_manifest_sha256,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("sample-invalid", "batch-1", "OTHER", "user_input", "raw", "r1", "SLOT_CREATED", "manifest", "now", "actor"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE real_idea_samples SET source_type='model_hypothesis' WHERE sample_id='sample-1'")

    db.execute(
        "INSERT INTO real_idea_feedback(feedback_id,batch_id,sample_id,stage,submitted_by,submitted_at,accepted,score_payload,feedback_attestation,feedback_schema_version,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("feedback-1", "batch-1", "sample-1", "BRIEF", "idea_provider", "now", 1, "{}", 1, "v1", "actor"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE real_idea_feedback SET accepted=0 WHERE feedback_id='feedback-1'")

    db.execute(
        "INSERT INTO real_idea_annotations(annotation_id,batch_id,sample_id,annotation_kind,target_type,target_id,payload_json,annotation_schema_version,policy_version,revision,input_sha256,evidence_sha256,created_at,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("annotation-1", "batch-1", "sample-1", "claim", "solution", "claim-1", "{}", "v1", "p1", 1, "i", "e", "now", "actor"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM real_idea_annotations WHERE annotation_id='annotation-1'")

    db.execute("UPDATE real_idea_batches SET finalized_at='later' WHERE batch_id='batch-1'")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE real_idea_batches SET status='RUNNING' WHERE batch_id='batch-1'")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM real_idea_batches WHERE batch_id='batch-1'")

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE real_idea_budget_allocations SET created_by='other' WHERE allocation_id='allocation-1'")
