from __future__ import annotations

from collections import Counter

import pytest

from app.errors import ConflictError
from app.services.if_guide_m4 import M4EvaluationService
from app.services.if_guide_m4_assignment import M4AssignmentService
from app.services.if_guide_m4_conditions import default_condition_definitions


def _create_experiment(service: M4EvaluationService) -> None:
    service.create_experiment(
        experiment_id="m4-assignment-exp",
        account_id="m4-assignment-owner",
        spec_version="m4-spec-v1",
        source_commit="m4-source",
        deployment_id="m4-deploy",
        condition_definitions=default_condition_definitions(
            source_commit="m4-source", deployment_id="m4-deploy"
        ),
        assignment_rule="balanced-by-purpose-v1",
        metric_versions={"primary": "m4-primary-v1"},
        rubric_versions={"quality": "r1.1-v1"},
        threshold_policy={"mode": "BASELINE_ONLY"},
        operator_assistance_policy={"allowed": False},
    )
    service.freeze_experiment(
        experiment_id="m4-assignment-exp",
        account_id="m4-assignment-owner",
        expected_revision=1,
    )


def _create_project(db, project_id: str, owner: str) -> None:
    with db.connect() as connection:
        connection.execute(
            """
            INSERT INTO projects (id, title, summary, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (project_id, "Assignment fixture", "fixture", "2026-09-16T00:00:00Z", "2026-09-16T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO project_intents (
                intent_id, project_id, owner_actor, purpose, raw_idea,
                revision, confirmed_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'LEARNING', ?, 1, ?, ?, ?)
            """,
            (
                f"intent-{project_id}",
                project_id,
                owner,
                "fixture",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
            ),
        )


def _create_participant(service: M4EvaluationService, participant_id: str, purpose: str) -> None:
    service.create_participant(
        experiment_id="m4-assignment-exp",
        participant_id=participant_id,
        account_id="m4-assignment-owner",
        purpose=purpose,
        prior_ai_familiarity="low",
        prior_product_experience="some",
        task_category="prototype",
    )


def test_balanced_assignment_is_frozen_auditable_and_not_reassignable(db):
    experiment_service = M4EvaluationService(db)
    _create_experiment(experiment_service)
    _create_project(db, "m4-assignment-project", "m4-assignment-owner")

    participant_ids = [f"p-learning-{index}" for index in range(6)]
    for participant_id in participant_ids:
        _create_participant(experiment_service, participant_id, "LEARNING")
    _create_participant(experiment_service, "p-personal", "PERSONAL_USE")
    _create_participant(experiment_service, "p-others", "FOR_OTHERS")

    assignment_service = M4AssignmentService(db)
    assigned = [
        assignment_service.assign_session(
            session_id=f"session-{participant_id}",
            experiment_id="m4-assignment-exp",
            participant_id=participant_id,
            account_id="m4-assignment-owner",
            project_id="m4-assignment-project",
        )
        for participant_id in participant_ids
    ]
    assert {item["condition"] for item in assigned} == {
        "STATIC_TEMPLATE",
        "GENERAL_AI",
        "INSIGHTFORGE_STATEFUL",
    }
    counts = Counter(item["condition"] for item in assigned)
    assert max(counts.values()) - min(counts.values()) <= 1
    assert all(item["assignment_rule_version"] == "balanced-by-purpose-v1" for item in assigned)
    assert all(item["state"] == "ASSIGNED" for item in assigned)

    personal = assignment_service.assign_session(
        session_id="session-personal",
        experiment_id="m4-assignment-exp",
        participant_id="p-personal",
        account_id="m4-assignment-owner",
        project_id="m4-assignment-project",
    )
    others = assignment_service.assign_session(
        session_id="session-others",
        experiment_id="m4-assignment-exp",
        participant_id="p-others",
        account_id="m4-assignment-owner",
        project_id="m4-assignment-project",
    )
    assert personal["purpose"] == "PERSONAL_USE"
    assert others["purpose"] == "FOR_OTHERS"
    assert personal["deviation_reason"] is None

    with pytest.raises(ConflictError, match="SESSION_ALREADY_ASSIGNED"):
        assignment_service.assign_session(
            session_id="session-reassignment",
            experiment_id="m4-assignment-exp",
            participant_id=participant_ids[0],
            account_id="m4-assignment-owner",
            project_id="m4-assignment-project",
        )

    withdrawn = assignment_service.withdraw_session(
        session_id="session-personal",
        account_id="m4-assignment-owner",
        expected_revision=1,
        reason="participant withdrew",
    )
    assert withdrawn["state"] == "WITHDRAWN"
    with db.connect() as connection:
        participant = connection.execute(
            "SELECT state, withdrawal_reason FROM m4_participants WHERE participant_id = ?",
            ("p-personal",),
        ).fetchone()
    assert participant["state"] == "WITHDRAWN"
    assert participant["withdrawal_reason"] == "participant withdrew"
