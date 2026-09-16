from __future__ import annotations

import pytest

from app.services.action_review import ActionReviewService
from app.services.action_submission import ActionSubmissionService
from app.services.if_guide_m3_quality import IFGuideM3QualityService
from app.services.real_idea_metrics import QualityBindingError, QualityEvaluationService
from tests.test_if_guide_m3_review import _review_payload, _submitted


def _reviewed(client, db):
    submission = _submitted(client, db)
    review_payload = _review_payload(
        submission,
        check_items=[
            {
                "check_id": "result-recorded",
                "outcome": "PASS",
                "critical": True,
                "evidence_refs": ["user-note-1"],
            }
        ],
    )
    review = ActionReviewService(db).review(actor="m3-owner", **review_payload)
    return submission, review


def test_m3_quality_reuses_immutable_ledger_and_recovers_p0_p1_metrics(client, db):
    submission, review = _reviewed(client, db)

    result = IFGuideM3QualityService(db).evaluate(
        actor="m3-owner",
        project_id=submission["project_id"],
        task_id=submission["task_id"],
        task_revision=submission["task_revision"],
        submission_id=submission["submission_id"],
        submission_revision=submission["revision"],
        review_id=review["review_id"],
        review_revision=review["revision"],
    )

    assert result["p0"]["status"] == "PASS"
    assert result["p1"]["status"] == "PASS"
    assert result["p1"]["metric_payload"]["evidence_sufficiency"] == 1.0
    assert result["p1"]["metric_payload"]["review_accuracy"] == 1.0
    assert result["p1"]["metric_payload"]["result_decision_traceability"] == 1.0
    assert result["p1"]["metric_payload"]["unsupported_conclusion_rate"] == 0.0
    assert result["p1"]["metric_payload"]["recovery_specificity"] == 1.0
    assert result["p2_status"] == "NOT_REVIEWED"

    rows = db.fetch_all(
        "SELECT artifact_type, evaluation_scope, quality_layer, quality_revision "
        "FROM real_idea_quality_evaluations WHERE project_id = ? "
        "ORDER BY quality_revision",
        (submission["project_id"],),
    )
    assert [(row["artifact_type"], row["evaluation_scope"], row["quality_layer"], row["quality_revision"])
            for row in rows] == [("M3_ACTION", "IF_GUIDE_M3", "P0", 1),
                                 ("M3_ACTION", "IF_GUIDE_M3", "P1", 2)]


def test_m3_quality_requires_exact_review_binding_and_keeps_p2_human_boundary(client, db):
    submission, review = _reviewed(client, db)
    service = IFGuideM3QualityService(db)

    with pytest.raises(ValueError, match="M3_REVIEW_BINDING_REQUIRED"):
        service.evaluate(
            actor="m3-owner",
            project_id=submission["project_id"],
            task_id=submission["task_id"],
            task_revision=submission["task_revision"],
            submission_id=submission["submission_id"],
            submission_revision=submission["revision"],
            review_id="review-wrong",
            review_revision=review["revision"],
        )

    p0 = QualityEvaluationService(db).get_for_artifact(
        evaluation_scope="IF_GUIDE_M3",
        project_id=submission["project_id"],
        artifact_type="M3_ACTION",
        artifact_id=submission["task_id"],
        artifact_revision=submission["task_revision"],
    )
    assert p0 is None
