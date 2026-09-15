from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.build_slice import BuildSliceService


def _ready_project(client) -> tuple[str, str]:
    actor = "m2-owner"
    response = client.post(
        "/api/projects",
        headers={"X-Actor": actor},
        json={"title": "M2 test project", "summary": "A project for Build Slice tests."},
    )
    assert response.status_code == 201
    project_id = response.json()["id"]

    response = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": actor},
        json={
            "purpose": "PERSONAL_USE",
            "raw_idea": "先完成一次可复盘的小流程。",
        },
    )
    assert response.status_code == 200
    action = response.json()["first_action"]
    response = client.post(
        f"/api/projects/{project_id}/actions/{action['task_id']}/confirm",
        headers={"X-Actor": actor},
        json={"expected_revision": action["revision"]},
    )
    assert response.status_code == 200
    return project_id, actor


def test_build_slice_create_binds_confirmed_m1_context_and_reopens(db, client):
    project_id, actor = _ready_project(client)
    service = BuildSliceService(db)

    created = service.create_or_get(
        project_id,
        actor=actor,
        expected_snapshot_id=None,
        expected_intent_revision=1,
    )

    assert created["project_id"] == project_id
    assert created["owner_actor"] == actor
    assert created["intent_revision"] == 1
    assert created["status"] == "DRAFT"
    assert created["revision"] == 1
    assert created["purpose"] == "PERSONAL_USE"
    assert created["in_scope"] == []
    assert created["out_of_scope"] == []
    assert created["acceptance_criteria"] == []

    reopened = BuildSliceService(db).get_current(project_id, actor=actor)
    assert reopened["slice_id"] == created["slice_id"]
    assert reopened["intent_revision"] == 1


def test_build_slice_create_is_idempotent_only_for_same_context(db, client):
    project_id, actor = _ready_project(client)
    service = BuildSliceService(db)
    first = service.create_or_get(
        project_id, actor=actor, expected_snapshot_id=None, expected_intent_revision=1
    )

    second = service.create_or_get(
        project_id, actor=actor, expected_snapshot_id=None, expected_intent_revision=1
    )
    assert second["slice_id"] == first["slice_id"]

    with pytest.raises(ConflictError, match="BUILD_SLICE_BINDING_CONFLICT"):
        service.create_or_get(
            project_id,
            actor=actor,
            expected_snapshot_id="snapshot-not-current",
            expected_intent_revision=1,
        )


def test_build_slice_enforces_owner_and_stale_intent_revision(db, client):
    project_id, actor = _ready_project(client)
    service = BuildSliceService(db)

    with pytest.raises(PermissionError):
        service.create_or_get(
            project_id,
            actor="another-account",
            expected_snapshot_id=None,
            expected_intent_revision=1,
        )

    with pytest.raises(ConflictError, match="INTENT_REVISION_CONFLICT"):
        service.create_or_get(
            project_id,
            actor=actor,
            expected_snapshot_id=None,
            expected_intent_revision=0,
        )


def test_build_slice_update_revision_and_persistence(db, client):
    project_id, actor = _ready_project(client)
    service = BuildSliceService(db)
    created = service.create_or_get(
        project_id, actor=actor, expected_snapshot_id=None, expected_intent_revision=1
    )

    updated = service.update(
        project_id,
        created["slice_id"],
        actor=actor,
        expected_revision=1,
        updates={
            "in_scope": ["定义一个可完成的最小流程"],
            "out_of_scope": ["自动部署"],
            "minimal_flow": ["定义", "确认", "检查"],
            "acceptance_criteria": ["用户能按步骤完成一次流程"],
        },
    )

    assert updated["revision"] == 2
    assert updated["status"] == "DRAFT"
    assert updated["in_scope"] == ["定义一个可完成的最小流程"]
    assert updated["out_of_scope"] == ["自动部署"]
    assert BuildSliceService(db).get_current(project_id, actor=actor)["revision"] == 2

    with pytest.raises(ConflictError, match="BUILD_SLICE_REVISION_CONFLICT"):
        service.update(
            project_id,
            created["slice_id"],
            actor=actor,
            expected_revision=1,
            updates={"in_scope": ["过期修改"]},
        )
