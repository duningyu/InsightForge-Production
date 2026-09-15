from __future__ import annotations

import pytest

from app.services.real_idea_metrics import QualityBindingError, QualityEvaluationService
from test_m2_quality_bindings import _binding, _confirmed_slice


def _p0(db, client):
    project_id, actor, slice_record = _confirmed_slice(db, client)
    service = QualityEvaluationService(db)
    evaluation = service.evaluate_p0(_binding(project_id, actor, slice_record["slice_id"]))
    return service, evaluation, project_id, actor, slice_record


def _review(**overrides):
    review = {
        "evaluator_role": "independent_reviewer",
        "review_id": "m2-review-001",
        "rubric_version": "if-guide-m2-quality-v1",
        "status": "PASS",
        "evidence_ids": ["slice:evidence-001", "acceptance:evidence-001"],
        "finding_codes": [],
    }
    review.update(overrides)
    return review


def test_p2_review_requires_authoritative_role_rubric_and_safe_evidence(db, client):
    service, p0, project_id, actor, slice_record = _p0(db, client)

    with pytest.raises(QualityBindingError, match="authoritative human reviewer"):
        service.record_p2_review(
            p0.quality_evaluation_id,
            _review(evaluator_role="llm_assist"),
        )
    with pytest.raises(QualityBindingError, match="rubric"):
        service.record_p2_review(
            p0.quality_evaluation_id,
            _review(rubric_version=""),
        )
    with pytest.raises(QualityBindingError, match="evidence"):
        service.record_p2_review(
            p0.quality_evaluation_id,
            _review(evidence_ids=[]),
        )
    with pytest.raises(QualityBindingError, match="unsafe"):
        service.record_p2_review(
            p0.quality_evaluation_id,
            _review(evidence={"content": "private artifact body"}),
        )

    assert db.fetch_one(
        "SELECT COUNT(*) AS count FROM real_idea_quality_evaluations "
        "WHERE project_id=? AND artifact_type='BUILD_SLICE'",
        (project_id,),
    )["count"] == 1


def test_p2_review_binds_exact_artifact_revision_and_records_safe_evidence(db, client):
    service, p0, project_id, actor, slice_record = _p0(db, client)

    review = service.record_p2_review(p0.quality_evaluation_id, _review())

    assert review.quality_layer == "P2"
    assert review.evaluator_role == "independent_reviewer"
    assert review.artifact_id == slice_record["slice_id"]
    assert review.artifact_revision == 2
    assert review.quality_revision == 2
    assert review.metric_payload["p2_review"]["rubric_version"] == "if-guide-m2-quality-v1"
    assert review.metric_payload["p2_review"]["evidence_ids"] == [
        "slice:evidence-001", "acceptance:evidence-001"
    ]


def test_idea_provider_is_allowed_but_llm_assist_is_not_authoritative_p2(db, client):
    service, p0, _, _, _ = _p0(db, client)

    review = service.record_p2_review(
        p0.quality_evaluation_id,
        _review(evaluator_role="idea_provider", review_id="provider-review-001"),
    )
    assert review.evaluator_role == "idea_provider"


def test_p2_corrections_are_append_only_and_remain_human_bound(db, client):
    service, p0, _, _, _ = _p0(db, client)
    p2 = service.record_p2_review(p0.quality_evaluation_id, _review())

    with pytest.raises(QualityBindingError, match="human"):
        service.revise(
            p2.quality_evaluation_id,
            metric_payload=p2.metric_payload,
            status="PASS",
            correction_reason="LLM candidate correction",
            evaluator_role="llm_assist",
        )

    corrected = service.revise(
        p2.quality_evaluation_id,
        metric_payload=p2.metric_payload,
        status="PARTIAL",
        correction_reason="independent reviewer corrected a rubric finding",
        evaluator_role="independent_reviewer",
    )
    assert corrected.quality_revision == 3
    assert corrected.supersedes_quality_evaluation_id == p2.quality_evaluation_id
    assert service.get(p2.quality_evaluation_id).status == "PASS"
