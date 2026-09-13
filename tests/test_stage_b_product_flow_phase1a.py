"""Phase 1A operator execution-path contract tests.

These first tests intentionally describe the bounded capabilities that are
missing from the baseline: CLI-only Solutions and local-PRD canary commands.
They are the RED checkpoint for the implementation task.
"""

from pathlib import Path

import pytest

from app.db import Database
from scripts.stage_b_evaluation_inspect import (
    main,
    run_local_prd_canary,
    run_solutions_canary,
)
from app.services.stage_b_evaluation import StageBGuardError
from app.services.stage_b_evaluation import StageBEvaluationReceiptStore


def test_solutions_canary_operator_command_exists() -> None:
    assert main(["solutions-canary", "--help"]) == 0


def test_local_prd_canary_operator_command_exists() -> None:
    assert main(["local-prd-canary", "--help"]) == 0


def _database(tmp_path: Path) -> tuple[Database, str]:
    database = Database(tmp_path / "insightforge.sqlite3")
    database.init_schema()
    project_id = "synthetic-phase1a-project"
    database.execute(
        "INSERT INTO projects(id, title, summary, status, project_origin, exclude_from_beta_metrics, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', 'demo', 1, '2026-01-01', '2026-01-01')",
        (project_id, "Synthetic", "Synthetic project"),
    )
    return database, project_id


def test_solutions_operator_creates_receipt_before_service_and_passes_context(tmp_path: Path) -> None:
    database, project_id = _database(tmp_path)
    observed = {}

    class FakeSolutionService:
        def generate(self, project_id: str, **kwargs: object) -> dict[str, object]:
            observed.update(kwargs)
            return {"candidates": [{"id": "safe"}]}

    result = run_solutions_canary(
        database=database, project_id=project_id, actor="test-operator",
        solution_service=FakeSolutionService(),
        participant="railway_stage_b",
    )
    assert result["status"] == "SUCCEEDED"
    assert result["dispatch_count"] == 0
    assert result["transport_count"] == 0
    assert observed["evaluation_context"].evaluation_id == result["evaluation_id"]
    assert observed["execution_policy"].validation_regeneration_allowed is False


def test_solutions_operator_create_failure_is_fail_closed(tmp_path: Path) -> None:
    database, project_id = _database(tmp_path)
    calls: list[str] = []

    class ExplodingStore:
        def __init__(self, database: Database) -> None:
            self.database = database

        def consumed_count(self) -> int:
            return 0

        def create(self, **kwargs: object) -> None:
            raise RuntimeError("synthetic receipt create failure")

    class FakeSolutionService:
        def generate(self, project_id: str, **kwargs: object) -> dict[str, object]:
            calls.append("provider-boundary")
            return {}

    def factory(db: Database) -> ExplodingStore:
        return ExplodingStore(db)

    with pytest.raises(RuntimeError, match="receipt create failure"):
        run_solutions_canary(
            database=database, project_id=project_id, actor="test-operator",
            solution_service=FakeSolutionService(), participant="railway_stage_b",
            receipt_store_factory=factory,  # type: ignore[arg-type]
        )
    assert calls == []


def test_local_prd_operator_is_provider_free_and_persists_success_receipt(tmp_path: Path) -> None:
    database, project_id = _database(tmp_path)
    database.execute(
        "UPDATE projects SET current_snapshot_id = ? WHERE id = ?",
        ("synthetic-snapshot", project_id),
    )

    class FakeDocumentLoop:
        def run(self, project_id: str, doc_type: str, **kwargs: object) -> dict[str, object]:
            assert doc_type == "prd"
            return {"status": "completed", "version": 1}

    result = run_local_prd_canary(
        database=database, project_id=project_id, actor="test-operator",
        document_loop=FakeDocumentLoop(), participant="railway_stage_b",
    )
    assert result["status"] == "SUCCEEDED"
    assert result["transport_count"] == 0
    assert result["budget_consumed"] == 0


def test_stage_b_guard_rejects_other_participants_before_project_flow(tmp_path: Path) -> None:
    database, project_id = _database(tmp_path)
    with pytest.raises(StageBGuardError, match="STAGE_B_PARTICIPANT_REQUIRED"):
        run_solutions_canary(
            database=database, project_id=project_id, actor="test-operator",
            solution_service=object(), participant="beta_003",
        )


def test_product_flow_pre_readback_failure_is_fail_closed(tmp_path: Path) -> None:
    database, project_id = _database(tmp_path)
    calls: list[str] = []

    class BrokenReadbackStore(StageBEvaluationReceiptStore):
        def inspect(self, evaluation_id: str) -> dict[str, object]:
            raise RuntimeError("synthetic readback failure")

    factory_calls = 0

    def factory(db: Database) -> StageBEvaluationReceiptStore:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 2:
            return BrokenReadbackStore(database=db)
        return StageBEvaluationReceiptStore(database=db)

    class FakeSolutionService:
        def generate(self, project_id: str, **kwargs: object) -> dict[str, object]:
            calls.append("provider-boundary")
            return {}

    with pytest.raises(RuntimeError, match="readback failure"):
        run_solutions_canary(
            database=database, project_id=project_id, actor="test-operator",
            solution_service=FakeSolutionService(), participant="railway_stage_b",
            receipt_store_factory=factory,
        )
    assert calls == []
    assert factory_calls == 2


def test_non_synthetic_project_is_rejected_before_product_flow(tmp_path: Path) -> None:
    database = Database(tmp_path / "insightforge.sqlite3")
    database.init_schema()
    database.execute(
        "INSERT INTO projects(id, title, summary, status, project_origin, exclude_from_beta_metrics, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', 'user', 0, '2026-01-01', '2026-01-01')",
        ("real-project", "Real", "Real project"),
    )
    with pytest.raises(StageBGuardError, match="STAGE_B_SYNTHETIC_PROJECT_REQUIRED"):
        run_solutions_canary(
            database=database, project_id="real-project", actor="test-operator",
            solution_service=object(), participant="railway_stage_b",
        )


def test_operator_adds_no_public_diagnostic_route() -> None:
    from app.main import create_app

    application = create_app(seed=False)
    paths = {route.path for route in application.routes}
    assert not any(
        any(token in path for token in ("canary", "diagnostic", "observability-execute", "private-artifact"))
        for path in paths
    )
