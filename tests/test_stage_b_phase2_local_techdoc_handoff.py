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
        "target", "problem", "solution", "mvp", "flow", "inputs", "outputs",
        "technical", "unknowns", "next", now, now, "test", sha256(b"snapshot").hexdigest(),
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
