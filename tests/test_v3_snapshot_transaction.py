from __future__ import annotations

import json
import sqlite3

import pytest


def prepared_project(client):
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]
    confirmed = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "理解准确"},
    )
    assert confirmed.status_code == 200, confirmed.text
    generated = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert generated.status_code == 201, generated.text
    return project_id, generated.json()["candidates"]


def test_confirm_solution_atomically_creates_decision_claims_snapshot_pointer_canvas_and_audit(client):
    project_id, candidates = prepared_project(client)
    selected = next(item for item in candidates if item["mechanism"] == "rule_based")
    response = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": "先验证低数据依赖的提醒价值",
            "human_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert snapshot["version"] == 1
    assert snapshot["snapshot_origin"] == "quick_value_flow"
    assert snapshot["solution"]["candidate_id"] == selected["id"]

    decision = client.app.state.db.fetch_one(
        "SELECT * FROM project_decisions WHERE project_id=? AND decision_type='solution_selection'",
        (project_id,),
    )
    assert decision["status"] == "confirmed"
    assert decision["decision_version"] == 1
    claims = client.app.state.db.fetch_all(
        "SELECT * FROM project_claims WHERE project_id=? ORDER BY claim_type,id", (project_id,)
    )
    assert claims
    assert {row["claim_type"] for row in claims} <= {
        "target_user", "user_problem", "behavior", "value", "feasibility"
    }
    assert all(row["verification_status"] == "unverified" for row in claims)
    assert any(row["provenance"] == "model_hypothesis" for row in claims)

    project = client.app.state.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
    assert project["current_snapshot_id"] == snapshot["id"]
    canvas = client.get(f"/api/projects/{project_id}/canvas")
    assert canvas.status_code == 200
    canvas_body = canvas.json()
    assert canvas_body["target_users"] == snapshot["target_user"]["primary"]
    assert canvas_body["problem"] == snapshot["problem"]["statement"]
    assert canvas_body["goals"] == snapshot["mvp"]["outcomes"]
    assert canvas_body["success_metrics"] == snapshot["mvp"]["acceptance_criteria"]
    assert client.app.state.db.fetch_one(
        "SELECT * FROM project_canvas_versions WHERE project_id=? AND version=1", (project_id,)
    ) is not None
    audit = client.app.state.db.fetch_one(
        "SELECT * FROM audit_events WHERE entity_type='project_snapshot' AND entity_id=?",
        (snapshot["id"],),
    )
    assert audit is not None


def test_solution_confirmation_failure_rolls_back_every_atomic_write(client):
    project_id, candidates = prepared_project(client)
    selected = candidates[0]
    with client.app.state.db.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_project_claim_insert
            BEFORE INSERT ON project_claims
            BEGIN SELECT RAISE(ABORT, 'injected claim failure'); END;
            """
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected claim failure"):
        client.app.state.snapshots.confirm_initial_solution(
            project_id,
            strategy="single",
            candidate_ids=[selected["id"]],
            rationale="test rollback",
            human_confirmed=True,
            actor="test",
        )
    assert client.app.state.db.fetch_one(
        "SELECT id FROM project_decisions WHERE project_id=? AND decision_type='solution_selection'",
        (project_id,),
    ) is None
    assert client.app.state.db.fetch_one(
        "SELECT id FROM project_snapshots WHERE project_id=?", (project_id,)
    ) is None
    assert client.app.state.db.fetch_one(
        "SELECT project_id FROM project_canvas WHERE project_id=?", (project_id,)
    ) is None
    assert client.app.state.db.fetch_one(
        "SELECT id FROM audit_events WHERE entity_type='project_snapshot' AND entity_id IN "
        "(SELECT id FROM project_snapshots WHERE project_id=?)", (project_id,)
    ) is None


def test_staged_selection_uses_first_candidate_as_mvp_and_only_existing_candidates_as_evolution(client):
    project_id, candidates = prepared_project(client)
    rule = next(item for item in candidates if item["mechanism"] == "rule_based")
    forecast = next(item for item in candidates if item["mechanism"] == "prediction_based")
    response = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "staged",
            "candidate_ids": [rule["id"], forecast["id"]],
            "rationale": "先规则验证，再升级预测",
            "human_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text
    solution = response.json()["solution"]
    assert solution["candidate_id"] == rule["id"]
    assert [item["candidate_id"] for item in solution["evolution_path"]] == [forecast["id"]]
    assert {item["candidate_id"] for item in solution["evolution_path"]} <= {c["id"] for c in candidates}


def test_snapshot_read_routes_return_current_and_immutable_version(client):
    project_id, candidates = prepared_project(client)
    selected = candidates[0]
    created = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single", "candidate_ids": [selected["id"]],
            "rationale": "确认", "human_confirmed": True,
        },
    )
    assert created.status_code == 201
    snapshot_id = created.json()["id"]
    current = client.get(f"/api/projects/{project_id}/snapshot")
    versions = client.get(f"/api/projects/{project_id}/snapshots")
    by_id = client.get(f"/api/project-snapshots/{snapshot_id}")
    assert current.status_code == versions.status_code == by_id.status_code == 200
    assert current.json()["id"] == snapshot_id
    assert versions.json()[0]["id"] == snapshot_id
    assert by_id.json()["content_sha256"] == created.json()["content_sha256"]


def test_snapshot_managed_canvas_write_requires_snapshot_reconciliation(client):
    project_id, candidates = prepared_project(client)
    snapshot = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single", "candidate_ids": [candidates[0]["id"]],
            "rationale": "确认", "human_confirmed": True,
        },
    ).json()
    response = client.put(
        f"/api/projects/{project_id}/canvas",
        json={
            "problem": "直接覆盖",
            "target_users": "用户",
            "goals": ["目标"],
            "non_goals": [],
            "success_metrics": ["指标"],
            "constraints": [],
        },
    )
    assert response.status_code == 200
    health = client.app.state.artifact_health.get("project_snapshot", snapshot["id"])
    assert health["health_status"] == "needs_review"
    proposals = client.get(f"/api/projects/{project_id}/change-proposals").json()
    assert len([p for p in proposals if p["proposal_type"] == "snapshot_canvas_reconciliation" and p["status"] == "open"]) == 1


def test_solution_selection_requires_human_confirmation(client):
    project_id, candidates = prepared_project(client)
    response = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single", "candidate_ids": [candidates[0]["id"]],
            "rationale": "未确认", "human_confirmed": False,
        },
    )
    assert response.status_code == 403
