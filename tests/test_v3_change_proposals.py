from __future__ import annotations

import json

import pytest

from app.db import utc_now


def prepare_snapshot(client):
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    project_id = quick.json()["project_id"]
    client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认"},
    )
    candidates = client.post(f"/api/projects/{project_id}/solutions/generate").json()["candidates"]
    selected = next(item for item in candidates if item["mechanism"] == "rule_based")
    snapshot = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": "先做最低数据依赖方案",
            "human_confirmed": True,
        },
    ).json()
    return project_id, snapshot


def set_claim_status(db, claim_id: str, status: str) -> None:
    db.execute(
        "UPDATE project_claims SET verification_status=?, updated_at=? WHERE id=?",
        (status, utc_now(), claim_id),
    )


def test_low_value_contextual_change_does_not_create_proposal(client):
    project_id, snapshot = prepare_snapshot(client)
    db = client.app.state.db
    now = utc_now()
    db.execute(
        """
        INSERT INTO project_claims(
            id,project_id,claim_type,statement,provenance,verification_status,
            criticality,scope_note,status,created_at,updated_at
        ) VALUES ('claim_low',?,'behavior','低关键上下文','model_hypothesis','limited_support','low','','active',?,?)
        """,
        (project_id, now, now),
    )
    result = client.app.state.impact.resolve_claim_change(
        project_id=project_id,
        claim_id="claim_low",
        before_status="unverified",
        after_status="limited_support",
        trigger_source_id=None,
        actor="test",
    )
    assert result["material"] is False
    assert result["proposal_id"] is None
    assert db.fetch_one("SELECT id FROM change_proposals WHERE project_id=?", (project_id,)) is None
    assert client.app.state.artifact_health.get("project_snapshot", snapshot["id"])["health_status"] == "current"


def test_critical_assumption_conflict_creates_one_open_proposal(client):
    project_id, snapshot = prepare_snapshot(client)
    db = client.app.state.db
    claim = db.fetch_one(
        """
        SELECT pc.* FROM project_claims pc
        JOIN decision_claim_links dcl ON dcl.claim_id=pc.id
        WHERE pc.project_id=? AND dcl.role='assumption' LIMIT 1
        """,
        (project_id,),
    )
    set_claim_status(db, claim["id"], "conflict")
    first = client.app.state.impact.resolve_claim_change(
        project_id=project_id, claim_id=claim["id"], before_status="unverified",
        after_status="conflict", trigger_source_id=None, actor="test",
    )
    second = client.app.state.impact.resolve_claim_change(
        project_id=project_id, claim_id=claim["id"], before_status="unverified",
        after_status="conflict", trigger_source_id=None, actor="test",
    )
    assert first["material"] is True
    assert first["proposal_id"] == second["proposal_id"]
    rows = db.fetch_all("SELECT * FROM change_proposals WHERE project_id=? AND status='open'", (project_id,))
    assert len(rows) == 1
    assert client.app.state.artifact_health.get("project_snapshot", snapshot["id"])["health_status"] == "needs_review"


