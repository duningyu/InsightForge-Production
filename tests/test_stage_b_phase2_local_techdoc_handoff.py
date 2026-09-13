"""Task 1 contract tests for the Stage-B Phase 2 local canary operators."""

import json
import sqlite3
from hashlib import sha256

import pytest

from app.db import Database, utc_now
from app.services.document_versions import DocumentVersionService
from app.services.stage_b_evaluation import StageBEvaluationReceiptStore, StageBGuardError
from app.services.stage_b_synthetic_seed import (
    STAGE_B_PHASE1A_PARTICIPANT,
    StageBPhase1ASyntheticProjectSeedService,
)
import scripts.stage_b_evaluation_inspect as operator


def _phase2_database(tmp_path):
    database = Database(tmp_path / "phase2-confirm.sqlite3")
    database.init_schema()
    seed = StageBPhase1ASyntheticProjectSeedService(database)
    seed.seed(participant=STAGE_B_PHASE1A_PARTICIPANT, actor="test-seed")
    project_id = "project_seed_phase1a_synthetic"
    now = utc_now()
    brief = database.fetch_one(
        "SELECT id FROM idea_briefs WHERE project_id=? ORDER BY version DESC LIMIT 1",
        (project_id,),
    )
    assert brief is not None
    database.execute(
        """INSERT INTO project_canvas(
            project_id, version, problem, target_users, goals_json,
            non_goals_json, success_metrics_json, constraints_json, created_at, updated_at
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id, "problem", "target users", "[]", "[]", "[]", "[]", now, now,
        ),
    )
    solution_run_id = "solution_run_phase2"
    solution_id = "solution_6199e5ad886d47769e835c311f7d0ec6"
    database.execute(
        """INSERT INTO solution_runs(
            id, project_id, idea_brief_id, provider, model, prompt_version,
            schema_version, generator_version, input_sha256, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (solution_run_id, project_id, brief["id"], "local", "fixture", "fixture", "1", "1", "fixture", "succeeded", now),
    )
    json_value = json.dumps([], ensure_ascii=False)
    database.execute(
        """INSERT INTO solution_candidates(
            id, run_id, project_id, title, mechanism, summary, why_fit,
            user_flow_json, mvp_pages_json, features_json, inputs_json, outputs_json,
            decision_logic_json, data_requirements_json, technical_components_json,
            implementation_plan_json, acceptance_cases_json, risks_json, unknowns_json,
            complexity, provenance, created_at
        ) VALUES (?, ?, ?, ?, 'workflow_based', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (solution_id, solution_run_id, project_id, "Selected solution", "summary", "fit", *([json_value] * 12), "low", "synthetic", now),
    )
    decision_id = "decision_phase2"
    database.execute(
        """INSERT INTO project_decisions(
            id, project_id, decision_type, options_json, selected_option_id,
            rationale, status, decision_key, decision_version, decision_payload_json,
            confirmed_by, created_at, confirmed_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?, 1, ?, ?, ?, ?)""",
        (decision_id, project_id, "solution", json.dumps([solution_id]), solution_id, "fixture", "solution", "{}", "test", now, now),
    )
    snapshot_id = "snapshot_phase2"
    snapshot_fields = [
        snapshot_id, project_id, brief["id"], decision_id, "Selected", "one liner",
        json.dumps({"users": ["target"]}), json.dumps({"problem": "problem"}),
        json.dumps({"title": "Selected solution", "summary": "solution", "why_fit": "fit"}),
        json.dumps({"features": ["mvp"], "pages": ["page"], "risks": ["risk"]}),
        json.dumps(["flow"]), json.dumps(["inputs"]),
        json.dumps(["outputs"]), json.dumps(["technical"]), json.dumps(["unknowns"]),
        json.dumps(["next"]), now, now, "test", sha256(b"snapshot").hexdigest(),
    ]
    database.execute(
        """INSERT INTO project_snapshots(
            id, project_id, version, idea_brief_id, decision_id, title, one_liner,
            target_user_json, problem_json, solution_json, mvp_json, user_flow_json,
            inputs_json, outputs_json, technical_plan_json, unknowns_json, next_action_json,
            snapshot_origin, created_at, confirmed_at, created_by, content_sha256
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'quick_value_flow', ?, ?, ?, ?)""",
        snapshot_fields,
    )
    database.execute(
        "INSERT INTO snapshot_decision_links(snapshot_id, decision_id, role) VALUES (?, ?, 'current_solution')",
        (snapshot_id, decision_id),
    )
    database.execute(
        """INSERT INTO artifact_health(artifact_type, artifact_id, health_status, reason, updated_at)
           VALUES ('project_snapshot', ?, 'current', 'fixture', ?)""",
        (snapshot_id, now),
    )
    database.execute(
        "UPDATE projects SET current_snapshot_id=? WHERE id=?", (snapshot_id, project_id)
    )
    document_id = "document_phase2_prd"
    version_id = "version_phase2_prd"
    database.execute(
        "INSERT INTO documents(id, project_id, doc_type, title, created_at) VALUES (?, ?, 'prd', 'PRD', ?)",
        (document_id, project_id, now),
    )
    database.execute(
        """INSERT INTO document_versions(
            id, document_id, project_id, doc_type, version, canvas_version,
            status, content, citations_json, validation_status, idempotency_key, created_at
        ) VALUES (?, ?, ?, 'prd', 1, 1, 'draft', ?, '[]', 'passed', ?, ?)""",
        (version_id, document_id, project_id, "# PRD\nfixture", "prd-fixture", now),
    )
    database.execute(
        """INSERT INTO artifact_health(artifact_type, artifact_id, health_status, reason, updated_at)
           VALUES ('document_version', ?, 'current', 'fixture', ?)""",
        (version_id, now),
    )
    database.execute(
        """INSERT INTO artifact_dependencies(
               artifact_type, artifact_id, dependency_type, dependency_id,
               dependency_version, created_at
           ) VALUES ('document_version', ?, 'project_snapshot', ?, NULL, ?)""",
        (version_id, snapshot_id, now),
    )
    return database, project_id, version_id, solution_id, snapshot_id


def _prepare_confirmed_handoff_documents(database, project_id, prd_version_id, snapshot_id):
    """Make the isolated fixture satisfy the existing handoff document contract."""
    DocumentVersionService(database).confirm(
        prd_version_id, actor="test-operator", note="fixture", human_confirmed=True
    )
    now = utc_now()
    document_id = "document_phase2_techdoc"
    version_id = "version_phase2_techdoc"
    database.execute(
        "INSERT INTO documents(id, project_id, doc_type, title, created_at) VALUES (?, ?, 'techdoc', 'TechDoc', ?)",
        (document_id, project_id, now),
    )
    database.execute(
        """INSERT INTO document_versions(
            id, document_id, project_id, doc_type, version, canvas_version,
            status, content, citations_json, validation_status, idempotency_key, created_at,
            approved_at
        ) VALUES (?, ?, ?, 'techdoc', 1, 1, 'approved', ?, '[]', 'passed', ?, ?, ?)""",
        (version_id, document_id, project_id, "# TechDoc\nfixture", "techdoc-fixture", now, now),
    )
    database.execute(
        """INSERT INTO artifact_health(artifact_type, artifact_id, health_status, reason, updated_at)
           VALUES ('document_version', ?, 'current', 'fixture', ?)""",
        (version_id, now),
    )
    database.execute(
        """INSERT INTO artifact_dependencies(
               artifact_type, artifact_id, dependency_type, dependency_id,
               dependency_version, created_at
           ) VALUES ('document_version', ?, 'project_snapshot', ?, NULL, ?)""",
        (version_id, snapshot_id, now),
    )
    return version_id


class _ProviderTripwire:
    def __getattr__(self, name):
        raise AssertionError(f"Provider must not be called: {name}")


class _SearchTripwire:
    def __getattr__(self, name):
        raise AssertionError(f"Search must not be called: {name}")


def test_confirm_prd_canary_persists_receipt_before_service_mutation_and_carries_context(
    tmp_path, monkeypatch
) -> None:
    database, project_id, version_id, solution_id, snapshot_id = _phase2_database(tmp_path)
    observed: dict[str, object] = {}

    class ConfirmService:
        def __init__(self, db):
            self.db = db

        def confirm(self, requested_version_id, *, actor, note, human_confirmed):
            receipts = StageBEvaluationReceiptStore(database=Database(database.path))
            rows = self.db.fetch_all(
                "SELECT * FROM stage_b_evaluation_receipts WHERE operation=?",
                (operator.PHASE2_PRD_CONFIRM,),
            )
            assert len(rows) == 1
            readback = receipts.inspect(rows[0]["evaluation_id"])
            observed.update(
                evaluation_id=readback["evaluation_id"],
                status=readback["status"],
                project_id=readback["idea_id"],
                context_version=readback["context_version"],
                requested_version_id=requested_version_id,
                actor=actor,
                note=note,
                human_confirmed=human_confirmed,
            )
            assert readback["status"] == "CREATED"
            assert readback["transport_count"] == 0
            assert readback["transport_attempted"] == 0
            return DocumentVersionService(self.db).confirm(
                requested_version_id, actor=actor, note=note, human_confirmed=human_confirmed
            )

    monkeypatch.setattr(operator, "DocumentVersionService", ConfirmService, raising=False)
    monkeypatch.setattr(operator, "ProviderAdapter", _ProviderTripwire, raising=False)
    monkeypatch.setattr(operator, "SearchClient", _SearchTripwire, raising=False)

    result = operator.run_confirm_prd_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )

    assert observed == {
        "evaluation_id": observed["evaluation_id"],
        "status": "CREATED",
        "project_id": project_id,
        "context_version": operator.CONTEXT_VERSION,
        "requested_version_id": version_id,
        "actor": "phase2-test-operator",
        "note": "Phase 2 PRD confirmation canary",
        "human_confirmed": True,
    }
    assert result.operation == operator.PHASE2_PRD_CONFIRM
    assert result.project_id == project_id
    assert result.version_id == version_id
    assert result.selected_solution_id == solution_id
    assert result.snapshot_id == snapshot_id
    assert result.status == "approved"
    assert database.fetch_one("SELECT status FROM document_versions WHERE id=?", (version_id,))["status"] == "approved"


def test_confirm_prd_canary_is_idempotent_for_the_same_current_confirmation(tmp_path) -> None:
    database, project_id, version_id, solution_id, snapshot_id = _phase2_database(tmp_path)

    first = operator.run_confirm_prd_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )
    second = operator.run_confirm_prd_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )

    assert second == first
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM stage_b_evaluation_receipts WHERE operation=?",
        (operator.PHASE2_PRD_CONFIRM,),
    )["n"] == 1
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM audit_events WHERE action='document_version_confirmed' AND entity_id=?",
        (version_id,),
    )["n"] == 1
    assert first.selected_solution_id == solution_id
    assert first.snapshot_id == snapshot_id


def test_confirm_prd_canary_fails_closed_without_a_current_validation_passed_prd(tmp_path) -> None:
    database, project_id, _version_id, _solution_id, _snapshot_id = _phase2_database(tmp_path)
    database.execute(
        "UPDATE document_versions SET validation_status='needs_human_review' WHERE project_id=?",
        (project_id,),
    )

    with pytest.raises(StageBGuardError, match="PRD"):
        operator.run_confirm_prd_canary(
            database=database, project_id=project_id, actor="phase2-test-operator"
        )

    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM stage_b_evaluation_receipts WHERE operation=?",
        (operator.PHASE2_PRD_CONFIRM,),
    )["n"] == 0


def test_confirm_prd_canary_does_not_initialize_or_migrate_schema_before_preflight(
    tmp_path, monkeypatch
) -> None:
    database, project_id, _version_id, _solution_id, _snapshot_id = _phase2_database(tmp_path)

    def forbidden_schema_initialization() -> None:
        raise AssertionError("Phase 2 canary must not initialize or migrate schema")

    monkeypatch.setattr(database, "init_schema", forbidden_schema_initialization)
    database.execute(
        "UPDATE document_versions SET validation_status='needs_human_review' WHERE project_id=?",
        (project_id,),
    )

    with pytest.raises(StageBGuardError, match="PRD"):
        operator.run_confirm_prd_canary(
            database=database, project_id=project_id, actor="phase2-test-operator"
        )

    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM stage_b_evaluation_receipts WHERE operation=?",
        (operator.PHASE2_PRD_CONFIRM,),
    )["n"] == 0


def test_local_techdoc_canary_reads_back_receipt_before_local_document_loop(
    tmp_path, monkeypatch
) -> None:
    database, project_id, _version_id, solution_id, snapshot_id = _phase2_database(tmp_path)
    database.execute(
        "UPDATE document_versions SET status='approved' WHERE id=?",
        (_version_id,),
    )
    observed: dict[str, object] = {}

    class LocalGenerator:
        pass

    class DocumentLoop:
        def __init__(self, db, *, generator):
            observed["database_path"] = db.path
            observed["generator_type"] = type(generator)

        def run(self, requested_project_id, doc_type, **kwargs):
            rows = database.fetch_all(
                "SELECT * FROM stage_b_evaluation_receipts WHERE operation=?",
                (operator.PHASE2_TECHDOC_GENERATE,),
            )
            assert len(rows) == 1
            receipt = StageBEvaluationReceiptStore(database=Database(database.path)).inspect(
                rows[0]["evaluation_id"]
            )
            observed.update(
                evaluation_id=receipt["evaluation_id"],
                status=receipt["status"],
                project_id=receipt["idea_id"],
                doc_type=doc_type,
                requested_project_id=requested_project_id,
                idempotency_key=kwargs["idempotency_key"],
                require_snapshot=kwargs["require_snapshot"],
                competitor_snapshot_id=kwargs["competitor_snapshot_id"],
                use_competitor_snapshot=kwargs["use_competitor_snapshot"],
            )
            assert receipt["status"] == "CREATED"
            assert receipt["dispatch_count"] == 0
            assert receipt["transport_count"] == 0
            assert receipt["transport_attempted"] == 0
            database.execute(
                "INSERT INTO documents(id, project_id, doc_type, title, created_at) VALUES (?, ?, 'techdoc', 'TechDoc', ?)",
                ("document_phase2_techdoc", requested_project_id, utc_now()),
            )
            database.execute(
                """INSERT INTO document_versions(
                       id, document_id, project_id, doc_type, version, canvas_version,
                       status, content, citations_json, validation_status, idempotency_key, created_at
                   ) VALUES (?, ?, ?, 'techdoc', 1, 1, 'draft', ?, '[]', 'passed', ?, ?)""",
                (
                    "version_phase2_techdoc", "document_phase2_techdoc", requested_project_id,
                    "# TechDoc\nfixture", kwargs["idempotency_key"], utc_now(),
                ),
            )
            return {
                "project_id": requested_project_id,
                "doc_type": "techdoc",
                "document_id": "document_phase2_techdoc",
                "version_id": "version_phase2_techdoc",
                "snapshot_id": snapshot_id,
                "selected_solution_id": solution_id,
                "rounds": 1,
                "citations": [],
                "claims": [],
            }

    monkeypatch.setattr(operator, "DocumentLoop", DocumentLoop, raising=False)
    monkeypatch.setattr(operator, "LocalDocumentGenerator", LocalGenerator, raising=False)

    result = operator.run_local_techdoc_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )

    assert result.operation == operator.PHASE2_TECHDOC_GENERATE
    assert result.project_id == project_id
    assert result.selected_solution_id == solution_id
    assert result.snapshot_id == snapshot_id
    assert result.document_id == "document_phase2_techdoc"
    assert result.version_id == "version_phase2_techdoc"
    assert result.status == "completed"
    assert observed["generator_type"] is LocalGenerator


def test_local_techdoc_canary_uses_selected_solution_snapshot_without_prd_binding(
    tmp_path, monkeypatch
) -> None:
    database, project_id, version_id, solution_id, snapshot_id = _phase2_database(tmp_path)
    database.execute(
        "UPDATE project_canvas SET problem=?, target_users=? WHERE project_id=?",
        (json.dumps("problem"), json.dumps(["target users"]), project_id),
    )

    result = operator.run_local_techdoc_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )

    assert result.status == "completed"
    assert result.selected_solution_id == solution_id
    assert result.snapshot_id == snapshot_id
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM document_versions WHERE project_id=? AND doc_type='techdoc'",
        (project_id,),
    )["n"] == 1
    techdoc = database.fetch_one(
        "SELECT * FROM document_versions WHERE project_id=? AND doc_type='techdoc'",
        (project_id,),
    )
    assert techdoc["validation_status"] == "passed"
    assert techdoc["status"] == "draft"
    assert database.fetch_one(
        """SELECT 1 FROM artifact_dependencies
           WHERE artifact_type='document_version' AND artifact_id=? AND dependency_type='prd_version'""",
        (techdoc["id"],),
    ) is None
    receipt = StageBEvaluationReceiptStore(database=Database(database.path)).inspect(result.evaluation_id)
    assert receipt["status"] == "SUCCEEDED"
    assert receipt["dispatch_count"] == 0
    assert receipt["transport_count"] == 0
    artifact = json.loads(
        (tmp_path / "private" / "stage_b_evaluation" / f"{sha256(result.evaluation_id.encode()).hexdigest()}.json").read_text()
    )
    assert artifact["response"]["content"] is True
    assert "prompt" in artifact and artifact["prompt"] is None
    monkeypatch.setattr(operator, "DocumentLoop", lambda *args, **kwargs: pytest.fail("idempotent rerun must not invoke loop"))
    assert operator.run_local_techdoc_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    ) == result


def test_local_techdoc_canary_does_not_require_confirmed_prd_before_receipt(tmp_path) -> None:
    database, project_id, _version_id, _solution_id, _snapshot_id = _phase2_database(tmp_path)

    result = operator.run_local_techdoc_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )

    assert result.status == "completed"
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM document_versions WHERE project_id=? AND doc_type='techdoc'",
        (project_id,),
    )["n"] == 1


@pytest.mark.parametrize(
    "command",
    [
        "confirm-prd-canary",
        "local-techdoc-canary",
        "confirm-techdoc-canary",
        "handoff-canary",
    ],
)
def test_phase2_operator_command_help_is_exposed_without_execution(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert operator.main([command, "--help"]) == 0

    output = capsys.readouterr().out
    assert command in output
    assert "--project-id" in output
    assert "--provider" not in output
    assert "--model" not in output


def test_phase2_help_has_no_evaluation_product_provider_search_or_budget_side_effects(
    tmp_path, monkeypatch, capsys
) -> None:
    database_path = tmp_path / "isolated-stage-b.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE product_tripwire (value TEXT NOT NULL)")
        connection.execute("INSERT INTO product_tripwire VALUES ('unchanged')")
        connection.commit()

    calls: list[str] = []

    class DatabaseTripwire:
        def __init__(self, *_args, **_kwargs):
            calls.append("database")
            raise AssertionError("help must not construct or mutate a database")

    def tripwire(*_args, **_kwargs):
        calls.append("external-or-budget")
        raise AssertionError("help must not evaluate, dispatch, search, or consume budget")

    monkeypatch.setattr(operator, "Database", DatabaseTripwire)
    monkeypatch.setattr(operator, "StageBEvaluationReceiptStore", tripwire)
    monkeypatch.setattr(operator, "evaluate_stage_b_guard", tripwire)
    monkeypatch.setattr(operator, "_database_path", lambda: database_path)

    for command in operator._PHASE2_COMMANDS:
        assert operator.main([command, "--help", "--database", str(database_path)]) == 0

    assert calls == []
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT value FROM product_tripwire").fetchone() == ("unchanged",)
    capsys.readouterr()


def test_phase2_operator_without_project_id_returns_rejection_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator.main(["local-techdoc-canary"]) == 2
    assert "--project-id" in capsys.readouterr().err


@pytest.mark.parametrize("document_state", ["missing", "unconfirmed", "stale"])
def test_handoff_canary_rejects_missing_unconfirmed_or_stale_techdoc_before_mutation(
    tmp_path, document_state
) -> None:
    database, project_id, prd_version_id, _solution_id, snapshot_id = _phase2_database(tmp_path)
    if document_state != "missing":
        techdoc_version_id = _prepare_confirmed_handoff_documents(
            database, project_id, prd_version_id, snapshot_id
        )
        if document_state == "unconfirmed":
            database.execute(
                "UPDATE document_versions SET status='draft', approved_at=NULL WHERE id=?",
                (techdoc_version_id,),
            )
        else:
            database.execute(
                "UPDATE artifact_health SET health_status='stale_evidence' WHERE artifact_id=?",
                (techdoc_version_id,),
            )

    with pytest.raises(StageBGuardError, match="HANDOFF|TECHDOC"):
        operator.run_handoff_canary(
            database=database, project_id=project_id, actor="phase2-test-operator"
        )

    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM handoff_runs WHERE project_id=?", (project_id,)
    )["n"] == 0
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM handoff_unresolved_acknowledgements WHERE project_id=?",
        (project_id,),
    )["n"] == 0
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM stage_b_evaluation_receipts WHERE operation=?",
        (operator.PHASE2_HANDOFF,),
    )["n"] == 0


@pytest.mark.parametrize(
    ("guard_kwargs", "message"),
    [
        ({"participant": "wrong-participant"}, "STAGE_B_PARTICIPANT_REQUIRED"),
        ({"safe_fixture_mode": True}, "SAFE_FIXTURE_MUST_BE_OFF"),
        ({"accounts_enabled": True}, "ACCOUNTS_MUST_BE_DISABLED"),
        ({"real_provider_stage_b": False}, "REAL_PROVIDER_STAGE_B_REQUIRED"),
    ],
)
def test_handoff_canary_enforces_stage_b_guard_before_execution_boundary(
    tmp_path, guard_kwargs, message
) -> None:
    database, project_id, _prd_version_id, _solution_id, _snapshot_id = _phase2_database(tmp_path)

    with pytest.raises(StageBGuardError, match=message):
        operator.run_handoff_canary(
            database=database,
            project_id=project_id,
            actor="phase2-test-operator",
            **guard_kwargs,
        )


def test_handoff_canary_valid_prepared_project_reaches_local_assembly(tmp_path) -> None:
    database, project_id, prd_version_id, _solution_id, snapshot_id = _phase2_database(tmp_path)
    _prepare_confirmed_handoff_documents(database, project_id, prd_version_id, snapshot_id)

    result = operator.run_handoff_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )

    assert result.operation == operator.PHASE2_HANDOFF
    assert result.project_id == project_id


def test_handoff_canary_acknowledgement_and_build_are_idempotent(tmp_path) -> None:
    database, project_id, prd_version_id, _solution_id, snapshot_id = _phase2_database(tmp_path)
    _prepare_confirmed_handoff_documents(database, project_id, prd_version_id, snapshot_id)

    first = operator.run_handoff_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )
    second = operator.run_handoff_canary(
        database=database, project_id=project_id, actor="phase2-test-operator"
    )

    assert second == first
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM handoff_unresolved_acknowledgements WHERE project_id=?", (project_id,)
    )["n"] == 1
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM handoff_runs WHERE project_id=? AND target_client='generic'", (project_id,)
    )["n"] == 1
    receipt = StageBEvaluationReceiptStore(database=database).inspect(first.evaluation_id)
    assert receipt["dispatch_count"] == 0
    assert receipt["transport_count"] == 0
    assert "fixture" not in json.dumps(receipt, ensure_ascii=False)


def test_handoff_canary_rejects_multiple_current_techdocs_fail_closed(tmp_path) -> None:
    database, project_id, prd_version_id, _solution_id, snapshot_id = _phase2_database(tmp_path)
    _prepare_confirmed_handoff_documents(database, project_id, prd_version_id, snapshot_id)
    now = utc_now()
    database.execute(
        """INSERT INTO document_versions(
            id, document_id, project_id, doc_type, version, canvas_version,
            status, content, citations_json, validation_status, idempotency_key, created_at, approved_at
        ) VALUES (?, ?, ?, 'techdoc', 2, 1, 'approved', ?, '[]', 'passed', ?, ?, ?)""",
        ("version_phase2_techdoc_2", "document_phase2_techdoc", project_id,
         "# TechDoc 2\nfixture", "techdoc-fixture-2", now, now),
    )
    database.execute(
        "INSERT INTO artifact_health(artifact_type, artifact_id, health_status, reason, updated_at) VALUES ('document_version', ?, 'current', 'fixture', ?)",
        ("version_phase2_techdoc_2", now),
    )
    database.execute(
        "INSERT INTO artifact_dependencies(artifact_type, artifact_id, dependency_type, dependency_id, dependency_version, created_at) VALUES ('document_version', ?, 'project_snapshot', ?, NULL, ?)",
        ("version_phase2_techdoc_2", snapshot_id, now),
    )

    with pytest.raises(StageBGuardError, match="TECHDOC_NOT_EXACTLY_ONE"):
        operator.run_handoff_canary(database=database, project_id=project_id, actor="phase2-test-operator")
    assert database.fetch_one("SELECT COUNT(*) AS n FROM handoff_runs WHERE project_id=?", (project_id,))["n"] == 0
    assert database.fetch_one("SELECT COUNT(*) AS n FROM stage_b_evaluation_receipts WHERE idea_id=?", (project_id,))["n"] == 0


def test_phase2_normal_invocation_dispatches_to_mapped_runner(monkeypatch, capsys) -> None:
    calls: list[tuple[object, str, str]] = []

    class DatabaseFixture:
        def __init__(self, path):
            self.path = path

    def runner(*, database, project_id, actor):
        calls.append((database, project_id, actor))
        return operator.Phase2SafeReceiptMetadata(
            operation=operator.PHASE2_TECHDOC_GENERATE, status="not_implemented"
        )

    monkeypatch.setattr(operator, "Database", DatabaseFixture)
    monkeypatch.setitem(
        operator._PHASE2_COMMANDS,
        "local-techdoc-canary",
        (operator.PHASE2_TECHDOC_GENERATE, runner),
    )

    assert operator.main([
        "local-techdoc-canary", "--project-id", "isolated-project",
        "--database", "isolated.sqlite3", "--actor", "test-actor",
    ]) == 0
    assert len(calls) == 1
    assert calls[0][1:] == ("isolated-project", "test-actor")
    assert '"operation": "PHASE2_TECHDOC_GENERATE"' in capsys.readouterr().out
