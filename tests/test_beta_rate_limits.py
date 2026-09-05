from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.errors import BetaDailyLimitReached, StructuredRuntimeRecoveryError
from app.schemas import IdeaBriefDraft
from app.services.ai_runtime import DeterministicDemoRuntime
from app.services.beta_usage import BetaUsageService
from app.services.credential_store import CredentialStore
from app.services.hybrid_runtime import HybridStructuredRuntime
from app.services.model_profiles import ModelProfileService
from app.services.projects import ProjectService
from app.services.provider_adapters import ProviderCallError
from app.main import create_app


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"
SHANGHAI = ZoneInfo("Asia/Shanghai")


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class MemoryCredentialBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


@pytest.fixture()
def usage_db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "insightforge.sqlite3")
    database.init_schema()
    return database


@pytest.fixture()
def clock() -> MutableClock:
    return MutableClock(datetime(2026, 8, 31, 9, 0, tzinfo=SHANGHAI))


def _usage(
    database: Database,
    clock: MutableClock,
    *,
    participant: str = "beta_001",
    beta_mode: bool = True,
    limits: dict[str, int] | None = None,
) -> BetaUsageService:
    return BetaUsageService(
        database,
        participant_id=participant,
        beta_mode=beta_mode,
        timezone_name="Asia/Shanghai",
        limits=limits,
        clock=clock,
    )


def _count(database: Database, participant: str, operation: str) -> int:
    row = database.fetch_one(
        """
        SELECT request_count FROM beta_daily_usage
        WHERE participant_id=? AND operation_type=?
        """,
        (participant, operation),
    )
    return int(row["request_count"]) if row else 0


def test_solution_limit_allows_first_ten(usage_db, clock):
    service = _usage(usage_db, clock)

    decisions = [service.consume("solution_generation") for _ in range(10)]

    assert [decision.used for decision in decisions] == list(range(1, 11))
    assert all(decision.allowed for decision in decisions)


def test_solution_limit_rejects_eleventh(usage_db, clock):
    service = _usage(usage_db, clock)
    for _ in range(10):
        service.consume("solution_generation")

    with pytest.raises(BetaDailyLimitReached) as captured:
        service.consume("solution_generation")

    assert captured.value.as_payload() == {
        "error_code": "BETA_DAILY_LIMIT_REACHED",
        "operation": "solution_generation",
        "operation_type": "solution_generation",
        "blocked_operation": "solution_generation",
        "limit": 10,
        "used": 10,
        "remaining": 0,
        "reset_at": "2026-09-01T00:00:00+08:00",
        "message": "该类 Beta AI 操作的今日额度已达到测试上限；其他操作额度不受影响。",
    }
    assert _count(usage_db, "beta_001", "solution_generation") == 10


def test_document_limit_shared_by_prd_and_techdoc(usage_db, clock):
    service = _usage(usage_db, clock)
    for _ in range(5):
        service.consume("document_generation")  # PRD
        service.consume("document_generation")  # TechDoc

    with pytest.raises(BetaDailyLimitReached):
        service.consume("document_generation")

    assert _count(usage_db, "beta_001", "document_generation") == 10


def test_evidence_limit_is_twenty(usage_db, clock):
    service = _usage(usage_db, clock)
    for _ in range(20):
        service.consume("evidence_analysis")

    with pytest.raises(BetaDailyLimitReached):
        service.consume("evidence_analysis")


def test_limit_resets_next_local_day(usage_db, clock):
    service = _usage(
        usage_db, clock, limits={"solution_generation": 1, "document_generation": 1, "evidence_analysis": 1}
    )
    service.consume("solution_generation")
    clock.value = datetime(2026, 9, 1, 0, 0, tzinfo=SHANGHAI)

    decision = service.consume("solution_generation")

    assert decision.used == 1
    rows = usage_db.fetch_all(
        "SELECT usage_date, request_count FROM beta_daily_usage ORDER BY usage_date"
    )
    assert rows == [
        {"usage_date": "2026-08-31", "request_count": 1},
        {"usage_date": "2026-09-01", "request_count": 1},
    ]


def test_beta001_limit_does_not_affect_beta002(usage_db, clock):
    first = _usage(usage_db, clock, participant="beta_001", limits={"solution_generation": 1})
    second = _usage(usage_db, clock, participant="beta_002", limits={"solution_generation": 1})
    first.consume("solution_generation")

    assert second.consume("solution_generation").used == 1


def test_non_beta_mode_not_limited(usage_db, clock):
    service = _usage(usage_db, clock, participant="local", beta_mode=False)

    decisions = [service.consume("solution_generation") for _ in range(30)]

    assert all(decision.counted is False for decision in decisions)
    assert usage_db.fetch_one("SELECT COUNT(*) AS n FROM beta_daily_usage")["n"] == 0


class OneShotAdapter:
    def __init__(self, before_return=None, error: Exception | None = None) -> None:
        self.before_return = before_return
        self.error = error
        self.calls = 0

    def design_solutions(self, _brief):
        self.calls += 1
        if self.before_return:
            self.before_return()
        if self.error:
            raise self.error
        raise AssertionError("test does not require a provider response")

    def close(self) -> None:
        pass


class OneShotFactory:
    def __init__(self, adapter: OneShotAdapter) -> None:
        self.adapter = adapter

    def __call__(self, **_configuration):
        return self.adapter