def test_accept_requires_human_confirmation_and_creates_snapshot_v2_without_mutating_v1(client):
    project_id, snapshot_v1 = prepare_snapshot(client)
    db = client.app.state.db
    claim = db.fetch_one(
        """
        SELECT pc.* FROM project_claims pc JOIN decision_claim_links dcl ON dcl.claim_id=pc.id
        WHERE pc.project_id=? AND dcl.role='assumption' LIMIT 1
        """,
        (project_id,),
    )
    set_claim_status(db, claim["id"], "conflict")
    proposal_id = client.app.state.impact.resolve_claim_change(
        project_id=project_id, claim_id=claim["id"], before_status="unverified",
        after_status="conflict", trigger_source_id=None, actor="test",
    )["proposal_id"]
    v1_before = client.get(f"/api/project-snapshots/{snapshot_v1['id']}").json()

    denied = client.post(
        f"/api/change-proposals/{proposal_id}/accept",
        json={"human_confirmed": False, "note": ""},
    )
    assert denied.status_code == 403

    accepted = client.post(
        f"/api/change-proposals/{proposal_id}/accept",
        json={"human_confirmed": True, "note": "接受证据变化"},
    )
    assert accepted.status_code == 200, accepted.text
    v2 = accepted.json()["snapshot"]
    assert v2["version"] == 2
    assert v2["supersedes_snapshot_id"] == snapshot_v1["id"]
    assert v2["snapshot_origin"] == "change_proposal"
    assert client.app.state.db.fetch_one("SELECT current_snapshot_id FROM projects WHERE id=?", (project_id,))["current_snapshot_id"] == v2["id"]

    v1_after = client.get(f"/api/project-snapshots/{snapshot_v1['id']}").json()
    assert v1_after["content_sha256"] == v1_before["content_sha256"]
    assert {key: v1_after[key] for key in client.app.state.snapshots.JSON_FIELDS} == {key: v1_before[key] for key in client.app.state.snapshots.JSON_FIELDS}
    assert client.app.state.artifact_health.get("project_snapshot", snapshot_v1["id"])["health_status"] == "superseded"
    assert client.app.state.artifact_health.get("project_snapshot", v2["id"])["health_status"] == "current"


def test_reject_and_defer_leave_current_snapshot_pointer_unchanged(client):
    project_id, snapshot = prepare_snapshot(client)
    service = client.app.state.change_proposals
    first = service.create(
        project_id=project_id, from_snapshot_id=snapshot["id"], proposal_type="manual_test",
        summary="test", reason="test", affected_claim_ids=[], affected_decision_ids=[],
        suggested_changes={}, trigger_source_id=None,
    )
    second = service.create(
        project_id=project_id, from_snapshot_id=snapshot["id"], proposal_type="manual_test_2",
        summary="test", reason="test", affected_claim_ids=[], affected_decision_ids=[],
        suggested_changes={}, trigger_source_id=None,
    )
    rejected = client.post(f"/api/change-proposals/{first['id']}/reject", json={"human_confirmed": True, "note": "不改"})
    deferred = client.post(f"/api/change-proposals/{second['id']}/defer", json={"human_confirmed": True, "note": "以后再看"})
    assert rejected.status_code == deferred.status_code == 200
    assert client.app.state.db.fetch_one("SELECT current_snapshot_id FROM projects WHERE id=?", (project_id,))["current_snapshot_id"] == snapshot["id"]


def test_accept_stale_from_snapshot_returns_409(client):
    project_id, snapshot = prepare_snapshot(client)
    service = client.app.state.change_proposals
    stale = service.create(
        project_id=project_id, from_snapshot_id=snapshot["id"], proposal_type="stale_test",
        summary="stale", reason="test", affected_claim_ids=[], affected_decision_ids=[],
        suggested_changes={}, trigger_source_id=None,
    )
    current_first = service.create(
        project_id=project_id, from_snapshot_id=snapshot["id"], proposal_type="advance_test",
        summary="advance", reason="test", affected_claim_ids=[], affected_decision_ids=[],
        suggested_changes={}, trigger_source_id=None,
    )
    advanced = client.post(
        f"/api/change-proposals/{current_first['id']}/accept",
        json={"human_confirmed": True, "note": "advance"},
    )
    assert advanced.status_code == 200
    response = client.post(
        f"/api/change-proposals/{stale['id']}/accept",
        json={"human_confirmed": True, "note": "stale"},
    )
    assert response.status_code == 409
    assert "STALE_CHANGE_PROPOSAL" in response.json()["detail"]


