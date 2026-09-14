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
