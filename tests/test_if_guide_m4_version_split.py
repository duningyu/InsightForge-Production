from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.if_guide_m4 import M4EvaluationService
from test_if_guide_m4_experiment import _create_experiment, _create_project_with_owner


def _frozen_fixture(db):
    service = M4EvaluationService(db)
    _create_experiment(service)
    service.freeze_experiment(
        experiment_id="m4-exp-001", account_id="m4-owner", expected_revision=1
    )
    service.create_participant(
        experiment_id="m4-exp-001",
        participant_id="p-001",
        account_id="m4-owner",
        purpose="LEARNING",
        prior_ai_familiarity="some",
        prior_product_experience="some",
        task_category="prototype",
    )
    project_id = _create_project_with_owner(db)
    service.create_session(
        session_id="s-001",
        experiment_id="m4-exp-001",
        participant_id="p-001",
        account_id="m4-owner",
        project_id=project_id,
        condition="STATIC_TEMPLATE",
        assignment_rule_version="balanced-by-purpose-v1",
        condition_version="static-v1",
        source_commit="m4-source",
        deployment_id="m4-deploy",
    )
    return service, project_id


def test_frozen_runtime_metadata_change_marks_split_and_prevents_silent_pooling(db):
    service, _ = _frozen_fixture(db)

    result = service.record_version_observation(
        experiment_id="m4-exp-001",
        account_id="m4-owner",
        observed_metadata={"source_commit": "different-source"},
    )

    assert result["version_split"] is True
    assert result["mismatches"] == ["source_commit"]
    assert service.get_session(session_id="s-001", account_id="m4-owner")["version_split"] == 1
    with pytest.raises(ConflictError, match="EXPERIMENT_VERSION_SPLIT"):
        service.aggregateable_session(session_id="s-001", account_id="m4-owner")


def test_matching_frozen_runtime_metadata_does_not_split(db):
    service, _ = _frozen_fixture(db)

    result = service.record_version_observation(
        experiment_id="m4-exp-001",
        account_id="m4-owner",
        observed_metadata={
            "source_commit": "m4-source",
            "deployment_id": "m4-deploy",
            "assignment_rule": "balanced-by-purpose-v1",
        },
    )

    assert result["version_split"] is False
    assert result["mismatches"] == []
