from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.build_slice import BuildSliceService
from app.services.prototype_task import PrototypeTaskService

from tests.test_prototype_task_generation import _COMPLETE, _confirmed_slice, _ready_project


def _task(client, db) -> tuple[PrototypeTaskService, BuildSliceService, str, str, dict]:
    slices, project_id, actor, confirmed = _confirmed_slice(client, db)
    tasks = PrototypeTaskService(db)
    task = tasks.generate_rule_first(
        project_id,
        actor=actor,
        slice_id=confirmed["slice_id"],
        expected_slice_revision=confirmed["revision"],
    )
    return tasks, slices, project_id, actor, task


def test_prototype_task_edit_save_reopen_and_confirm(db, client):
    tasks, _, project_id, actor, task = _task(client, db)

    updated = tasks.update(
        project_id,
        task["task_id"],
        actor=actor,
        expected_revision=task["revision"],
        updates={
            "implementation_tasks": ["定义范围", "完成一次本地原型流程"],
            "acceptance_steps": [
                "用户确认范围后，页面显示对应实现任务",
                "刷新页面后，仍显示同一任务版本",
            ],
        },
    )
    assert updated["revision"] == task["revision"] + 1
    assert updated["status"] == "DRAFT"

    reopened = tasks.get_current(project_id, actor=actor)
    assert reopened["task_id"] == task["task_id"]
    assert reopened["revision"] == updated["revision"]
    assert reopened["acceptance_steps"] == updated["acceptance_steps"]

    confirmed = tasks.confirm(
        project_id,
        task["task_id"],
        actor=actor,
        expected_revision=updated["revision"],
    )
    assert confirmed["status"] == "READY"
    assert confirmed["p0_status"] == "PASS"
    assert tasks.get_current(project_id, actor=actor)["status"] == "READY"


def test_prototype_task_confirmation_requires_complete_acceptance_contract(db, client):
    tasks, _, project_id, actor, task = _task(client, db)
    updated = tasks.update(
        project_id,
        task["task_id"],
        actor=actor,
        expected_revision=task["revision"],
        updates={"acceptance_steps": []},
    )

    with pytest.raises(ConflictError, match="M2_MISSING_ACCEPTANCE_STEPS"):
        tasks.confirm(
            project_id,
            task["task_id"],
            actor=actor,
            expected_revision=updated["revision"],
        )


def test_prototype_task_revision_conflict_is_fail_closed(db, client):
    tasks, _, project_id, actor, task = _task(client, db)
    updated = tasks.update(
        project_id,
        task["task_id"],
        actor=actor,
        expected_revision=task["revision"],
        updates={"implementation_tasks": ["新的明确实现步骤"]},
    )

    with pytest.raises(ConflictError, match="PROTOTYPE_TASK_REVISION_CONFLICT"):
        tasks.confirm(
            project_id,
            task["task_id"],
            actor=actor,
            expected_revision=task["revision"],
        )
    with pytest.raises(ConflictError, match="PROTOTYPE_TASK_REVISION_CONFLICT"):
        tasks.update(
            project_id,
            task["task_id"],
            actor=actor,
            expected_revision=task["revision"],
            updates={"implementation_tasks": ["过期写入"]},
        )
    assert tasks.get_current(project_id, actor=actor)["revision"] == updated["revision"]


def test_build_slice_revision_invalidates_prototype_task(db, client):
    tasks, slices, project_id, actor, task = _task(client, db)
    slice_row = slices.get_current(project_id, actor=actor)
    changed = slices.update(
        project_id,
        slice_row["slice_id"],
        actor=actor,
        expected_revision=slice_row["revision"],
        updates={"in_scope": ["变更后的明确范围"], **_COMPLETE},
    )
    assert changed["revision"] == task["slice_revision"] + 1

    with pytest.raises(ConflictError, match="PROTOTYPE_TASK_SLICE_STALE"):
        tasks.confirm(
            project_id,
            task["task_id"],
            actor=actor,
            expected_revision=task["revision"],
        )


def test_prototype_task_is_owner_scoped_and_rejects_forbidden_external_action(db, client):
    tasks, _, project_id, actor, task = _task(client, db)
    with pytest.raises(PermissionError):
        tasks.get_current(project_id, actor="other-actor")

    updated = tasks.update(
        project_id,
        task["task_id"],
        actor=actor,
        expected_revision=task["revision"],
        updates={"implementation_tasks": ["自动部署到生产环境"]},
    )
    result = tasks.evaluate_p0(project_id, updated["task_id"], actor=actor)
    assert result["status"] == "FAIL"
    assert "M2_FORBIDDEN_EXTERNAL_ACTION" in result["codes"]
