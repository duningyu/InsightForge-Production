from app.services.real_idea_metrics import QualityEvaluationService
from tests.test_real_idea_artifact_quality import _binding, _sample


def test_techdoc_quality_requires_traceability_and_nfr_contract(db):
    sample = _sample(db)
    result = QualityEvaluationService(db).evaluate_p0(_binding(sample, artifact_type="TECHDOC"))
    assert result.artifact_type == "TECHDOC"
    assert result.metric_payload["prd_traceability_recall"] == 1.0
    assert result.metric_payload["nfr_coverage"] == 1.0

