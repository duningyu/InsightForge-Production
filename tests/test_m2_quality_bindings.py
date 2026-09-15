from dataclasses import replace

import pytest

from app.services.build_slice import BuildSliceService
from app.services.real_idea_metrics import (
    ArtifactBinding,
    QualityBindingError,
    QualityEvaluationService,
    QualityRevisionError,
)
from test_build_slice_confirmation import _COMPLETE, _create_slice, _ready_project


def _confirmed_slice(db, client):
    project_id, actor = _ready_project(client)
    service = BuildSliceService(db)
    record = service.create_or_get(
        project_id,
        actor=actor,
        expected_snapshot_id=None,
        expected_intent_revision=1,
    )
    service.update(
        project_id,
        record["slice_id"],
        actor=actor,
        expected_revision=1,
        updates=_COMPLETE,
    )
    confirmed = service.confirm(
        project_id,
        record["slice_id"],
        actor=actor,
        expected_revision=2,
    )
    return project_id, actor, confirmed


def _payload():
    return {
        "scope_recall": 1.0,
        "scope_precision": 1.0,
        "acceptance_coverage": 1.0,
        "acceptance_testability": 1.0,
        "constraint_preservation": 1.0,
        "dependency_clarity": 1.0,
        "unsupported_claim_rate": 0.0,
    }


def _binding(project_id, actor, slice_id, revision=2, **overrides):
    values = dict(
        batch_id=None,
        sample_id=None,
        project_id=project_id,
        artifact_type="BUILD_SLICE",
        artifact_version_id=f"{slice_id}:r{revision}",
        selected_solution_id=None,
        snapshot_id=None,
        upstream_version_ids=(),
        quality_layer="P0",
        evaluator_role="system",
        metric_payload=_payload(),
        input_manifest={"artifact_type": "BUILD_SLICE", "artifact_id": slice_id, "artifact_revision": revision},
        evidence_manifest={"evidence_ids": [f"slice:{slice_id}:r{revision}"], "rubric_version": "if-guide-m2-v1"},
        policy_version="if-guide-m2-v1",
        owner_actor=actor,
        artifact_id=slice_id,
        artifact_revision=revision,
        evaluation_scope="IF_GUIDE_M2",
        intent_revision=1,
        slice_id=slice_id,
        slice_revision=revision,
    )
    values.update(overrides)
    return ArtifactBinding(**values)


def test_m2_quality_binding_and_exact_revision_readback(db, client):
    project_id, actor, slice_record = _confirmed_slice(db, client)
    service = QualityEvaluationService(db)
    binding = _binding(project_id, actor, slice_record["slice_id"])

    p0 = service.evaluate_p0(binding)
    assert p0.status == "PASS"
    assert p0.evaluation_scope == "IF_GUIDE_M2"
    assert p0.artifact_id == slice_record["slice_id"]
    assert p0.artifact_revision == 2

    p1 = service.get(service.enqueue_p1(p0.quality_evaluation_id))
    assert p1.quality_layer == "P1"
    assert p1.quality_revision == 2
    assert p1.artifact_id == p0.artifact_id
    assert service.get_for_artifact(
        evaluation_scope="IF_GUIDE_M2",
        project_id=project_id,
        artifact_type="BUILD_SLICE",
        artifact_id=slice_record["slice_id"],
        artifact_revision=2,
    ).quality_evaluation_id == p1.quality_evaluation_id


def test_m2_quality_binding_rejects_missing_or_wrong_identity(db, client):
    project_id, actor, slice_record = _confirmed_slice(db, client)
    service = QualityEvaluationService(db)
    binding = _binding(project_id, actor, slice_record["slice_id"])

    invalid = [
        replace(binding, owner_actor=None),
        replace(binding, artifact_id=None),
        replace(binding, artifact_revision=3),
        replace(binding, evaluation_scope="REAL_IDEA_BATCH"),
        replace(binding, batch_id="unexpected-batch"),
        replace(binding, project_id="other-project"),
    ]
    for candidate in invalid:
        with pytest.raises(QualityBindingError):
            service.evaluate_p0(candidate)


def test_m2_quality_revision_is_append_only_and_sensitive_evidence_is_rejected(db, client):
    project_id, actor, slice_record = _confirmed_slice(db, client)
    service = QualityEvaluationService(db)
    p0 = service.evaluate_p0(_binding(project_id, actor, slice_record["slice_id"]))

    revised = service.revise(
        p0.quality_evaluation_id,
        metric_payload=_payload(),
        status="PARTIAL",
        correction_reason="reviewed rubric correction",
        evaluator_role="independent_reviewer",
    )
    assert revised.quality_revision == 2
    assert revised.supersedes_quality_evaluation_id == p0.quality_evaluation_id
    assert revised.artifact_id == p0.artifact_id
    assert revised.artifact_revision == p0.artifact_revision

    with pytest.raises(QualityBindingError):
        service.evaluate_p0(
            _binding(
                project_id,
                actor,
                slice_record["slice_id"],
                evidence_manifest={"content": "private artifact body"},
            )
        )
    with pytest.raises(QualityRevisionError):
        service.revise(
            p0.quality_evaluation_id,
            metric_payload=_payload(),
            status="PARTIAL",
            correction_reason="duplicate revision",
            evaluator_role="independent_reviewer",
        )


def test_m2_quality_rejects_unknown_artifact_revision_without_mutation(db, client):
    project_id, actor, slice_record = _confirmed_slice(db, client)
    service = QualityEvaluationService(db)
    with pytest.raises(QualityBindingError):
        service.evaluate_p0(
            _binding(
                project_id,
                actor,
                slice_record["slice_id"],
                artifact_revision=3,
                slice_revision=3,
                artifact_version_id=f"{slice_record['slice_id']}:r3",
            )
        )
    assert db.fetch_one("SELECT COUNT(*) AS count FROM real_idea_quality_evaluations")["count"] == 0
