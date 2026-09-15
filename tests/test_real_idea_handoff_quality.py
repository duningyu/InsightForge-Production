from app.services.real_idea_metrics import QualityEvaluationService
from tests.test_real_idea_artifact_quality import _binding, _sample


def test_handoff_quality_requires_integrity_and_evidence_limitation_contract(db):
    sample = _sample(db)
    result = QualityEvaluationService(db).evaluate_p0(_binding(sample, artifact_type="HANDOFF"))
    assert result.artifact_type == "HANDOFF"
    assert result.metric_payload["package_integrity"] == 1.0
    assert result.metric_payload["evidence_limitation_visibility"] == 1.0

