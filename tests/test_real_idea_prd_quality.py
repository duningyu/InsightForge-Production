from app.services.real_idea_metrics import QualityEvaluationService
from tests.test_real_idea_artifact_quality import _binding, _sample


def test_prd_quality_requires_coverage_and_actionability_contract(db):
    sample = _sample(db)
    result = QualityEvaluationService(db).evaluate_p0(_binding(sample, artifact_type="PRD"))
    assert result.artifact_type == "PRD"
    assert result.metric_payload["requirement_coverage_recall"] == 1.0
    assert result.metric_payload["actionability"] == 1.0

