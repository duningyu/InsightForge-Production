from __future__ import annotations

from test_if_guide_m4_gold_set import _create_m4_session
from app.services.if_guide_m4_quality import M4QualityService


def _metrics() -> dict:
    return {
        "first_valid_action": {"numerator": 1, "denominator": 1},
        "first_usable_flow_completion": {"numerator": 0, "denominator": 1},
        "independent_acceptance": {"numerator": 1, "denominator": 1},
        "evidence_backed_decision": {"numerator": 0, "denominator": 1},
        "recovery": {"numerator": 0, "denominator": 0},
        "secondary": {
            "critical_requirement_recall": {"numerator": 2, "denominator": 2},
            "overall_requirement_recall": {"numerator": 3, "denominator": 4},
            "requirement_alignment_precision": {"numerator": 3, "denominator": 3},
            "checkability_coverage": {"numerator": 1, "denominator": 1},
            "acceptance_coverage": {"numerator": 2, "denominator": 2},
            "acceptance_testability": {"numerator": 2, "denominator": 2},
            "unsupported_claim_rate": {"numerator": 0, "denominator": 3},
            "actionability": {"numerator": 1, "denominator": 1},
            "result_decision_traceability": {"numerator": 0, "denominator": 1},
        },
        "p0_violations": [],
        "p1_gaps": [],
        "evidence": {"review_ref": "review-m4-1"},
        "gold_set": {"participant_confirmed": True, "confirmed_by": "idea_provider"},
    }


def test_m4_metrics_use_conditional_denominators_and_existing_quality_ledger(db):
    account_id, _, project_id = _create_m4_session(db)
    result = M4QualityService(db).evaluate_session(
        session_id="gold-session", account_id=account_id, project_id=project_id,
        expected_session_revision=1, metrics=_metrics(),
    )

    assert result["p0_status"] == "PASS"
    assert result["p1_status"] == "PASS"
    assert result["p2_status"] == "NOT_REVIEWED"
    assert result["primary_metrics"]["recovery"]["status"] == "NOT_APPLICABLE"
    assert result["primary_metrics"]["first_valid_action"]["value"] == 1.0
    row = db.fetch_one(
        "SELECT evaluation_scope, artifact_type, quality_layer FROM real_idea_quality_evaluations "
        "WHERE quality_evaluation_id = ?", (result["quality_evaluation_id"],)
    )
    assert tuple(row) == ("IF_GUIDE_M4", "M4_SESSION", "P0")
    assert result["provider_calls"] == 0
    assert result["search_calls"] == 0


def test_m4_metrics_reject_invalid_ratio_and_preserve_missing_as_not_applicable(db):
    account_id, _, project_id = _create_m4_session(db)
    metrics = _metrics()
    metrics["first_valid_action"] = {"numerator": 2, "denominator": 1}
    result = M4QualityService(db).evaluate_session(
        session_id="gold-session", account_id=account_id, project_id=project_id,
        expected_session_revision=1, metrics=metrics,
    )
    assert result["p0_status"] == "FAIL"
    assert "invalid_metric_ratio" in result["p0_violations"]

