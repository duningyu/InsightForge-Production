from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.if_guide_m4 import M4EvaluationService
from app.services.if_guide_m4_conditions import default_condition_definitions
from app.services.if_guide_m4_gold_set import M4GoldSetService


def _create_m4_session(db) -> tuple[str, str, str]:
    experiment_service = M4EvaluationService(db)
    experiment_service.create_experiment(
        experiment_id="m4-gold-exp",
        account_id="gold-owner",
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
    experiment_service.freeze_experiment(
        experiment_id="m4-gold-exp", account_id="gold-owner", expected_revision=1
    )
    experiment_service.create_participant(
        experiment_id="m4-gold-exp",
        participant_id="gold-participant",
        account_id="gold-owner",
        purpose="LEARNING",
        prior_ai_familiarity="low",
        prior_product_experience="some",
        task_category="prototype",
    )
    with db.connect() as connection:
        connection.execute(
            """
            INSERT INTO projects (id, title, summary, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (
                "gold-project",
                "Gold fixture",
                "fixture",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO project_intents (
                intent_id, project_id, owner_actor, purpose, raw_idea, revision,
                confirmed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                "gold-intent",
                "gold-project",
                "gold-owner",
                "LEARNING",
                "fixture idea",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
                "2026-09-16T00:00:00Z",
            ),
        )
    experiment_service.create_session(
        session_id="gold-session",
        experiment_id="m4-gold-exp",
        participant_id="gold-participant",
        account_id="gold-owner",
        project_id="gold-project",
        condition="STATIC_TEMPLATE",
        assignment_rule_version="balanced-by-purpose-v1",
        condition_version="static-v1",
        source_commit="m4-source",
        deployment_id="m4-deploy",
    )
    return "gold-owner", "gold-participant", "gold-project"


def _requirements() -> list[dict[str, str]]:
    return [
        {
            "requirement_id": "req-1",
            "canonical_text": "The first action must be checkable.",
            "importance": "CRITICAL",
            "source": "USER_CONFIRMED_BRIEF",
        },
        {
            "requirement_id": "req-2",
            "canonical_text": "The flow should preserve the user's constraints.",
            "importance": "SECONDARY",
            "source": "USER_EDIT",
        },
    ]


def test_gold_set_requires_participant_confirmation(db):
    account_id, participant_id, project_id = _create_m4_session(db)
    service = M4GoldSetService(db)

    with pytest.raises(ConflictError, match="GOLD_SET_PARTICIPANT_CONFIRMATION_REQUIRED"):
        service.finalize_gold_set(
            session_id="gold-session",
            account_id=account_id,
            participant_id=participant_id,
            project_id=project_id,
            purpose="learn a useful first action",
            constraints=["keep the scope small"],
            explicit_non_goals=["no automatic deployment"],
            requirements=_requirements(),
            participant_confirmed=False,
            expected_session_revision=1,
        )

    finalized = service.finalize_gold_set(
        session_id="gold-session",
        account_id=account_id,
        participant_id=participant_id,
        project_id=project_id,
        purpose="learn a useful first action",
        constraints=["keep the scope small"],
        explicit_non_goals=["no automatic deployment"],
        requirements=_requirements(),
        participant_confirmed=True,
        expected_session_revision=1,
    )
    assert finalized["finalized"] is True
    assert finalized["confirmed_by"] == "idea_provider"
    assert len(finalized["requirements"]) == 2


def test_gold_set_revisions_are_append_only_and_exactly_bound(db):
    account_id, participant_id, project_id = _create_m4_session(db)
    service = M4GoldSetService(db)
    first = service.finalize_gold_set(
        session_id="gold-session",
        account_id=account_id,
        participant_id=participant_id,
        project_id=project_id,
        purpose="initial purpose",
        constraints=[],
        explicit_non_goals=[],
        requirements=_requirements(),
        participant_confirmed=True,
        expected_session_revision=1,
    )
    second = service.finalize_gold_set(
        session_id="gold-session",
        account_id=account_id,
        participant_id=participant_id,
        project_id=project_id,
        purpose="revised purpose",
        constraints=["one constraint"],
        explicit_non_goals=["one non-goal"],
        requirements=[{**_requirements()[0], "canonical_text": "Revised critical action."}],
        participant_confirmed=True,
        expected_session_revision=1,
    )
    assert first["revision"] == 1
    assert second["revision"] == 2
    assert service.get_gold_set("gold-session", account_id)["revision"] == 2
    assert db.fetch_one("SELECT COUNT(*) AS n FROM m4_requirement_gold_items", ())["n"] == 3

    with pytest.raises(PermissionError, match="M4_ACCOUNT_ACCESS_DENIED"):
        service.get_gold_set("gold-session", "other-account")

