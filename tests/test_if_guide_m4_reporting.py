from __future__ import annotations

import json

import pytest

from app.services.if_guide_m4 import M4EvaluationService
from app.services.if_guide_m4_reporting import M4ReportingService
from tests.test_if_guide_m4_experiment import (
    _create_experiment,
    _create_project_with_owner,
)


def _create_session(db, *, session_id: str = "m4-report-session") -> None:
    service = M4EvaluationService(db)
    _create_experiment(service)
    service.freeze_experiment(
        experiment_id="m4-exp-001", account_id="m4-owner", expected_revision=1
    )
    service.create_participant(
        experiment_id="m4-exp-001",
        participant_id="m4-participant-001",
        account_id="m4-owner",
        purpose="LEARNING",
        prior_ai_familiarity="low",
        prior_product_experience="some",
        task_category="prototype",
    )
    project_id = _create_project_with_owner(db)
    service.create_session(
        session_id=session_id,
        experiment_id="m4-exp-001",
        participant_id="m4-participant-001",
        account_id="m4-owner",
        project_id=project_id,
        condition="STATIC_TEMPLATE",
        assignment_rule_version="balanced-by-purpose-v1",
        condition_version="static-v1",
        source_commit="m4-source",
        deployment_id="m4-deploy",
    )


def test_report_is_per_session_first_and_descriptive_only(db):
    _create_session(db)

    report = M4ReportingService(db).build_report(
        experiment_id="m4-exp-001", account_id="m4-owner"
    )

    assert report["sessions"]
    assert report["sessions"][0]["session_id"] == "m4-report-session"
    assert report["sessions"][0]["provider_calls"] == 0
    assert report["sessions"][0]["provider_cost"] == 0
    assert report["aggregates"]["by_condition"]["STATIC_TEMPLATE"]["session_count"] == 1
    assert report["claim_boundary"]["statistical_significance"] == "NOT_CLAIMED"
    assert "winner" not in report

    encoded = M4ReportingService(db).export_json(
        experiment_id="m4-exp-001", account_id="m4-owner"
    )
    assert json.loads(encoded) == report


def test_report_excludes_split_sessions_from_comparable_aggregates(db):
    _create_session(db)
    service = M4EvaluationService(db)
    split = service.record_version_observation(
        experiment_id="m4-exp-001",
        account_id="m4-owner",
        observed_metadata={"source_commit": "changed-source"},
    )
    assert split["version_split"] is True

    report = M4ReportingService(db).build_report(
        experiment_id="m4-exp-001", account_id="m4-owner"
    )
    assert report["sessions"][0]["version_split"] is True
    assert report["aggregates"]["comparable_session_count"] == 0
    assert report["version_splits"] == ["m4-report-session"]


def test_report_is_owner_scoped(db):
    _create_session(db)

    with pytest.raises(PermissionError, match="M4_ACCOUNT_ACCESS_DENIED"):
        M4ReportingService(db).build_report(
            experiment_id="m4-exp-001", account_id="other-account"
        )


def test_report_rejects_unsafe_fields(db):
    _create_session(db)

    with pytest.raises(ValueError, match="UNSAFE_REPORT_FIELD"):
        M4ReportingService.reject_unsafe_fields(
            {"session_id": "safe", "raw_idea": "must not be exported"}
        )
