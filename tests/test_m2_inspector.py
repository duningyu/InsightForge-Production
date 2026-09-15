from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.db import Database
from app.services.if_guide_m2_inspector import IFGuideM2Inspector
from app.services.real_idea_metrics import ArtifactBinding, QualityEvaluationService

from test_m2_routes import build_slice_payload, create_m1_ready_project


def _create_confirmed_m2_artifacts(client, db: Database, actor: str = "m2-owner"):
    project_id = create_m1_ready_project(client, actor=actor)
    headers = {"X-Actor": actor}

    created = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers=headers,
        json=build_slice_payload(),
    )
    assert created.status_code == 200, created.text
    slice_id = created.json()["slice_id"]

    saved = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers=headers,
        json={
            "slice_id": slice_id,
            "expected_revision": 1,
            "in_scope": build_slice_payload()["in_scope"],
        },
    )
    assert saved.status_code == 200, saved.text

    confirmed_slice = client.post(
        f"/api/projects/{project_id}/build-slice/confirm",
        headers=headers,
        json={"expected_revision": 2},
    )
    assert confirmed_slice.status_code == 200, confirmed_slice.text

    task = client.put(
        f"/api/projects/{project_id}/prototype-task",
        headers=headers,
        json={"slice_id": slice_id, "expected_slice_revision": 2},
    )
    assert task.status_code == 200, task.text
    task_id = task.json()["task_id"]

    confirmed_task = client.post(
        f"/api/projects/{project_id}/prototype-task/confirm",
        headers=headers,
        json={"expected_revision": 1},
    )
    assert confirmed_task.status_code == 200, confirmed_task.text

    quality = QualityEvaluationService(db)
    quality.evaluate_p0(
        ArtifactBinding(
            batch_id=None,
            sample_id=None,
                project_id=project_id,
                artifact_type="BUILD_SLICE",
                artifact_version_id=f"{slice_id}:r2",
            selected_solution_id=None,
            snapshot_id=None,
            upstream_version_ids=(),
            quality_layer="P0",
            evaluator_role="system",
            metric_payload={
                "scope_recall": 1.0,
                "scope_precision": 1.0,
                "acceptance_coverage": 1.0,
                "acceptance_testability": 1.0,
                "constraint_preservation": 1.0,
                "dependency_clarity": 1.0,
                "unsupported_claim_rate": 0.0,
                "unknown_count": 1,
                "evidence_ids": ["m2-evidence-1"],
                "evidence_kind": "IF_GUIDE_M2_BUILD_SLICE",
                "p0_violations": [],
                "p1_gaps": [],
            },
            input_manifest={
                "project_id": project_id,
                "artifact_id": slice_id,
                "artifact_revision": 2,
            },
            evidence_manifest={
                "evidence_ids": ["m2-evidence-1"],
                "evidence_kind": "IF_GUIDE_M2_BUILD_SLICE",
            },
            policy_version="if-guide-m2-v1",
            owner_actor=actor,
            artifact_id=slice_id,
            artifact_revision=2,
            evaluation_scope="IF_GUIDE_M2",
            intent_revision=1,
            slice_id=slice_id,
            slice_revision=2,
        )
    )
    return project_id, slice_id, task_id


def _assert_no_private_content(value):
    forbidden_keys = {
        "owner_actor",
        "actor",
        "metric_payload",
        "input_manifest",
        "evidence_manifest",
        "purpose",
        "in_scope",
        "out_of_scope",
        "implementation_tasks",
        "acceptance_steps",
        "raw_idea",
    }
    if isinstance(value, dict):
        assert not forbidden_keys.intersection(value), value
        for nested in value.values():
            _assert_no_private_content(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_private_content(nested)


def test_m2_inspector_returns_safe_metadata_and_fresh_readback(client, db):
    project_id, slice_id, task_id = _create_confirmed_m2_artifacts(client, db)

    first = IFGuideM2Inspector(db).inspect_project(project_id, actor="m2-owner")
    second = IFGuideM2Inspector(Database(db.path)).inspect_project(
        project_id, actor="m2-owner"
    )

    assert first == second
    assert first["safe_only"] is True
    assert first["project_id"] == project_id
    assert first["owner_actor_matches"] is True
    assert first["build_slice"]["slice_id"] == slice_id
    assert first["build_slice"]["status"] == "CONFIRMED"
    assert first["prototype_task"]["task_id"] == task_id
    assert first["prototype_task"]["status"] == "READY"
    assert first["quality_evaluations"]
    quality = first["quality_evaluations"][0]
    assert quality["evaluation_scope"] == "IF_GUIDE_M2"
    assert quality["artifact_id"] == slice_id
    assert quality["artifact_revision"] == 2
    assert quality["metrics"]["scope_recall"] == 1.0
    assert quality["unknown_count"] == 1
    assert quality["evidence_ids"] == ["m2-evidence-1"]
    assert "metric_payload" not in quality
    _assert_no_private_content(first)


def test_m2_inspector_rejects_unknown_project_without_creating_database(tmp_path):
    db_path = tmp_path / "missing.sqlite3"
    with pytest.raises(KeyError):
        IFGuideM2Inspector(Database(db_path)).inspect_project("missing")
    assert not db_path.exists()


def test_m2_inspector_cli_help_has_no_database_side_effect(tmp_path):
    db_path = tmp_path / "cli.sqlite3"
    script = Path(__file__).parents[1] / "scripts" / "if_guide_m2_inspect.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help", "--database-path", str(db_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--project-id" in result.stdout
    assert not db_path.exists()
