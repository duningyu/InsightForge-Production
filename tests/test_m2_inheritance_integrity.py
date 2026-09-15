from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.project_intent import ProjectIntentService
from app.services.prototype_task import PrototypeTaskService

from tests.test_prototype_task_lifecycle import _COMPLETE, _task


def test_build_slice_revision_marks_bound_task_needs_revision(db, client):
    tasks, slices, project_id, actor, task = _task(client, db)
    current = slices.get_current(project_id, actor=actor)

    changed = slices.update(
        project_id,
        current["slice_id"],
        actor=actor,
        expected_revision=current["revision"],
        updates={"in_scope": ["变更后的明确范围"], **_COMPLETE},
    )

    assert changed["status"] == "DRAFT"
    assert tasks.get_current(project_id, actor=actor)["status"] == "NEEDS_REVISION"
    with pytest.raises(ConflictError, match="PROTOTYPE_TASK_SLICE_STALE"):
        tasks.confirm(
            project_id,
            task["task_id"],
            actor=actor,
            expected_revision=task["revision"],
        )


def test_intent_revision_marks_slice_and_task_needs_revision(db, client):
    tasks, slices, project_id, actor, task = _task(client, db)

    ProjectIntentService(db).set_intent(
        project_id,
        purpose="PERSONAL_USE",
        raw_idea="上游目的发生变化，需要重新确认本轮范围。",
        actor=actor,
        expected_revision=1,
    )

    assert slices.get_current(project_id, actor=actor)["status"] == "NEEDS_REVISION"
    assert tasks.get_current(project_id, actor=actor)["status"] == "NEEDS_REVISION"


def test_prototype_task_rejects_out_of_scope_work_from_bound_slice(db, client):
    tasks, _, project_id, actor, task = _task(client, db)
    updated = tasks.update(
        project_id,
        task["task_id"],
        actor=actor,
        expected_revision=task["revision"],
        updates={"implementation_tasks": ["多人协作"]},
    )

    result = tasks.evaluate_p0(project_id, updated["task_id"], actor=actor)

    assert result["status"] == "FAIL"
    assert "M2_SCOPE_INHERITANCE_CONFLICT" in result["codes"]
