from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db import Database
from app.errors import BetaDailyLimitReached
from app.schemas import IdeaBriefDraft, SolutionSetDraft
from app.services.beta_usage import BetaUsageService
from app.services.project_claims import ProjectClaimService
from app.services.solution_design import SolutionDesignService


def _brief() -> IdeaBriefDraft:
    return IdeaBriefDraft(
        original_idea="测试项目",
        target_user="测试用户",
        problem="测试问题",
        desired_outcome="测试结果",
        provenance={
            "original_idea": "user_input",
            "target_user": "user_input",
            "problem": "user_input",
            "desired_outcome": "user_input",
        },
    )


def _overengineered_set() -> SimpleNamespace:
    def candidate(title: str) -> SimpleNamespace:
        return SimpleNamespace(
            title=title,
            mechanism="assistant",
            required_data_class="none",
            automation_level="high",
            human_role="reviewer",
            core_decision_logic="model decision",
            major_dependency="model",
            requires_llm_runtime=True,
            requires_rag_runtime=False,
            requires_agent_runtime=False,
        )

    return SimpleNamespace(
        candidates=[candidate("方案 A"), candidate("方案 B")],
        llm_core_required=False,
        recommendation_candidate_id=None,
        recommendation_rationale="",
    )


class _RuntimeWithReservation:
    provider = "bailian"
    model = "qwen3.7-flash"
    prompt_version = "test"
    schema_version = "test"
    mode = "managed"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 1
    last_provider_diagnostic = {}

    def __init__(self, usage: BetaUsageService) -> None:
        self.usage = usage
        self.decision = None

    async def async_design_solutions(self, brief, **kwargs):
        self.decision = self.usage.consume("solution_generation")
        return _overengineered_set()

    def release_current_reservation(self) -> None:
        if self.decision is not None:
            self.usage.release(self.decision)
            self.decision = None


def test_provider_success_postprocess_failure_releases_user_quota(tmp_path):
    db = Database(tmp_path / "quota.sqlite3")
    db.init_schema()
    usage = BetaUsageService(
        db,
        participant_id="beta_003",
        beta_mode=True,
        limits={"solution_generation": 3, "evidence_analysis": 5},
    )
    runtime = _RuntimeWithReservation(usage)
    service = SolutionDesignService(db=db, runtime=runtime)
    service._confirmed_brief_row = lambda project_id: {"id": "brief-1"}
    service._brief_from_row = lambda row: _brief()

    result = __import__("asyncio").run(
        service.generate_async("project-1", actor="beta_003")
    )

    row = db.fetch_one(
        "SELECT request_count FROM beta_daily_usage WHERE participant_id=? AND operation_type=?",
        ("beta_003", "solution_generation"),
    )
    assert result["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
    assert row is None or row["request_count"] == 0


def test_quota_release_is_idempotent(tmp_path):
    db = Database(tmp_path / "release.sqlite3")
    db.init_schema()
    usage = BetaUsageService(
        db,
        participant_id="beta_003",
        beta_mode=True,
        limits={"solution_generation": 3},
    )
    decision = usage.consume("solution_generation")

    usage.release(decision)
    usage.release(decision)

    row = db.fetch_one(
        "SELECT request_count FROM beta_daily_usage WHERE participant_id=? AND operation_type=?",
        ("beta_003", "solution_generation"),
    )
    reservation = db.fetch_one(
        "SELECT state FROM beta_quota_reservations WHERE reservation_id=?",
        (decision.reservation_id,),
    )
    assert row is None or row["request_count"] == 0
    assert reservation["state"] == "RELEASED"


def test_quota_commit_is_idempotent(tmp_path):
    db = Database(tmp_path / "commit.sqlite3")
    db.init_schema()
    usage = BetaUsageService(
        db,
        participant_id="beta_003",
        beta_mode=True,
        limits={"solution_generation": 3},
    )
    decision = usage.consume("solution_generation")

    usage.commit(decision)
    usage.commit(decision)

    row = db.fetch_one(
        "SELECT request_count FROM beta_daily_usage WHERE participant_id=? AND operation_type=?",
        ("beta_003", "solution_generation"),
    )
    reservation = db.fetch_one(
        "SELECT state FROM beta_quota_reservations WHERE reservation_id=?",
        (decision.reservation_id,),
    )
    assert row["request_count"] == 1
    assert reservation["state"] == "COMMITTED"


def test_postprocess_failure_does_not_advertise_automatic_retry(tmp_path):
    db = Database(tmp_path / "retry.sqlite3")
    db.init_schema()
    usage = BetaUsageService(db, participant_id="beta_003", beta_mode=True, limits={"solution_generation": 3})
    runtime = _RuntimeWithReservation(usage)
    service = SolutionDesignService(db=db, runtime=runtime)
    service._confirmed_brief_row = lambda project_id: {"id": "brief-1"}
    service._brief_from_row = lambda row: _brief()

    result = __import__("asyncio").run(service.generate_async("project-1", actor="beta_003"))

    assert result["retryable"] is False
    assert result["recovery_actions"] == ["重新生成"]


def test_quota_limit_payload_is_operation_scoped():
    error = BetaDailyLimitReached(
        operation="evidence_analysis", limit=5, used=5, reset_at="2026-09-06T00:00:00+08:00"
    )
    payload = error.as_payload()

    assert payload["operation_type"] == "evidence_analysis"
    assert payload["blocked_operation"] == "evidence_analysis"
    assert payload["remaining"] == 0
    assert "global" not in payload["message"].lower()


def test_evidence_budget_exhaustion_preserves_unanalyzed_items(tmp_path):
    db = Database(tmp_path / "evidence.sqlite3")
    db.init_schema()
    claims = [
        {"id": f"claim-{index}", "claim_type": "target_user", "statement": f"claim {index}", "verification_status": "unverified"}
        for index in range(3)
    ]

    class Retrieval:
        def execute_retrieval(self, *args, **kwargs):
            return {"items": [], "run_id": "retrieval-1"}

    class Runtime:
        provider = "bailian"
        model = "qwen3.7-flash"
        prompt_version = "test"
        schema_version = "test"
        mode = "managed"
        max_model_rounds = 1
        max_tool_rounds = 0
        model_rounds_used = 1

        def analyze_evidence(self, **kwargs):
            raise BetaDailyLimitReached(
                operation="evidence_analysis", limit=5, used=5, reset_at="2026-09-06T00:00:00+08:00"
            )

    service = ProjectClaimService(db=db, retrieval=Retrieval(), runtime=Runtime())
    service.list_claims = lambda project_id: claims

    result = service.analyze_project_evidence("project-1", actor="beta_003")

    assert result["analysis"]["blocked_operation"] == "evidence_analysis"
    assert len(result["not_analyzed"]) == 3
    assert all(item["status"] == "NOT_ANALYZED_QUOTA_EXHAUSTED" for item in result["not_analyzed"])
