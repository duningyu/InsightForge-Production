from __future__ import annotations


def create_m1_ready_project(client, actor: str = "m2-owner") -> str:
    created = client.post(
        "/api/projects",
        headers={"X-Actor": actor},
        json={
            "title": "M2 route project",
            "summary": "A project used to verify the M2 business path.",
        },
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    intent = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": actor},
        json={
            "purpose": "PERSONAL_USE",
            "raw_idea": "我想把一次真实的小流程缩小成可以复盘的最小尝试。",
        },
    )
    assert intent.status_code == 200, intent.text
    action = intent.json()["first_action"]
    confirmed = client.post(
        f"/api/projects/{project_id}/actions/{action['task_id']}/confirm",
        headers={"X-Actor": actor},
        json={"expected_revision": action["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return project_id


def build_slice_payload() -> dict:
    return {
        "expected_snapshot_id": None,
        "expected_intent_revision": 1,
        "confirmed_constraints": ["只做一次可撤销的小范围尝试。"],
        "in_scope": ["记录一次真实输入", "完成一次最小流程"],
        "out_of_scope": ["不做自动部署", "不做支付接入"],
        "minimal_flow": ["填写输入", "完成流程", "记录结果"],
        "acceptance_criteria": ["用户能完成一次流程", "结果能被复盘"],
        "inputs": ["用户自己的材料"],
        "expected_outputs": ["一份结果记录"],
        "error_handling": ["失败时保留原因并停止扩大范围"],
        "unknowns": ["真实使用频率仍未知"],
        "constraint_notes": ["不得把一次尝试写成市场验证"],
    }


def test_m2_routes_cover_build_slice_and_prototype_task_lifecycle(client):
    project_id = create_m1_ready_project(client)
    headers = {"X-Actor": "m2-owner"}

    created = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers=headers,
        json=build_slice_payload(),
    )
    assert created.status_code == 200, created.text
    build_slice = created.json()
    assert build_slice["status"] == "DRAFT"
    assert build_slice["revision"] == 1
    assert build_slice["in_scope"] == ["记录一次真实输入", "完成一次最小流程"]

    saved = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers=headers,
        json={
            "slice_id": build_slice["slice_id"],
            "expected_revision": 1,
            "in_scope": ["记录一次真实输入", "完成一次最小流程", "记录一个可观察结果"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2

    confirmed = client.post(
        f"/api/projects/{project_id}/build-slice/confirm",
        headers=headers,
        json={"expected_revision": 2},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"

    generated = client.put(
        f"/api/projects/{project_id}/prototype-task",
        headers=headers,
        json={
            "slice_id": build_slice["slice_id"],
            "expected_slice_revision": 2,
        },
    )
    assert generated.status_code == 200, generated.text
    task = generated.json()
    assert task["status"] == "DRAFT"
    assert task["scope"] == confirmed.json()["in_scope"]
    assert task["explicit_non_goals"] == confirmed.json()["out_of_scope"]
    assert all("executed" not in item.lower() for item in task["known_technical_context"])

    task_saved = client.put(
        f"/api/projects/{project_id}/prototype-task",
        headers=headers,
        json={
            "task_id": task["task_id"],
            "expected_revision": 1,
            "acceptance_steps": ["准备输入", "完成流程", "检查结果"],
        },
    )
    assert task_saved.status_code == 200, task_saved.text
    assert task_saved.json()["revision"] == 2

    ready = client.post(
        f"/api/projects/{project_id}/prototype-task/confirm",
        headers=headers,
        json={"expected_revision": 2},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "READY"

    slice_quality = client.get(
        f"/api/projects/{project_id}/build-slice/quality", headers=headers
    )
    task_quality = client.get(
        f"/api/projects/{project_id}/prototype-task/quality", headers=headers
    )
    assert slice_quality.status_code == 200, slice_quality.text
    assert task_quality.status_code == 200, task_quality.text
    assert slice_quality.json()["status"] == "PASS"
    assert task_quality.json()["status"] == "PASS"
    assert slice_quality.json()["evidence_kind"] == "IF_GUIDE_M2_BUILD_SLICE"
    assert task_quality.json()["evidence_kind"] == "IF_GUIDE_M2_PROTOTYPE_TASK"

    reopened = client.get(
        f"/api/projects/{project_id}/prototype-task", headers=headers
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["revision"] == 2
    assert reopened.json()["status"] == "READY"
    assert reopened.json()["acceptance_steps"] == ["准备输入", "完成流程", "检查结果"]


def test_m2_routes_enforce_account_isolation_and_stale_revision(client):
    project_id = create_m1_ready_project(client, actor="alice")

    foreign_get = client.get(
        f"/api/projects/{project_id}/build-slice",
        headers={"X-Actor": "bob"},
    )
    assert foreign_get.status_code == 403, foreign_get.text

    created = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers={"X-Actor": "alice"},
        json=build_slice_payload(),
    )
    assert created.status_code == 200, created.text

    stale = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers={"X-Actor": "alice"},
        json={
            "slice_id": created.json()["slice_id"],
            "expected_revision": 99,
            "in_scope": ["不应覆盖当前草稿"],
        },
    )
    assert stale.status_code == 409, stale.text

    malformed = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers={"X-Actor": "alice"},
        json={"expected_intent_revision": "not-an-int"},
    )
    assert malformed.status_code == 422, malformed.text


def test_m2_routes_do_not_offer_external_execution_or_handoff_actions(client):
    project_id = create_m1_ready_project(client)
    headers = {"X-Actor": "m2-owner"}
    for path in (
        f"/api/projects/{project_id}/build-slice/execute",
        f"/api/projects/{project_id}/prototype-task/deploy",
        f"/api/projects/{project_id}/prototype-task/handoff",
    ):
        response = client.post(path, headers=headers, json={})
        assert response.status_code == 404, response.text
