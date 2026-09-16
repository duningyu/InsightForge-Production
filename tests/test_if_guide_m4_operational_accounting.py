from __future__ import annotations

from app.services.if_guide_m4 import M4EvaluationService
from app.services.if_guide_m4_conditions import default_condition_definitions


def _create_project(db, project_id: str) -> None:
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO projects (id, title, summary, status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
            (project_id, "M4 accounting fixture", "fixture", "2026-09-16T00:00:00Z", "2026-09-16T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO project_intents (
                intent_id, project_id, owner_actor, purpose, raw_idea,
                revision, confirmed_at, created_at, updated_at
            ) VALUES (?, ?, ?, 'LEARNING', ?, 1, ?, ?, ?)
            """,
            (
                f"intent-{project_id}", project_id, "accounting-owner", "fixture",
                "2026-09-16T00:00:00Z", "2026-09-16T00:00:00Z", "2026-09-16T00:00:00Z",
            ),
        )


def test_no_provider_session_accounting_is_explicit_zero(db):
    service = M4EvaluationService(db)
    service.create_experiment(
        experiment_id="m4-accounting-exp",
        account_id="accounting-owner",
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
        experiment_id="m4-accounting-exp", account_id="accounting-owner", expected_revision=1
    )
    service.create_participant(
        experiment_id="m4-accounting-exp", participant_id="accounting-p1", account_id="accounting-owner",
        purpose="LEARNING", prior_ai_familiarity="low", prior_product_experience="some", task_category="prototype",
    )
    _create_project(db, "m4-accounting-project")
    service.create_session(
        session_id="m4-accounting-session", experiment_id="m4-accounting-exp", participant_id="accounting-p1",
        account_id="accounting-owner", project_id="m4-accounting-project", condition="STATIC_TEMPLATE",
        assignment_rule_version="balanced-by-purpose-v1", condition_version="static-v1",
        source_commit="m4-source", deployment_id="m4-deploy",
    )

    updated = service.record_operational_accounting(
        session_id="m4-accounting-session", account_id="accounting-owner", expected_revision=1,
        edit_count=2, support_minutes=1.5,
    )
    assert updated["provider_calls"] == 0
    assert updated["provider_cost"] == 0
    assert updated["retry_count"] == 0
    assert updated["timeout_count"] == 0
    assert updated["edit_count"] == 2
    assert updated["support_minutes"] == 1.5

