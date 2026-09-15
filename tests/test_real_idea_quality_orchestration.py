from dataclasses import replace

import pytest

from app.services.real_idea_metrics import QualityBindingError, QualityEvaluationService
from tests.test_real_idea_artifact_quality import _binding, _sample


def test_p1_is_append_only_and_p2_requires_human_authority(db):
    sample = _sample(db)
    service = QualityEvaluationService(db)
    p0 = service.evaluate_p0(_binding(sample))

    p1_id = service.enqueue_p1(p0.quality_evaluation_id)
    p1 = service.get(p1_id)
    assert p1.quality_layer == "P1"
    assert p1.supersedes_quality_evaluation_id == p0.quality_evaluation_id
    assert service.get(p0.quality_evaluation_id).quality_layer == "P0"

    with pytest.raises(QualityBindingError):
        service.record_p2_review(p1_id, {"evaluator_role": "llm_assist", "status": "PASS"})

    p2 = service.record_p2_review(
        p1_id,
        {"evaluator_role": "independent_reviewer", "status": "PASS", "review_id": "review-1"},
    )
    assert p2.quality_layer == "P2"
    assert p2.evaluator_role == "independent_reviewer"


def test_p0_failure_cannot_be_upgraded_by_report_or_revision(db):
    sample = _sample(db)
    service = QualityEvaluationService(db)
    binding = _binding(sample)
    binding = replace(binding, metric_payload={
        **binding.metric_payload, "p0_violations": ["wrong_version"]
    })
    failed = service.evaluate_p0(binding)
    assert failed.status == "FAIL"
    with pytest.raises(QualityBindingError):
        service.enqueue_p1(failed.quality_evaluation_id)
    with pytest.raises(QualityBindingError):
        service.revise(
            failed.quality_evaluation_id,
            metric_payload=binding.metric_payload,
            status="PASS",
            correction_reason="incorrect review",
            evaluator_role="independent_reviewer",
        )
