import pytest

from app.services.real_idea_metrics import QualityBindingError, QualityEvaluationService, QualityRevisionError
from tests.test_real_idea_artifact_quality import _binding, _payload, _sample


def test_quality_rejects_cross_project_and_unsafe_body_evidence(db):
    sample = _sample(db)
    service = QualityEvaluationService(db)
    with pytest.raises(QualityBindingError):
        service.evaluate_p0(_binding(sample, project_id="other-project"))
    with pytest.raises(QualityBindingError):
        service.evaluate_p0(_binding(sample, evidence_manifest={"body": "private document"}))


def test_quality_hard_fail_covers_placeholder_and_wrong_version_invariants(db):
    sample = _sample(db)
    service = QualityEvaluationService(db)
    payload = {**_payload("HANDOFF"), "p0_violations": ["placeholder_content", "wrong_version_binding"]}
    result = service.evaluate_p0(_binding(sample, artifact_type="HANDOFF", payload=payload))
    assert result.status == "FAIL"
    with pytest.raises(QualityBindingError):
        service.enqueue_p1(result.quality_evaluation_id)


def test_quality_rejects_llm_as_sole_p2_authority(db):
    sample = _sample(db)
    service = QualityEvaluationService(db)
    p0 = service.evaluate_p0(_binding(sample))
    p1 = service.enqueue_p1(p0.quality_evaluation_id)
    with pytest.raises(QualityBindingError):
        service.record_p2_review(p1, {"evaluator_role": "llm_assist", "status": "PASS"})


def test_quality_duplicate_revision_is_rejected_without_mutating_history(db):
    sample = _sample(db)
    service = QualityEvaluationService(db)
    p0 = service.evaluate_p0(_binding(sample))
    p1 = service.enqueue_p1(p0.quality_evaluation_id)
    before = service.get(p1)
    with pytest.raises(QualityRevisionError):
        service.revise(
            p0.quality_evaluation_id,
            metric_payload=_payload("PRD"),
            status="PASS",
            correction_reason="duplicate attempt",
            evaluator_role="independent_reviewer",
        )
    assert service.get(p1) == before
