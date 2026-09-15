from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.build_slice import BuildSliceService


def _ready_project(client) -> tuple[str, str]:
    actor = "m2-confirm-owner"
    response = client.post(
        "/api/projects",
        headers={"X-Actor": actor},
        json={"title": "M2 confirmation project", "summary": "A project for confirmation tests."},
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


def _create_slice(client, db) -> tuple[BuildSliceService, str, str, dict]:
    project_id, actor = _ready_project(client)
    service = BuildSliceService(db)
    created = service.create_or_get(
        project_id, actor=actor, expected_snapshot_id=None, expected_intent_revision=1
    )
    return service, project_id, actor, created


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


def test_build_slice_confirm_requires_complete_scope_and_persists_confirmation(db, client):
    service, project_id, actor, created = _create_slice(client, db)
    updated = service.update(
        project_id,
        created["slice_id"],
        actor=actor,
        expected_revision=1,
        updates=_COMPLETE,
    )

    confirmed = service.confirm(
        project_id,
        created["slice_id"],
        actor=actor,
        expected_revision=updated["revision"],
    )

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["p0_status"] == "PASS"
    reopened = service.get_current(project_id, actor=actor)
    assert reopened["status"] == "CONFIRMED"
    assert reopened["revision"] == updated["revision"]


def test_build_slice_confirm_rejects_missing_required_contract_fields(db, client):
    service, project_id, actor, created = _create_slice(client, db)
    service.update(
        project_id,
        created["slice_id"],
        actor=actor,
        expected_revision=1,
        updates={"in_scope": ["定义一个流程"], "out_of_scope": ["自动部署"]},
    )

    with pytest.raises(ConflictError, match="M2_MISSING_MINIMAL_FLOW"):
        service.confirm(
            project_id,
            created["slice_id"],
            actor=actor,
            expected_revision=2,
        )


def test_build_slice_confirm_rejects_stale_revision(db, client):
    service, project_id, actor, created = _create_slice(client, db)
    updated = service.update(
        project_id,
        created["slice_id"],
        actor=actor,
        expected_revision=1,
        updates=_COMPLETE,
    )

    with pytest.raises(ConflictError, match="BUILD_SLICE_REVISION_CONFLICT"):
        service.confirm(
            project_id,
            created["slice_id"],
            actor=actor,
            expected_revision=1,
        )

    assert updated["status"] == "DRAFT"


def test_build_slice_p0_rejects_unverified_execution_claims(db, client):
    service, project_id, actor, created = _create_slice(client, db)
    updates = dict(_COMPLETE)
    updates["acceptance_criteria"] = ["该流程已经部署到生产环境"]
    updated = service.update(
        project_id,
        created["slice_id"],
        actor=actor,
        expected_revision=1,
        updates=updates,
    )

    result = service.evaluate_p0(project_id, created["slice_id"], actor=actor)
    assert result["status"] == "FAIL"
    assert "M2_FALSE_EXECUTION_CLAIM" in result["codes"]
    with pytest.raises(ConflictError, match="M2_FALSE_EXECUTION_CLAIM"):
        service.confirm(
            project_id,
            created["slice_id"],
            actor=actor,
            expected_revision=updated["revision"],
        )
