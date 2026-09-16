from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.if_guide_m4 import M4EvaluationService


def _create_experiment(service: M4EvaluationService) -> None:
    service.create_experiment(
        experiment_id="m4-exp-001",
        account_id="m4-owner",
        spec_version="m4-spec-v1",
        source_commit="m4-source",
        deployment_id="m4-deploy",
        condition_definitions={
            "STATIC_TEMPLATE": {"version": "static-v1"},
            "GENERAL_AI": {"version": "general-v1"},
            "INSIGHTFORGE_STATEFUL": {"version": "if-v1"},
        },
        assignment_rule="balanced-by-purpose-v1",
        metric_versions={"primary": "m4-primary-v1"},
        rubric_versions={"quality": "r1.1-v1"},
        threshold_policy={"mode": "BASELINE_ONLY"},
        operator_assistance_policy={"allowed": False},
    )


def _create_project_with_owner(db) -> str:
    project_id = "m4-project-001"
    with db.connect() as connection:
        connection.execute(
            """
            INSERT INTO projects (
                id, title, summary, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (
                project_id,
                "M4 Fixture",
                "M4 fixture project",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO project_intents (
                intent_id, project_id, owner_actor, purpose, raw_idea,
                revision, confirmed_at, created_at, updated_at
            ) VALUES (?, ?, 'm4-owner', 'LEARNING', ?, 1, ?, ?, ?)
            """,
            (
                "m4-intent-001",
                project_id,
                "M4 fixture",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
            ),
        )
    return project_id


def test_experiment_freeze_and_owned_session_lifecycle(db):
    service = M4EvaluationService(db)
    _create_experiment(service)

    with pytest.raises(ConflictError, match="EXPERIMENT_NOT_FROZEN"):
        service.create_participant(
            experiment_id="m4-exp-001",
            participant_id="p-001",
            account_id="m4-owner",
            purpose="LEARNING",
            prior_ai_familiarity="low",
            prior_product_experience="some",
            task_category="prototype",
        )

    frozen = service.freeze_experiment(
        experiment_id="m4-exp-001", account_id="m4-owner", expected_revision=1
    )
    assert frozen["state"] == "FROZEN"
    assert frozen["revision"] == 2

    service.create_participant(
        experiment_id="m4-exp-001",
        participant_id="p-001",
        account_id="m4-owner",
        purpose="LEARNING",
        prior_ai_familiarity="low",
        prior_product_experience="some",
        task_category="prototype",
    )
    project_id = _create_project_with_owner(db)
    session = service.create_session(
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
    assert session["state"] == "ASSIGNED"

    with pytest.raises(PermissionError, match="M4_ACCOUNT_ACCESS_DENIED"):
        service.get_session(session_id="s-001", account_id="other-account")

    with pytest.raises(PermissionError, match="M4_ACCOUNT_ACCESS_DENIED"):
        service.create_session(
            session_id="s-cross-account-project",
            experiment_id="m4-exp-001",
            participant_id="p-001",
            account_id="other-account",
            project_id=project_id,
            condition="GENERAL_AI",
            assignment_rule_version="balanced-by-purpose-v1",
            condition_version="general-v1",
            source_commit="m4-source",
            deployment_id="m4-deploy",
        )

    with pytest.raises(ConflictError, match="SESSION_EXISTS"):
        service.create_session(
            session_id="s-duplicate",
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

    with pytest.raises(ConflictError, match="INVALID_SESSION_TRANSITION"):
        service.transition_session(
            session_id="s-001",
            account_id="m4-owner",
            target_state="COMPLETED",
            expected_revision=1,
        )

    ready = service.transition_session(
        session_id="s-001",
        account_id="m4-owner",
        target_state="READY",
        expected_revision=1,
    )
    assert ready["state"] == "READY"
    assert ready["revision"] == 2

    with pytest.raises(ConflictError, match="SESSION_REVISION_CONFLICT"):
        service.transition_session(
            session_id="s-001",
            account_id="m4-owner",
            target_state="IN_PROGRESS",
            expected_revision=1,
        )

    with pytest.raises(ConflictError, match="EXPERIMENT_FROZEN"):
        service.update_experiment_metadata(
            experiment_id="m4-exp-001",
            account_id="m4-owner",
            expected_revision=2,
            condition_definitions={
                "STATIC_TEMPLATE": {"version": "changed"},
                "GENERAL_AI": {"version": "general-v1"},
                "INSIGHTFORGE_STATEFUL": {"version": "if-v1"},
            },
        )
