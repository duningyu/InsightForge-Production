import pytest

from app.services.real_idea_metrics import QualityBindingError, QualityEvaluationService
from tests.test_real_idea_artifact_quality import _binding, _sample


def test_cross_artifact_quality_rejects_wrong_project_binding(db):
    sample = _sample(db)
    with pytest.raises(QualityBindingError):
        QualityEvaluationService(db).evaluate_p0(_binding(sample, project_id="other-project"))


def test_quality_evidence_rejects_document_body_or_raw_provider_payload(db):
    sample = _sample(db)
    payload = _binding(sample, metric_payload={"body": "must not persist"})
    with pytest.raises(QualityBindingError, match="unsafe quality evidence"):
        QualityEvaluationService(db).evaluate_p0(payload)

