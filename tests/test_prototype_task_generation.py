from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.build_slice import BuildSliceService
from app.services.prototype_task import PrototypeTaskService


def _ready_project(client) -> tuple[str, str]:
    actor = "m2-task-owner"
    response = client.post(
        "/api/projects",
        headers={"X-Actor": actor},
        json={"title": "M2 prototype project", "summary": "A project for task generation tests."},
    )
    assert response.status_code == 201
    project_id = response.json()["id"]
    response = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": actor},
        json={"purpose": "PERSONAL_USE", "raw_idea": "先完成一次可复盘的小流程。"},
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


_COMPLETE = {
    "in_scope": ["定义一个可完成的最小流程"],
    "out_of_scope": ["自动部署", "多人协作"],
    "minimal_flow": ["定义范围", "确认范围", "查看实现任务"],
    "acceptance_criteria": ["用户能按步骤完成一次流程", "刷新后仍能看到已确认范围"],
    "inputs": ["用户确认的范围"],
    "expected_outputs": ["可检查的原型任务"],
    "error_handling": ["过期版本必须提示重新加载"],
    "unknowns": ["具体前端布局仍需实现时确认"],
}


def _confirmed_slice(client, db) -> tuple[BuildSliceService, str, str, dict]:
    project_id, actor = _ready_project(client)
    slices = BuildSliceService(db)
    created = slices.create_or_get(
        project_id, actor=actor, expected_snapshot_id=None, expected_intent_revision=1
    )
    updated = slices.update(
        project_id, created["slice_id"], actor=actor, expected_revision=1, updates=_COMPLETE
    )
    confirmed = slices.confirm(
        project_id, created["slice_id"], actor=actor, expected_revision=updated["revision"]
    )
    return slices, project_id, actor, confirmed


def test_prototype_task_generation_requires_confirmed_build_slice(db, client):
    project_id, actor = _ready_project(client)
    slices = BuildSliceService(db)
    created = slices.create_or_get(
        project_id, actor=actor, expected_snapshot_id=None, expected_intent_revision=1
    )

    with pytest.raises(ConflictError, match="BUILD_SLICE_NOT_CONFIRMED"):
        PrototypeTaskService(db).generate_rule_first(
            project_id, actor=actor, slice_id=created["slice_id"], expected_slice_revision=1
        )


def test_prototype_task_generation_is_rule_first_and_exactly_bound(db, client):
    _, project_id, actor, confirmed = _confirmed_slice(client, db)
    service = PrototypeTaskService(db)

    task = service.generate_rule_first(
        project_id,
        actor=actor,
        slice_id=confirmed["slice_id"],
        expected_slice_revision=confirmed["revision"],
    )

    assert task["project_id"] == project_id
    assert task["owner_actor"] == actor
    assert task["slice_id"] == confirmed["slice_id"]
    assert task["slice_revision"] == confirmed["revision"]
    assert task["snapshot_id"] is None
    assert task["purpose"] == confirmed["purpose"]
    assert task["scope"] == confirmed["in_scope"]
    assert task["explicit_non_goals"] == confirmed["out_of_scope"]
    assert task["acceptance_steps"] == confirmed["acceptance_criteria"]
    assert task["unknown_dependencies"] == confirmed["unknowns"]
    assert task["status"] == "DRAFT"
    assert all("deployed" not in item.lower() for item in task["known_technical_context"])


def test_prototype_task_generation_reuses_same_bound_revision(db, client):
    _, project_id, actor, confirmed = _confirmed_slice(client, db)
    service = PrototypeTaskService(db)
    first = service.generate_rule_first(
        project_id, actor=actor, slice_id=confirmed["slice_id"], expected_slice_revision=confirmed["revision"]
    )
    second = service.generate_rule_first(
        project_id, actor=actor, slice_id=confirmed["slice_id"], expected_slice_revision=confirmed["revision"]
    )

    assert second["task_id"] == first["task_id"]
    with pytest.raises(ConflictError, match="BUILD_SLICE_REVISION_CONFLICT"):
        service.generate_rule_first(
            project_id, actor=actor, slice_id=confirmed["slice_id"], expected_slice_revision=99
        )
