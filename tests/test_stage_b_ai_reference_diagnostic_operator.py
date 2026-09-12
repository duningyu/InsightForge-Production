from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database
from app.schemas import AIReferenceDraft
from app.services.ai_reference import AIReferenceService
from app.services.ai_runtime import ManagedQwenStructuredRuntime
from app.services.provider_dispatch_ledger import ProviderDispatchLedger
from app.services.provider_adapters import ProviderCallError
from app.services.projects import ProjectService
from app.services.stage_b_evaluation import StageBEvaluationReceiptStore, StageBGuardError


def _project(database: Database) -> str:
    database.init_schema()
    return ProjectService(database).create_project(
        title="合成求职进度项目", summary="记录投递、笔试、面试和跟进事项。", actor="test"
    )["id"]


class _FakeAdapter:
    def __init__(self, **_kwargs):
        self.last_safe_diagnostic = {"message_content_present": True, "message_content_char_count": 12}

    def generate_ai_reference(self, _context):
        return AIReferenceDraft(possible_target_users=["准备实习求职的学生"])

    def close(self):
        return None


class _CountingRuntime:
    def __init__(self):
        self.calls = 0

    def generate_ai_reference(self, _context, *, evaluation_context=None):
        self.calls += 1
        if evaluation_context is not None:
            assert evaluation_context.evaluation_type == "AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY"
        return AIReferenceDraft(possible_target_users=["合成目标用户"])


class _503Adapter(_FakeAdapter):
    def generate_ai_reference(self, _context):
        raise ProviderCallError(
            "provider_error",
            "上游服务暂时不可用",
            False,
            safe_diagnostic={
                "provider_error_source": "UPSTREAM_HTTP_503",
                "provider_http_status": 503,
            },
        )


def _managed_runtime(database: Database) -> ManagedQwenStructuredRuntime:
    return ManagedQwenStructuredRuntime(
        model="qwen3.7-flash",
        api_key="test-only-placeholder",
        adapter_factory=_FakeAdapter,
        dispatch_ledger=ProviderDispatchLedger(database),
    )


def _managed_runtime_with_adapter(database: Database, adapter_factory) -> ManagedQwenStructuredRuntime:
    return ManagedQwenStructuredRuntime(
        model="qwen3.7-flash",
        api_key="test-only-placeholder",
        adapter_factory=adapter_factory,
        dispatch_ledger=ProviderDispatchLedger(database),
    )


def test_stage_b_ai_reference_shape_operator_has_a_product_path(tmp_path: Path) -> None:
    from scripts.stage_b_evaluation_inspect import run_ai_reference_shape_canary

    database = Database(tmp_path / "stage-b-operator.sqlite3")
    project_id = _project(database)
    result = run_ai_reference_shape_canary(
        database=database,
        project_id=project_id,
        actor="stage-b-operator-test",
        runtime=_CountingRuntime(),
    )

    assert result["execution_mode"] == "INSIGHTFORGE"
    assert result["evaluation_type"] == "AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY"


def test_operator_fake_success_links_dispatch_to_evaluation(tmp_path: Path) -> None:
    from scripts.stage_b_evaluation_inspect import run_ai_reference_shape_canary

    database = Database(tmp_path / "linked.sqlite3")
    project_id = _project(database)
    result = run_ai_reference_shape_canary(
        database=database,
        project_id=project_id,
        actor="operator-test",
        runtime=_managed_runtime(database),
    )

    assert result["status"] == "SUCCEEDED"
    assert result["dispatch_count"] == 1
    assert result["transport_count"] == 1
    assert result["dispatch_permit_id"]
    assert result["dispatch_evaluation_id"] == result["evaluation_id"]
    assert result["artifact_exists"] is True


@pytest.mark.parametrize("failure_point", ["create", "readback"])
def test_operator_fails_closed_before_provider_on_preflight_failure(tmp_path: Path, failure_point: str, monkeypatch) -> None:
    from scripts import stage_b_evaluation_inspect as operator

    database = Database(tmp_path / f"{failure_point}.sqlite3")
    project_id = _project(database)
    runtime = _CountingRuntime()
    original = StageBEvaluationReceiptStore

    class FailingStore(original):
        def create(self, **kwargs):
            if failure_point == "create":
                raise RuntimeError("synthetic create failure")
            return super().create(**kwargs)

        def inspect(self, evaluation_id):
            row = super().inspect(evaluation_id)
            if failure_point == "readback":
                row["transport_attempted"] = True
            return row

    monkeypatch.setattr(operator, "StageBEvaluationReceiptStore", FailingStore)
    with pytest.raises((RuntimeError, StageBGuardError)):
        operator.run_ai_reference_shape_canary(
            database=database,
            project_id=project_id,
            actor="operator-test",
            runtime=runtime,
        )
    assert runtime.calls == 0
    assert database.fetch_one("SELECT COUNT(*) AS n FROM provider_dispatch_permits")["n"] == 0
    assert database.fetch_one("SELECT COUNT(*) AS n FROM provider_attempts")["n"] == 0