def test_derived_ux_state_uses_snapshot_health_and_open_material_proposals(client):
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    bare_project = quick.json()["project_id"]
    assert client.app.state.snapshots.derive_project_state(bare_project) == "exploring"

    project_id, snapshot = prepare_snapshot(client)
    assert client.app.state.snapshots.derive_project_state(project_id) == "executable"
    proposal = client.app.state.change_proposals.create(
        project_id=project_id, from_snapshot_id=snapshot["id"], proposal_type="material_test",
        summary="material", reason="material", affected_claim_ids=[], affected_decision_ids=[],
        suggested_changes={}, trigger_source_id=None,
    )
    assert proposal["status"] == "open"
    assert client.app.state.snapshots.derive_project_state(project_id) == "reconfirm_required"


def test_direct_canvas_edit_creates_reconciliation_proposal_and_marks_snapshot_needs_review(client):
    project_id, snapshot = prepare_snapshot(client)
    response = client.put(
        f"/api/projects/{project_id}/canvas",
        json={
            "problem": "用户手动修改后的问题",
            "target_users": "新的目标用户描述",
            "goals": ["验证新目标"],
            "non_goals": ["不做复杂预测"],
            "success_metrics": ["完成 3 个验收案例"],
            "constraints": ["两周内完成"],
        },
    )
    assert response.status_code == 200, response.text
    health = client.app.state.artifact_health.get("project_snapshot", snapshot["id"])
    assert health["health_status"] == "needs_review"
    proposals = client.get(f"/api/projects/{project_id}/change-proposals")
    assert proposals.status_code == 200
    open_reconciliation = [p for p in proposals.json() if p["status"] == "open" and p["proposal_type"] == "snapshot_canvas_reconciliation"]
    assert len(open_reconciliation) == 1
    suggested = open_reconciliation[0]["suggested_changes"]
    assert suggested["snapshot_patch"]["problem"]["statement"] == "用户手动修改后的问题"


def test_accept_canvas_reconciliation_supersedes_changed_project_claims(client):
    project_id, snapshot_v1 = prepare_snapshot(client)
    db = client.app.state.db
    old_problem = db.fetch_one(
        "SELECT * FROM project_claims WHERE project_id=? AND claim_type='user_problem' AND status='active'",
        (project_id,),
    )
    response = client.put(
        f"/api/projects/{project_id}/canvas",
        json={
            "problem": "新的经用户修改的问题定义",
            "target_users": "新的目标用户描述",
            "goals": ["验证新目标"],
            "non_goals": ["不做复杂预测"],
            "success_metrics": ["完成 3 个验收案例"],
            "constraints": ["两周内完成"],
        },
    )
    assert response.status_code == 200
    proposal = next(
        item for item in client.get(f"/api/projects/{project_id}/change-proposals").json()
        if item["proposal_type"] == "snapshot_canvas_reconciliation" and item["status"] == "open"
    )
    accepted = client.post(
        f"/api/change-proposals/{proposal['id']}/accept",
        json={"human_confirmed": True, "note": "接受 Canvas 调整"},
    )
    assert accepted.status_code == 200, accepted.text
    snapshot_v2 = accepted.json()["snapshot"]
    assert snapshot_v2["problem"]["statement"] == "新的经用户修改的问题定义"

    old_after = db.fetch_one("SELECT * FROM project_claims WHERE id=?", (old_problem["id"],))
    assert old_after["status"] == "superseded"
    new_problem = db.fetch_one(
        "SELECT * FROM project_claims WHERE project_id=? AND claim_type='user_problem' AND status='active'",
        (project_id,),
    )
    assert new_problem["statement"] == "新的经用户修改的问题定义"
    assert new_problem["provenance"] == "user_input"
    assert new_problem["verification_status"] == "unverified"
    assert new_problem["supersedes_claim_id"] == old_problem["id"]
    assert db.fetch_one(
        "SELECT 1 FROM snapshot_claim_links WHERE snapshot_id=? AND claim_id=?",
        (snapshot_v2["id"], new_problem["id"]),
    ) is not None
    assert db.fetch_one(
        "SELECT 1 FROM snapshot_claim_links WHERE snapshot_id=? AND claim_id=?",
        (snapshot_v2["id"], old_problem["id"]),
    ) is None
