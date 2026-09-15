from app.services.real_idea_metrics import QualityEvaluationService
from tests.test_real_idea_artifact_quality import _binding, _sample


def test_batch_report_is_per_sample_and_safe(db):
    sample = _sample(db)
    service = QualityEvaluationService(db)
    evaluation = service.evaluate_p0(_binding(sample))
    report = service.build_batch_report(sample.batch_id)

    assert report["sample_count"] == 1
    assert report["samples"][0]["sample_id"] == sample.sample_id
    assert report["samples"][0]["quality_evaluation_count"] == 1
    assert report["n3_statistical_superiority_claim_allowed"] is False
    assert "metric_payload" not in report["samples"][0]
    assert "body" not in str(report).lower()

    monitoring = service.monitoring_summary(sample.batch_id)
    assert monitoring["quality_evaluation_count"] == 1
    assert monitoring["statuses"] == {"PASS": 1}
    assert monitoring["latest_quality_evaluation_id"] == evaluation.quality_evaluation_id