def test_ordinary_service_call_does_not_create_diagnostic_evaluation(tmp_path: Path) -> None:
    database = Database(tmp_path / "ordinary.sqlite3")
    project_id = _project(database)
    AIReferenceService(database).generate(
        project_id, actor="user", runtime=_CountingRuntime(), idempotency_key="ordinary-1"
    )
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM stage_b_evaluation_receipts "
        "WHERE evaluation_type='AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY'"
    )["n"] == 0


def test_operator_fake_503_preserves_linkage_and_transport_failure_stage(tmp_path: Path) -> None:
    from scripts.stage_b_evaluation_inspect import inspect_receipt, run_ai_reference_shape_canary

    database = Database(tmp_path / "503.sqlite3")
    project_id = _project(database)
    runtime = _managed_runtime_with_adapter(database, _503Adapter)

    with pytest.raises(Exception):
        run_ai_reference_shape_canary(
            database=database,
            project_id=project_id,
            actor="operator-test",
            runtime=runtime,
        )

    row = database.fetch_one(
        "SELECT evaluation_id FROM stage_b_evaluation_receipts "
        "WHERE evaluation_type='AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY'"
    )
    result = inspect_receipt(database, row["evaluation_id"])
    assert result["dispatch_count"] == 1
    assert result["transport_count"] == 1
    assert result["dispatch_evaluation_id"] == result["evaluation_id"]
    assert result["failure_classification"] == "PROVIDER_5XX"
    assert result["failure_stage"] == "PROVIDER_TRANSPORT"
    assert result["output_contract_attempted"] in (False, 0)
    assert database.fetch_one("SELECT COUNT(*) AS n FROM projects")["n"] == 1


def test_operator_rejects_non_stage_b_participant_before_provider(tmp_path: Path) -> None:
    from scripts.stage_b_evaluation_inspect import run_ai_reference_shape_canary

    database = Database(tmp_path / "guard.sqlite3")
    project_id = _project(database)
    runtime = _CountingRuntime()
    with pytest.raises(StageBGuardError, match="STAGE_B_PARTICIPANT_REQUIRED"):
        run_ai_reference_shape_canary(
            database=database,
            project_id=project_id,
            actor="operator-test",
            runtime=runtime,
            participant="railway_stage_a",
        )
    assert runtime.calls == 0
    assert database.fetch_one("SELECT COUNT(*) AS n FROM stage_b_evaluation_receipts")["n"] == 0


def test_operator_help_does_not_create_receipt_or_initialize_provider(tmp_path: Path, monkeypatch) -> None:
    from scripts import stage_b_evaluation_inspect as operator

    called = False

    def fail_create_app(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("--help must not initialize the application")

    monkeypatch.setattr("app.main.create_app", fail_create_app)
    with pytest.raises(SystemExit) as exc_info:
        operator.main(["ai-reference-shape-canary", "--help"])
    assert exc_info.value.code == 0
    assert called is False


def test_operator_runs_two_evaluations_without_cross_linkage(tmp_path: Path) -> None:
    from scripts.stage_b_evaluation_inspect import run_ai_reference_shape_canary

    database = Database(tmp_path / "isolated.sqlite3")
    project_id = _project(database)
    first = run_ai_reference_shape_canary(
        database=database, project_id=project_id, actor="operator-a", runtime=_managed_runtime(database)
    )
    second = run_ai_reference_shape_canary(
        database=database, project_id=project_id, actor="operator-b", runtime=_managed_runtime(database)
    )
    assert first["evaluation_id"] != second["evaluation_id"]
    rows = database.fetch_all(
        "SELECT r.evaluation_id, l.evaluation_id AS dispatch_evaluation_id "
        "FROM stage_b_evaluation_receipts AS r "
        "JOIN provider_dispatch_evaluation_links AS l "
        "ON l.permit_id = r.dispatch_permit_id "
        "WHERE r.evaluation_type='AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY' ORDER BY r.rowid"
    )
    assert [(row["evaluation_id"], row["dispatch_evaluation_id"]) for row in rows] == [
        (row["evaluation_id"], row["evaluation_id"]) for row in rows
    ]
