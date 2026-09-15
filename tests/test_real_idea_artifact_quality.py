import pytest

from app.services.real_idea_evaluation import RealIdeaEvaluationService
from app.services.real_idea_metrics import (
    ArtifactBinding,
    QualityBindingError,
    QualityEvaluationService,
    QualityRevisionError,
)


def _sample(db):
    evaluation = RealIdeaEvaluationService(db, durable_budget=6)
    evaluation.start_batch("batch-quality-test")
    return evaluation.start_sample("batch-quality-test", "an isolated reviewed idea")


def _payload(artifact_type):
    keys = {
        "SOLUTIONS": {
            "brief_critical_requirement_recall", "brief_overall_requirement_recall",
            "solution_set_recall", "solution_set_critical_recall",
            "selected_solution_recall", "selected_solution_critical_recall",
            "requirement_alignment_precision", "factual_precision", "unsupported_claim_rate",
            "decision_dimension_coverage", "pairwise_solution_differentiation",
        },
        "PRD": {
            "requirement_coverage_recall", "critical_requirement_coverage", "selected_solution_inheritance",
            "scope_consistency", "mandatory_section_coverage", "acceptance_criteria_testability",
            "completeness", "actionability", "unsupported_claim_rate", "critical_contradiction_rate",
        },
        "TECHDOC": {
            "prd_traceability_recall", "critical_technical_coverage", "nfr_coverage",
            "implementation_actionability", "feasibility_accuracy", "selected_solution_snapshot_inheritance",
            "unsupported_technical_claim_rate", "critical_contradiction_rate", "completeness",
        },
        "HANDOFF": {
            "exact_version_binding_accuracy", "artifact_completeness", "unresolved_item_coverage",
            "evidence_limitation_visibility", "decision_binding_accuracy", "package_integrity",
        },
    }[artifact_type]
    return {key: 1.0 for key in keys}


def _binding(sample, artifact_type="PRD", payload=None, **overrides):
    values = dict(
        batch_id=sample.batch_id,
        sample_id=sample.sample_id,
        project_id=sample.project_id,
        artifact_type=artifact_type,
        artifact_version_id=f"version-{artifact_type.lower()}",
        selected_solution_id=None,
        snapshot_id=None,
        upstream_version_ids=(),
        quality_layer="P0",
        evaluator_role="system",
        metric_payload=payload if payload is not None else _payload(artifact_type),
        input_manifest={"artifact": artifact_type, "version": "v1"},
        evidence_manifest={"metrics": "deterministic"},
        policy_version="real-idea-quality-v1",
    )
    values.update(overrides)
    return ArtifactBinding(**values)


def test_artifact_quality_p0_persists_safe_immutable_evidence(db):
    sample = _sample(db)
    result = QualityEvaluationService(db).evaluate_p0(_binding(sample))
    assert result.status == "PASS"
    assert result.quality_layer == "P0"
    assert result.quality_revision == 1
    assert db.fetch_one(
        "SELECT metric_payload FROM real_idea_quality_evaluations WHERE quality_evaluation_id = ?",
        (result.quality_evaluation_id,),
    )


def test_quality_binding_mismatch_is_rejected(db):
    sample = _sample(db)
    with pytest.raises(QualityBindingError):
        QualityEvaluationService(db).evaluate_p0(_binding(sample, project_id="wrong-project"))


def test_quality_missing_required_metrics_is_rejected(db):
    sample = _sample(db)
    with pytest.raises(QualityBindingError, match="required metric"):
        QualityEvaluationService(db).evaluate_p0(_binding(sample, payload={"completeness": 1.0}))


def test_quality_p0_violation_cannot_pass(db):
    sample = _sample(db)
    result = QualityEvaluationService(db).evaluate_p0(
        _binding(sample, payload={**_payload("HANDOFF"), "p0_violations": ["wrong_version_binding"]}, artifact_type="HANDOFF")
    )
    assert result.status == "FAIL"


def test_quality_revision_is_append_only_and_supersedes_previous(db):
    sample = _sample(db)
    quality = QualityEvaluationService(db)
    original = quality.evaluate_p0(_binding(sample))
    revised = quality.revise(
        original.quality_evaluation_id,
        metric_payload=_payload("PRD") | {"completeness": 0.8},
        status="PARTIAL",
        correction_reason="review correction",
        evaluator_role="independent_reviewer",
    )
    assert revised.quality_revision == 2
    assert revised.supersedes_quality_evaluation_id == original.quality_evaluation_id
    assert db.fetch_one(
        "SELECT quality_revision FROM real_idea_quality_evaluations WHERE quality_evaluation_id = ?",
        (original.quality_evaluation_id,),
    )["quality_revision"] == 1
    with pytest.raises(QualityRevisionError):
        quality.revise(original.quality_evaluation_id, metric_payload=_payload("PRD"), status="PASS", correction_reason="again", evaluator_role="system")


@pytest.mark.parametrize("artifact_type", ["SOLUTIONS", "PRD", "TECHDOC", "HANDOFF"])
def test_each_artifact_quality_contract_has_required_metrics(db, artifact_type):
    sample = _sample(db)
    result = QualityEvaluationService(db).evaluate_p0(_binding(sample, artifact_type=artifact_type))
    assert result.status == "PASS"