def _profile_runtime(usage_db, clock, adapter: OneShotAdapter, *, with_key: bool = True):
    backend = MemoryCredentialBackend()
    profiles = ModelProfileService(usage_db, credential_store=CredentialStore(backend=backend))
    profile = profiles.create(
        display_name="quota-test",
        provider="openai",
        model_id="quota-test-model",
        api_key="safe-test-key",
        is_default=True,
    )
    if not with_key:
        stored = usage_db.fetch_one(
            "SELECT credential_ref FROM model_profiles WHERE id=?", (profile["id"],)
        )
        profiles.credential_store.delete(stored["credential_ref"])
    usage = _usage(usage_db, clock, limits={"solution_generation": 2})
    runtime = HybridStructuredRuntime(
        profiles,
        local_runtime=DeterministicDemoRuntime(fixture_path=FIXTURE_PATH),
        adapter_factory=OneShotFactory(adapter),
        before_provider_call=usage.consume,
        after_provider_failure=lambda _operation, decision: usage.release(decision),
    ).for_project(None)
    brief = IdeaBriefDraft(
        original_idea="测试限额",
        target_user="测试者",
        problem="验证真实请求边界",
        desired_outcome="精确计数",
        known_resources=[],
        constraints=[],
        unknowns=[],
        provenance={"problem": "user_input"},
        clarification_required=False,
        clarification_question=None,
    )
    return runtime, brief, usage


def test_limit_consumed_before_real_provider_call(usage_db, clock):
    adapter = OneShotAdapter(
        before_return=lambda: (
            _count(usage_db, "beta_001", "solution_generation") == 1
            or (_ for _ in ()).throw(AssertionError("quota was not consumed before dispatch"))
        ),
        error=ProviderCallError("provider_error", "safe", False),
    )
    runtime, brief, _usage_service = _profile_runtime(usage_db, clock, adapter)

    with pytest.raises(StructuredRuntimeRecoveryError):
        runtime.design_solutions(brief)

    assert adapter.calls == 1


def test_local_validation_failure_does_not_consume(usage_db, clock):
    runtime, brief, _usage_service = _profile_runtime(
        usage_db, clock, OneShotAdapter(), with_key=False
    )

    with pytest.raises(StructuredRuntimeRecoveryError) as captured:
        runtime.design_solutions(brief)

    assert captured.value.error_code == "MODEL_CREDENTIAL_MISSING"
    assert _count(usage_db, "beta_001", "solution_generation") == 0


def test_provider_failure_releases_reserved_quota(usage_db, clock):
    adapter = OneShotAdapter(error=ProviderCallError("provider_error", "safe", False))
    runtime, brief, _usage_service = _profile_runtime(usage_db, clock, adapter)

    with pytest.raises(StructuredRuntimeRecoveryError):
        runtime.design_solutions(brief)

    assert _count(usage_db, "beta_001", "solution_generation") == 0


def test_provider_failure_does_not_burn_existing_successful_quota(usage_db, clock):
    adapter = OneShotAdapter(error=ProviderCallError("provider_error", "safe", False))
    usage = _usage(usage_db, clock, limits={"solution_generation": 3})
    usage.consume("solution_generation")
    runtime, brief, _usage_service = _profile_runtime(usage_db, clock, adapter)

    with pytest.raises(StructuredRuntimeRecoveryError):
        runtime.design_solutions(brief)

    assert _count(usage_db, "beta_001", "solution_generation") == 1


def test_atomic_limit_prevents_overrun(usage_db, clock):
    barrier = Barrier(2)

    def consume_once() -> str:
        service = _usage(
            usage_db, clock, limits={"solution_generation": 1, "document_generation": 1, "evidence_analysis": 1}
        )
        barrier.wait()
        try:
            service.consume("solution_generation")
            return "allowed"
        except BetaDailyLimitReached:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: consume_once(), range(2)))

    assert sorted(results) == ["allowed", "rejected"]
    assert _count(usage_db, "beta_001", "solution_generation") == 1


def test_existing_content_readable_after_limit(usage_db, clock):
    project = ProjectService(usage_db).create_project(
        title="限额后仍可查看", summary="已有业务内容", actor="tester"
    )
    service = _usage(usage_db, clock, limits={"solution_generation": 1})
    service.consume("solution_generation")
    with pytest.raises(BetaDailyLimitReached):
        service.consume("solution_generation")

    restored = ProjectService(usage_db).get_project(project["id"])

    assert restored["title"] == "限额后仍可查看"


def test_unknown_operation_is_rejected_without_database_write(usage_db, clock):
    service = _usage(usage_db, clock)

    with pytest.raises(ValueError, match="unsupported beta usage operation"):
        service.consume("interpret_idea")

    assert usage_db.fetch_one("SELECT COUNT(*) AS n FROM beta_daily_usage")["n"] == 0


def test_rate_limit_http_contract_is_429_and_ui_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("BETA_MODE", "false")
    application = create_app(database_path=tmp_path / "api.sqlite3", seed=False)

    @application.get("/_test/beta-limit")
    def fail_with_limit():
        raise BetaDailyLimitReached(
            operation="solution_generation",
            limit=10,
            used=10,
            reset_at="2026-09-01T00:00:00+08:00",
        )

    with TestClient(application) as client:
        response = client.get("/_test/beta-limit")

    assert response.status_code == 429
    assert response.json() == {
        "error_code": "BETA_DAILY_LIMIT_REACHED",
        "operation": "solution_generation",
        "operation_type": "solution_generation",
        "blocked_operation": "solution_generation",
        "limit": 10,
        "used": 10,
        "remaining": 0,
        "reset_at": "2026-09-01T00:00:00+08:00",
        "message": "该类 Beta AI 操作的今日额度已达到测试上限；其他操作额度不受影响。",
    }
    app_js = (Path(__file__).parents[1] / "app" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "body.detail || body.message" in app_js
