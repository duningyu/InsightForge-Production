from __future__ import annotations

import pytest

from app.services.if_guide_m4_quality import M4QualityService
from test_if_guide_m4_gold_set import _create_m4_session
from test_if_guide_m4_metrics import _metrics


@pytest.mark.parametrize("violation", [
    "unsupported_verified_claim", "cross_project_leakage", "wrong_version_binding",
])
def test_m4_integrity_violations_are_p0_failures(db, violation):
    account_id, _, project_id = _create_m4_session(db)
    metrics = _metrics()
    metrics["p0_violations"] = [violation]
    result = M4QualityService(db).evaluate_session(
        session_id="gold-session", account_id=account_id, project_id=project_id,
        expected_session_revision=1, metrics=metrics,
    )
    assert result["p0_status"] == "FAIL"
    assert result["p1_status"] == "NOT_RUN"


def test_llm_assist_cannot_finalize_gold_set_and_p2_is_not_claimed(db):
    account_id, _, project_id = _create_m4_session(db)
    metrics = _metrics()
    metrics["gold_set"] = {"participant_confirmed": True, "confirmed_by": "LLM_ASSIST"}
    result = M4QualityService(db).evaluate_session(
        session_id="gold-session", account_id=account_id, project_id=project_id,
        expected_session_revision=1, metrics=metrics,
    )
    assert result["p0_status"] == "FAIL"
    assert "gold_set_not_human_confirmed" in result["p0_violations"]
    assert result["p2_status"] == "NOT_REVIEWED"


def test_quality_evaluation_is_owned_and_revision_bound(db):
    account_id, _, project_id = _create_m4_session(db)
    with pytest.raises(PermissionError, match="M4_ACCOUNT_ACCESS_DENIED"):
        M4QualityService(db).evaluate_session(
            session_id="gold-session", account_id="other-account", project_id=project_id,
            expected_session_revision=1, metrics=_metrics(),
        )
