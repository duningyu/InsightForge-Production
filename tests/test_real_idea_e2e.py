from __future__ import annotations

import pytest

from app.errors import StructuredRuntimeRecoveryError
from app.schemas import IdeaBriefDraft
from app.services.real_idea_evaluation import RealIdeaEvaluationService
from app.services.quick_start import QuickStartService
from app.services.evaluation_policy import EvaluationExecutionPolicy
from tests.test_real_idea_feedback_and_documents import FakeSolutionsRuntime


RAW_IDEA = "我平时会收藏很多 AI 工具和教程，但过几天就忘了当时为什么收藏，也不知道哪些真的适合自己。"


class FakeQuickStartRuntime:
    mode = "isolated_fake"
    provider = "isolated_fake"
    model = "fake-quickstart"
    prompt_version = "test"
    schema_version = "test"

    def __init__(self, outcome="SUCCESS"):
        self.outcome = outcome
        self.provider_transport_attempts = 0

    def for_project(self, _project_id, **_kwargs):
        return self

    def interpret_idea(self, payload):
        if self.outcome == "QUICKSTART_TIMEOUT":
            raise StructuredRuntimeRecoveryError(
                error_code="TRANSPORT_TIMEOUT", message="fake timeout",
                recovery_actions=("retry_later",), preserved_input=payload,
            )
        self.provider_transport_attempts += 1
        if self.outcome == "QUICKSTART_INCOMPLETE":
            return IdeaBriefDraft(
                original_idea=payload.idea, target_user="", problem="", desired_outcome="",
                provenance={"original_idea": "user_input", "target_user": "model_hypothesis",
                             "problem": "model_hypothesis", "desired_outcome": "model_hypothesis"},
            )
        return IdeaBriefDraft(
            original_idea=payload.idea, target_user="收藏 AI 工具和教程的人",
            problem="收藏内容分散且难以判断是否适合自己",
            desired_outcome="集中整理并明确下一步",
            provenance={"original_idea": "user_input", "target_user": "model_hypothesis",
                        "problem": "model_hypothesis", "desired_outcome": "model_hypothesis"},
        )


class FakeBatch:
    def __init__(self, tmp_path):
        from app.db import Database
        self.db = Database(tmp_path / "e2e.sqlite3")
        self.db.init_schema()

    def run(self, outcomes):
        service = RealIdeaEvaluationService(self.db, durable_budget=6)
        batch_id = "batch-e2e"
        service.start_batch(batch_id)
        transports = 0
        for key, outcome in outcomes.items():
            sample = service.start_sample(batch_id, RAW_IDEA)
            quick = FakeQuickStartRuntime(outcome)
            result = service.run_quickstart(sample.sample_id, raw_idea=RAW_IDEA, runtime=quick)
            transports += quick.provider_transport_attempts
            if result["status"] != "AWAITING_BRIEF_REVIEW":
                continue
            QuickStartService(self.db, service.projects, quick).confirm_brief(
                sample.project_id, human_confirmed=True,
                note="provider-free fake review", actor="test",
            )
            solutions_runtime = FakeSolutionsRuntime()
            solved = service.run_solutions(sample.sample_id, runtime=solutions_runtime)
            transports += solved.transport_count
            service.record_selection(sample.sample_id, selected_ordinal=2, reason="第二个方案更适合当前需求。")
            service.transition_sample(sample.sample_id, from_state="AWAITING_SOLUTION_REVIEW", to_state="COMPLETED")
        final = service.finalize_batch(batch_id)
        return type("Result", (), {"status": final.status, "provider_transport_count": transports, "search_count": 0})()

    def run_all_success(self):
        return self.run({key: "SUCCESS" for key in ("REAL_IDEA_01", "REAL_IDEA_02", "REAL_IDEA_03")})

    def run_with_violation(self, violation):
        service = RealIdeaEvaluationService(self.db, durable_budget=6)
        batch_id = "batch-violation"
        service.start_batch(batch_id)
        service.inject_integrity_violation(batch_id, violation)
        return type("Result", (), {"status": service.finalize_batch(batch_id).status})()


@pytest.fixture
def fake_batch(tmp_path):
    return FakeBatch(tmp_path)


def test_partial_batch_has_two_completed_samples_and_one_operational_incomplete(fake_batch):
    result = fake_batch.run(
        outcomes={"REAL_IDEA_01": "SUCCESS", "REAL_IDEA_02": "SUCCESS", "REAL_IDEA_03": "QUICKSTART_TIMEOUT"}
    )
    assert result.status == "PARTIAL"
    assert result.provider_transport_count == 4
    assert result.search_count == 0


def test_all_success_batch_is_pass(fake_batch):
    assert fake_batch.run_all_success().status == "PASS"


@pytest.mark.parametrize(
    "violation",
    ["cross_sample_project", "wrong_solution_id", "wrong_prd_version", "budget_overrun", "search", "silent_ack", "unsupported_fact"],
)
def test_e2e_integrity_violation_fails_closed(fake_batch, violation):
    assert fake_batch.run_with_violation(violation).status == "FAIL"
