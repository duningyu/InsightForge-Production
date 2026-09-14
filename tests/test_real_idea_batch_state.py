from __future__ import annotations

import pytest

from app.db import Database
from app.services.real_idea_evaluation import (
    ExpectedSeedFailure,
    RealIdeaEvaluationService,
)


RAW_IDEA = "我想做一个帮助用户整理灵感并持续行动的小工具。"


@pytest.fixture()
def evaluation_service(tmp_path):
    database = Database(tmp_path / "real-idea-state.db")
    database.init_schema()
    service = RealIdeaEvaluationService(database, durable_budget=6)
    service.start_batch("batch-1")
    return service


def test_batch_start_is_atomic_and_internal_identity_is_set(evaluation_service):
    sample = evaluation_service.start_sample("batch-1", RAW_IDEA)

    project = evaluation_service.read_project(sample.project_id)

    assert project["project_origin"] == "user"
    assert project["exclude_from_beta_metrics"] == 1
    assert sample.raw_idea_sha256
    assert sample.state == "QUICKSTART_PENDING"


def test_failed_sample_start_rolls_back_project_and_evaluation_rows(evaluation_service):
    with pytest.raises(ExpectedSeedFailure):
        evaluation_service.start_sample(
            "batch-1", RAW_IDEA, fail_after_project=True
        )

    assert evaluation_service.count_projects() == 0
    assert evaluation_service.count_samples("batch-1") == 0


def test_batch_and_sample_state_transitions_are_fail_closed(evaluation_service):
    sample = evaluation_service.start_sample("batch-1", RAW_IDEA)

    evaluation_service.transition_sample(
        sample.sample_id, from_state="QUICKSTART_PENDING", to_state="OPERATIONAL_INCOMPLETE"
    )
    evaluation_service.transition_batch(
        "batch-1", from_state="RUNNING", to_state="PARTIAL"
    )

    assert evaluation_service.read_sample(sample.sample_id).state == "OPERATIONAL_INCOMPLETE"
    assert evaluation_service.read_batch("batch-1").status == "PARTIAL"

    with pytest.raises(ValueError):
        evaluation_service.transition_sample(
            sample.sample_id, from_state="OPERATIONAL_INCOMPLETE", to_state="COMPLETED"
        )


def test_rollback_sample_start_removes_only_the_new_isolated_sample(evaluation_service):
    first = evaluation_service.start_sample("batch-1", RAW_IDEA)
    second = evaluation_service.start_sample("batch-1", RAW_IDEA + " 第二个")

    evaluation_service.rollback_sample_start(first.sample_id)

    assert evaluation_service.read_sample(first.sample_id) is None
    assert evaluation_service.read_project(first.project_id) is None
    assert evaluation_service.read_sample(second.sample_id).project_id == second.project_id
    assert evaluation_service.read_project(second.project_id)["project_origin"] == "user"


def _terminal_sample(service, key_index: int, state: str):
    sample = service.start_sample("batch-1", f"{RAW_IDEA} {key_index}")
    if state == "COMPLETED":
        service.transition_sample(
            sample.sample_id,
            from_state="QUICKSTART_PENDING",
            to_state="AWAITING_BRIEF_REVIEW",
        )
        service.transition_sample(
            sample.sample_id,
            from_state="AWAITING_BRIEF_REVIEW",
            to_state="AWAITING_SOLUTION_REVIEW",
        )
        service.transition_sample(
            sample.sample_id,
            from_state="AWAITING_SOLUTION_REVIEW",
            to_state="COMPLETED",
        )
    else:
        service.transition_sample(
            sample.sample_id,
            from_state="QUICKSTART_PENDING",
            to_state=state,
        )
    return sample


def test_three_sample_batch_is_partial_when_one_operationally_incomplete(evaluation_service):
    _terminal_sample(evaluation_service, 1, "COMPLETED")
    _terminal_sample(evaluation_service, 2, "COMPLETED")
    _terminal_sample(evaluation_service, 3, "OPERATIONAL_INCOMPLETE")

    result = evaluation_service.finalize_batch("batch-1")

    assert result.status == "PARTIAL"
    assert result.sample_statuses == {
        "REAL_IDEA_01": "COMPLETED",
        "REAL_IDEA_02": "COMPLETED",
        "REAL_IDEA_03": "OPERATIONAL_INCOMPLETE",
    }


@pytest.mark.parametrize(
    "violation",
    [
        "cross_sample_binding",
        "wrong_version",
        "budget_overrun",
        "search_attempt",
        "silent_ack",
        "unsupported_verified_fact",
    ],
)
def test_integrity_violation_is_fail(evaluation_service, violation):
    evaluation_service.inject_integrity_violation("batch-1", violation)

    assert evaluation_service.finalize_batch("batch-1").status == "FAIL"
