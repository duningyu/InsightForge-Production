from __future__ import annotations

import pytest

from app.services.if_guide_m2_quality import (
    evaluate_build_slice,
    evaluate_prototype_task,
)
from app.services.build_slice import BuildSliceService
from app.services.prototype_task import PrototypeTaskService
from app.errors import ConflictError

from tests.test_m2_routes import build_slice_payload, create_m1_ready_project
from tests.test_prototype_task_generation import _confirmed_slice


def _complete_build_slice() -> dict:
    payload = build_slice_payload()
    payload["slice_id"] = "slice-negative"
    payload["project_id"] = "project-negative"
    payload["actor"] = "owner"
    payload["revision"] = 1
    payload["snapshot_id"] = "snapshot-negative"
    return payload


def _complete_task() -> dict:
    return {
        "task_id": "task-negative",
        "project_id": "project-negative",
        "actor": "owner",
        "slice_id": "slice-negative",
        "slice_revision": 1,
        "revision": 1,
        "scope": ["完成一次最小流程"],
        "inputs": ["用户输入"],
        "outputs": ["结果记录"],
        "existing_behaviors_to_preserve": ["保留当前页面"],
        "explicit_non_goals": ["不做部署"],
        "known_technical_context": [{"name": "当前路由", "status": "KNOWN", "verified": True}],
        "unknown_dependencies": [{"name": "真实使用频率", "status": "UNKNOWN"}],
        "implementation_tasks": ["实现本地流程"],
        "acceptance_steps": ["准备输入", "完成流程", "检查结果"],
        "failure_recovery_notes": ["失败时保留原因并停止"],
        "required_return_evidence": ["返回结果记录"],
        "permission_risk_notes": ["不执行外部写入"],
    }


def test_quality_rejects_missing_scope_and_acceptance_contract():
    build = _complete_build_slice()
    build["in_scope"] = []
    build["acceptance_criteria"] = []

    result = evaluate_build_slice(build)

    assert result["status"] == "FAIL"
    assert "M2_MISSING_IN_SCOPE" in result["codes"]
    assert "M2_MISSING_ACCEPTANCE_CRITERIA" in result["codes"]


def test_quality_rejects_false_execution_and_forbidden_external_actions():
    task = _complete_task()
    task["known_technical_context"] = ["已部署到生产环境"]
    task["implementation_tasks"] = ["自动部署到生产环境"]

    result = evaluate_prototype_task(task)

    assert result["status"] == "FAIL"
    assert "M2_FALSE_EXECUTION_CLAIM" in result["codes"]
    assert "M2_FORBIDDEN_EXTERNAL_ACTION" in result["codes"]


def test_quality_keeps_unknown_dependency_unknown_and_rejects_fabricated_verified_dependency():
    task = _complete_task()
    task["quality_rubric"] = {
        "rubric_version": "if-guide-m2-quality-v1",
        "evidence_ids": ["dependency-negative-1"],
        "dependencies": [
            {"id": "unverified-dependency", "status": "KNOWN", "verified": False},
            {"id": "unknown-dependency", "status": "UNKNOWN"},
        ],
    }

    result = evaluate_prototype_task(task)

    assert result["status"] == "FAIL"
    assert "M2_FABRICATED_DEPENDENCY_MARKED_VERIFIED" in result["codes"]
    assert result["metrics"]["dependency_clarity"] < 1


def test_routes_fail_closed_for_foreign_task_and_stale_task_revision(client):
    project_id = create_m1_ready_project(client, actor="negative-owner")
    headers = {"X-Actor": "negative-owner"}
    created = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers=headers,
        json=build_slice_payload(),
    )
    assert created.status_code == 200, created.text
    confirmed = client.post(
        f"/api/projects/{project_id}/build-slice/confirm",
        headers=headers,
        json={"expected_revision": created.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    task = client.put(
        f"/api/projects/{project_id}/prototype-task",
        headers=headers,
        json={"slice_id": confirmed.json()["slice_id"], "expected_slice_revision": 1},
    )
    assert task.status_code == 200, task.text

    foreign = client.get(
        f"/api/projects/{project_id}/prototype-task",
        headers={"X-Actor": "other-account"},
    )
    assert foreign.status_code == 403, foreign.text

    stale = client.put(
        f"/api/projects/{project_id}/prototype-task",
        headers=headers,
        json={
            "task_id": task.json()["task_id"],
            "expected_revision": 99,
            "implementation_tasks": ["过期写入"],
        },
    )
    assert stale.status_code == 409, stale.text


def test_service_rejects_task_bound_to_wrong_slice_without_mutating_current(db, client):
    slices, project_id, actor, confirmed_slice = _confirmed_slice(client, db)
    tasks = PrototypeTaskService(db)
    task = tasks.generate_rule_first(
        project_id,
        actor=actor,
        slice_id=confirmed_slice["slice_id"],
        expected_slice_revision=confirmed_slice["revision"],
    )
    with pytest.raises(ValueError, match="unsupported prototype task fields"):
        tasks.update(
            project_id,
            task["task_id"],
            actor=actor,
            expected_revision=task["revision"],
            updates={"slice_id": "wrong-slice"},
        )
    current = tasks.get_current(project_id, actor=actor)
    assert current["slice_id"] == slices.get_current(project_id, actor=actor)["slice_id"]


def test_m2_routes_have_no_execution_or_formal_handoff_surface(client):
    project_id = create_m1_ready_project(client)
    routes = {route.path for route in client.app.routes}
    assert f"/api/projects/{project_id}/prototype-task/execute" not in routes
    assert f"/api/projects/{project_id}/prototype-task/deploy" not in routes
    assert f"/api/projects/{project_id}/prototype-task/handoff" not in routes
