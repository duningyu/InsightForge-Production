from __future__ import annotations


def test_m3_schema_has_submission_review_recovery_and_decision_contracts(db):
    expected = {
        "first_action_cards": {
            "kind",
            "parent_task_id",
            "source_submission_id",
            "source_review_id",
            "execution_state",
            "execution_revision",
        },
        "action_submissions": {
            "submission_id",
            "project_id",
            "task_id",
            "task_revision",
            "submission_kind",
            "description",
            "attachment_refs_json",
            "check_results_json",
            "execution_claim_json",
            "source_identity",
            "revision",
            "submitted_by",
            "created_at",
        },
        "action_reviews": {
            "review_id",
            "project_id",
            "submission_id",
            "submission_revision",
            "task_id",
            "task_revision",
            "check_items_json",
            "overall_status",
            "known_unknowns_json",
            "evidence_level",
            "recommendation",
            "reviewer_role",
            "revision",
            "evidence_hash",
            "created_at",
        },
        "decision_records": {
            "decision_id",
            "project_id",
            "source_submission_id",
            "source_review_id",
            "decision",
            "rationale",
            "confirmed",
            "confirmed_by",
            "revision",
            "created_at",
        },
    }
    with db.connect() as connection:
        for table, fields in expected.items():
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert fields <= columns


def test_m3_schema_enforces_action_and_decision_enum_contracts(db):
    with db.connect() as connection:
        sql_by_table = {
            table: connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            for table in (
                "first_action_cards",
                "action_submissions",
                "action_reviews",
                "decision_records",
            )
        }

    assert "RECOVERY" in sql_by_table["first_action_cards"]
    assert "DONE" in sql_by_table["action_submissions"]
    assert "BLOCKED" in sql_by_table["action_submissions"]
    assert "AUTHORIZED_RUN" in sql_by_table["action_reviews"]
    assert "NOT_APPLICABLE" in sql_by_table["action_reviews"]
    for decision in ("CONTINUE", "NARROW", "CHANGE", "STOP", "FINISH"):
        assert decision in sql_by_table["decision_records"]


def test_m3_quality_ledger_accepts_m3_action_artifacts(db):
    with db.connect() as connection:
        project_id = connection.execute(
            "SELECT id FROM projects ORDER BY id LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO real_idea_quality_evaluations(
                quality_evaluation_id, project_id, artifact_type,
                artifact_version_id, upstream_version_ids, quality_layer,
                quality_revision, status, metric_payload,
                input_manifest_sha256, evidence_manifest_sha256,
                policy_version, quality_schema_version, evaluator_role,
                evaluation_scope, owner_actor, artifact_id, artifact_revision,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "m3-quality-migration-test",
                project_id,
                "M3_ACTION",
                "task-test:1",
                "{}",
                "P0",
                1,
                "PASS",
                "{}",
                "input-sha",
                "evidence-sha",
                "if-guide-m3",
                "if-guide-m3-v1",
                "system",
                "IF_GUIDE_M3",
                "owner",
                "task-test",
                1,
                "2026-09-16T00:00:00+00:00",
            ),
        )
