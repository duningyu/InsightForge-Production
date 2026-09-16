from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.if_guide_m4 import M4EvaluationService
from test_if_guide_m4_experiment import _create_experiment, _create_project_with_owner


def _session(db, session_id="s-001"):
    service = M4EvaluationService(db)
    _create_experiment(service)
    service.freeze_experiment(
        experiment_id="m4-exp-001", account_id="m4-owner", expected_revision=1
    )
    service.create_participant(
        experiment_id="m4-exp-001",
        participant_id=f"p-{session_id}",
        account_id="m4-owner",
        purpose="LEARNING",
        prior_ai_familiarity="some",
        prior_product_experience="some",
        task_category="prototype",
    )
    project_id = _create_project_with_owner(db)
    service.create_session(
        session_id=session_id,
        experiment_id="m4-exp-001",
        participant_id=f"p-{session_id}",
        account_id="m4-owner",
        project_id=project_id,
        condition="STATIC_TEMPLATE",
        assignment_rule_version="balanced-by-purpose-v1",
        condition_version="static-v1",
        source_commit="m4-source",
        deployment_id="m4-deploy",
    )
    service.transition_session(
        session_id=session_id,
        account_id="m4-owner",
        target_state="READY",
        expected_revision=1,
    )
    service.transition_session(
        session_id=session_id,
        account_id="m4-owner",
        target_state="IN_PROGRESS",
        expected_revision=2,
    )
    return service, project_id


def test_completed_outcome_without_quality_evidence_is_quality_incomplete(db):
    service, _ = _session(db)
    result = service.finalize_session(
        session_id="s-001",
        account_id="m4-owner",
        expected_revision=3,
        outcome="COMPLETED",
    )

    assert result["outcome"] == "QUALITY_INCOMPLETE"
    assert result["state"] == "FINALIZED"


def test_withdrawal_is_final_and_preserves_reason(db):
    service, _ = _session(db)
    result = service.finalize_session(
        session_id="s-001",
        account_id="m4-owner",
        expected_revision=3,
        outcome="WITHDRAWN",
        reason="participant withdrew",
    )

    assert result["outcome"] == "WITHDRAWN"
    assert result["withdrawal_reason"] == "participant withdrew"


def test_integrity_failure_is_terminal_and_cannot_be_reopened(db):
    service, _ = _session(db)
    result = service.finalize_session(
        session_id="s-001",
        account_id="m4-owner",
        expected_revision=3,
        outcome="INTEGRITY_FAIL",
        reason="cross-account leak",
    )

    assert result["outcome"] == "INTEGRITY_FAIL"
    with pytest.raises(ConflictError, match="SESSION_FINALIZED"):
        service.finalize_session(
            session_id="s-001",
            account_id="m4-owner",
            expected_revision=4,
            outcome="COMPLETED",
        )

