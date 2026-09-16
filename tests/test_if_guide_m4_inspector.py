from __future__ import annotations

import pytest

from app.services.if_guide_m4 import M4EvaluationService
from app.services.if_guide_m4_inspector import M4InspectorService
from tests.test_if_guide_m4_experiment import (
    _create_experiment,
    _create_project_with_owner,
)


def _create_session(db) -> None:
    service = M4EvaluationService(db)
    _create_experiment(service)
    service.freeze_experiment(
        experiment_id="m4-exp-001", account_id="m4-owner", expected_revision=1
    )
    service.create_participant(
        experiment_id="m4-exp-001",
        participant_id="m4-participant-001",
        account_id="m4-owner",
        purpose="PERSONAL_USE",
        prior_ai_familiarity="medium",
        prior_product_experience="low",
        task_category="prototype",
    )
    project_id = _create_project_with_owner(db)
    service.create_session(
        session_id="m4-inspect-session",
        experiment_id="m4-exp-001",
        participant_id="m4-participant-001",
        account_id="m4-owner",
        project_id=project_id,
        condition="INSIGHTFORGE_STATEFUL",
        assignment_rule_version="balanced-by-purpose-v1",
        condition_version="if-v1",
        source_commit="m4-source",
        deployment_id="m4-deploy",
    )


def test_inspector_returns_safe_session_metadata_only(db):
    _create_session(db)

    result = M4InspectorService(db).inspect_session(
        session_id="m4-inspect-session", account_id="m4-owner"
    )

    assert result["safe_only"] is True
    assert result["session_id"] == "m4-inspect-session"
    assert result["experiment_id"] == "m4-exp-001"
    assert result["project_id"] == "m4-project-001"
    assert result["participant_purpose"] == "PERSONAL_USE"
    assert result["source_commit"] == "m4-source"
    assert result["provider_calls"] == 0
    assert result["provider_cost"] == 0
    assert "raw_idea" not in result
    assert "content" not in result
    assert "private_artifact_body" not in result


def test_inspector_is_owner_scoped(db):
    _create_session(db)

    with pytest.raises(PermissionError, match="M4_ACCOUNT_ACCESS_DENIED"):
        M4InspectorService(db).inspect_session(
            session_id="m4-inspect-session", account_id="other-account"
        )
