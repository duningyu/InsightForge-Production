from __future__ import annotations

import pytest


def create_project(client, actor: str = "m1-owner") -> str:
    response = client.post(
        "/api/projects",
        headers={"X-Actor": actor},
        json={"title": "M1 contract project", "summary": "A project for the M1 contract tests."},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


PURPOSES = ("LEARNING", "PERSONAL_USE", "FOR_OTHERS", "UNSPECIFIED")


@pytest.mark.parametrize("purpose", PURPOSES)
def test_m1_purpose_creates_complete_deterministic_first_action(client, purpose):
    project_id = create_project(client)

    response = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "m1-owner"},
        json={"purpose": purpose, "raw_idea": "我想把一个模糊想法变成下一步可执行行动。"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"]["purpose"] == purpose
    assert payload["intent"]["revision"] == 1
    action = payload["first_action"]
    assert action["status"] == "READY"
    assert all(action[field] for field in (
        "goal", "why_now", "inputs", "steps", "expected_artifact",
        "checks", "branches", "stop_condition", "prohibited_actions",
    ))
    assert payload["quality"]["structural_coverage"]["covered"] == 9
    assert payload["quality"]["structural_coverage"]["required"] == 9
    assert payload["quality"]["provider_dispatches"] == 0
    assert payload["quality"]["provider_transports"] == 0
    assert payload["quality"]["search_requests"] == 0
    assert payload["quality"]["source_identity"] == "user"
    assert payload["quality"]["purpose_alignment"] == "PASS"
    assert payload["quality"]["guard"]


def test_m1_intent_and_action_reopen_from_fresh_client(client, db):
    project_id = create_project(client)
    created = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "m1-owner"},
        json={"purpose": "PERSONAL_USE", "raw_idea": "我想减少每周整理资料时的遗漏。"},
    )
    assert created.status_code == 200, created.text

    from fastapi.testclient import TestClient
    from app.main import create_app

    fresh_app = create_app(database_path=db.path, seed=False)
    with TestClient(fresh_app) as fresh_client:
        reopened = fresh_client.get(
            f"/api/projects/{project_id}/intent",
            headers={"X-Actor": "m1-owner"},
        )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["intent"]["revision"] == 1
    assert reopened.json()["first_action"]["status"] == "READY"


def test_m1_purpose_change_creates_new_revision_and_action(client):
    project_id = create_project(client)
    first = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "m1-owner"},
        json={"purpose": "LEARNING", "raw_idea": "我想练习拆解一个问题。"},
    )
    assert first.status_code == 200, first.text
    first_task = first.json()["first_action"]["task_id"]

    second = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "m1-owner"},
        json={
            "purpose": "FOR_OTHERS",
            "raw_idea": "我想先向身边的人验证一个具体问题。",
            "expected_revision": 1,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["intent"]["revision"] == 2
    assert second.json()["first_action"]["task_id"] != first_task


def test_m1_stale_revision_is_conflict(client):
    project_id = create_project(client)
    created = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "m1-owner"},
        json={"purpose": "UNSPECIFIED", "raw_idea": "我想先做一个低风险的小尝试。"},
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["first_action"]["task_id"]

    updated = client.patch(
        f"/api/projects/{project_id}/actions/{task_id}",
        headers={"X-Actor": "m1-owner"},
        json={"expected_revision": 1, "goal": "先完成一个可撤销的小实验。"},
    )
    assert updated.status_code == 200, updated.text

    stale = client.patch(
        f"/api/projects/{project_id}/actions/{task_id}",
        headers={"X-Actor": "m1-owner"},
        json={"expected_revision": 1, "goal": "不应覆盖已经保存的行动。"},
    )
    assert stale.status_code == 409, stale.text


def test_m1_cross_account_access_is_denied(client):
    project_id = create_project(client, actor="alice")
    created = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "alice"},
        json={"purpose": "PERSONAL_USE", "raw_idea": "我想改善自己的整理流程。"},
    )
    assert created.status_code == 200, created.text

    for method, url, kwargs in (
        ("get", f"/api/projects/{project_id}/intent", {}),
        ("put", f"/api/projects/{project_id}/intent", {"json": {"purpose": "LEARNING", "raw_idea": "越权"}}),
    ):
        response = getattr(client, method)(url, headers={"X-Actor": "bob"}, **kwargs)
        assert response.status_code == 403, response.text


def test_public_project_creation_does_not_accept_evaluation_identity_controls(client, db):
    with db.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    response = client.post(
        "/api/projects",
        headers={"X-Actor": "m1-owner"},
        json={
            "title": "普通项目",
            "summary": "不能从公共创建接口伪造评测身份。",
            "project_origin": "demo",
            "exclude_from_beta_metrics": True,
        },
    )
    assert response.status_code == 422, response.text
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == before


def test_m1_action_is_idempotent_and_confirmed_without_execution_state(client):
    project_id = create_project(client)
    created = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "m1-owner"},
        json={"purpose": "LEARNING", "raw_idea": "我想验证一个学习方法是否适合自己。"},
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["first_action"]["task_id"]

    ensured = client.post(
        f"/api/projects/{project_id}/actions/first",
        headers={"X-Actor": "m1-owner"},
    )
    assert ensured.status_code == 200, ensured.text
    assert ensured.json()["first_action"]["task_id"] == task_id

    confirmed = client.post(
        f"/api/projects/{project_id}/actions/{task_id}/confirm",
        headers={"X-Actor": "m1-owner"},
        json={"expected_revision": 1},
    )
    assert confirmed.status_code == 200, confirmed.text
    action = confirmed.json()["first_action"]
    assert action["confirmed"] is True
    assert action["status"] == "READY"
    assert "executed" not in action
    assert "validated" not in action


def test_m1_rejects_placeholder_action_content(client):
    project_id = create_project(client)
    created = client.put(
        f"/api/projects/{project_id}/intent",
        headers={"X-Actor": "m1-owner"},
        json={"purpose": "UNSPECIFIED", "raw_idea": "我想先澄清一个问题。"},
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["first_action"]["task_id"]

    response = client.patch(
        f"/api/projects/{project_id}/actions/{task_id}",
        headers={"X-Actor": "m1-owner"},
        json={"expected_revision": 1, "goal": "待定"},
    )
    assert response.status_code == 422, response.text
