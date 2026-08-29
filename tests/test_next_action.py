import json

import pytest


EXPECTED_KEYS = {"code", "title", "reason", "view", "control_id"}


def _quick_project(client) -> str:
    response = client.post(
        "/api/projects/quick-start",
        json={
            "idea": "帮助小型便利店减少缺货",
            "target_user": None,
            "resources": [],
            "priority": "fast_mvp",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _confirm_brief(client, project_id: str) -> None:
    response = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认系统理解"},
    )
    assert response.status_code == 200, response.text


def _generate_solutions(client, project_id: str) -> list[dict]:
    response = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert response.status_code == 201, response.text
    return response.json()["candidates"]


def _select_solution(client, project_id: str, candidates: list[dict]) -> None:
    selected = next(candidate for candidate in candidates if candidate["mechanism"] == "rule_based")
    response = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": "先验证低成本规则方案",
            "human_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text


def _mark_claims_supported(client, project_id: str) -> None:
    client.app.state.db.execute(
        "UPDATE project_claims SET verification_status='supported' WHERE project_id=? AND status='active'",
        (project_id,),
    )


def _generate_valid_document(
    client, project_id: str, doc_type: str, *, key_prefix: str = "guidance"
) -> str:
    response = client.post(
        f"/api/projects/{project_id}/documents/generate",
        json={"doc_type": doc_type, "idempotency_key": f"{key_prefix}-{doc_type}"},
    )
    assert response.status_code == 200, response.text
    version_id = response.json()["version_id"]
    client.app.state.db.execute(
        "UPDATE document_versions SET validation_status='passed' WHERE id=?", (version_id,)
    )
    return version_id


def _confirm_document(client, version_id: str) -> None:
    response = client.post(
        f"/api/document-versions/{version_id}/confirm",
        json={"actor": "pm", "note": "确认当前版本", "human_confirmed": True},
    )
    assert response.status_code == 200, response.text


def _action(client, project_id: str) -> dict:
    response = client.get(f"/api/projects/{project_id}/next-action")
    assert response.status_code == 200, response.text
    action = response.json()
    assert set(action) == EXPECTED_KEYS
    return action


def _assert_action(client, project_id: str, expected: tuple[str, str, str]) -> None:
    action = _action(client, project_id)
    assert (action["code"], action["view"], action["control_id"]) == expected


def _ready_project(client, *, key_prefix: str = "guidance") -> str:
    project_id = _quick_project(client)
    _confirm_brief(client, project_id)
    _select_solution(client, project_id, _generate_solutions(client, project_id))
    _mark_claims_supported(client, project_id)
    prd_version = _generate_valid_document(client, project_id, "prd", key_prefix=key_prefix)
    techdoc_version = _generate_valid_document(client, project_id, "techdoc", key_prefix=key_prefix)
    _confirm_document(client, prd_version)
    _confirm_document(client, techdoc_version)
    exported = client.post(
        f"/api/projects/{project_id}/handoff/export", json={"target_client": "codex"}
    )
    assert exported.status_code == 200, exported.text
    return project_id


def _accept_new_snapshot(client, project_id: str) -> dict:
    current = client.get(f"/api/projects/{project_id}/snapshot").json()
    proposal = client.app.state.change_proposals.create(
        project_id=project_id,
        from_snapshot_id=current["id"],
        proposal_type="guidance_regression",
        summary="指导状态机回归",
        reason="创建新的确认 Snapshot",
        affected_claim_ids=[],
        affected_decision_ids=[],
        suggested_changes={},
        trigger_source_id=None,
    )
    accepted = client.post(
        f"/api/change-proposals/{proposal['id']}/accept",
        json={"human_confirmed": True, "note": "确认新的 Snapshot"},
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()["snapshot"]


def _create_open_snapshot_proposal(client, project_id: str, *, summary: str) -> dict:
    snapshot = client.get(f"/api/projects/{project_id}/snapshot").json()
    return client.app.state.change_proposals.create(
        project_id=project_id,
        from_snapshot_id=snapshot["id"],
        proposal_type="guidance_regression",
        summary=summary,
        reason="验证确定性的 Snapshot 指引目标",
        affected_claim_ids=[],
        affected_decision_ids=[],
        suggested_changes={},
        trigger_source_id=None,
    )


def test_project_next_action_follows_persisted_priority_order(client):
    """Every persisted workflow state maps to one stable deep-link target."""
    project_id = _quick_project(client)
    candidates: list[dict] = []
    versions: dict[str, str] = {}

    def generate_solutions() -> None:
        candidates.extend(_generate_solutions(client, project_id))

    def select_solution() -> None:
        _select_solution(client, project_id, candidates)

    def generate_prd() -> None:
        versions["prd"] = _generate_valid_document(client, project_id, "prd")

    def generate_techdoc() -> None:
        versions["techdoc"] = _generate_valid_document(client, project_id, "techdoc")

    def confirm_documents() -> None:
        _confirm_document(client, versions["prd"])
        _confirm_document(client, versions["techdoc"])

    def export_handoff() -> None:
        response = client.post(
            f"/api/projects/{project_id}/handoff/export", json={"target_client": "codex"}
        )
        assert response.status_code == 200, response.text

    state_table = [
        ("inferred brief", lambda: None, ("confirm_idea_brief", "solutions", "idea-brief-confirm")),
        ("confirmed brief", lambda: _confirm_brief(client, project_id), ("generate_solutions", "solutions", "generate-solutions-button")),
        ("generated candidates", generate_solutions, ("select_solution", "solutions", "solutions-content")),
        ("selected solution", select_solution, ("verify_project_claim", "evidence", "evidence-claims-panel")),
        ("verified claims", lambda: _mark_claims_supported(client, project_id), ("generate_or_update_prd", "documents", "documents-content")),
        ("valid PRD", generate_prd, ("generate_or_update_techdoc", "documents", "documents-content")),
        ("valid document pair", generate_techdoc, ("confirm_document_versions", "documents", "documents-content")),
        ("confirmed documents", confirm_documents, ("export_handoff", "handoff", "export-handoff-button")),
        ("matching handoff", export_handoff, ("ready", "handoff", "handoff-content")),
    ]
    for _state, advance, expected in state_table:
        advance()
        _assert_action(client, project_id, expected)


@pytest.mark.parametrize(
    ("tour_completed", "expected_code"),
    [(False, "start_example_tour"), (True, "create_new_idea")],
)
def test_home_next_action_uses_tour_completion_only_after_no_incomplete_project(
    client, tour_completed: bool, expected_code: str
):
    """A ready project must not hide the example-tour/new-Idea fallback choice."""
    project_id = _quick_project(client)
    _confirm_brief(client, project_id)
    candidates = _generate_solutions(client, project_id)
    _select_solution(client, project_id, candidates)
    _mark_claims_supported(client, project_id)
    prd_version = _generate_valid_document(client, project_id, "prd")
    techdoc_version = _generate_valid_document(client, project_id, "techdoc")
    _confirm_document(client, prd_version)
    _confirm_document(client, techdoc_version)
    exported = client.post(
        f"/api/projects/{project_id}/handoff/export", json={"target_client": "codex"}
    )
    assert exported.status_code == 200, exported.text
    client.app.state.db.execute("UPDATE projects SET status='trashed' WHERE id='project_insightforge_demo'")

    if tour_completed:
        # The feedback-complete schema now owns this table; this test only seeds completed progress.
        client.app.state.db.execute(
            "INSERT INTO project_tour_progress VALUES (?, ?, ?, ?, NULL, ?)",
            (
                project_id,
                "complete-example-v1",
                "handoff",
                json.dumps(["idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"]),
                "2026-08-28T00:00:00+00:00",
            ),
        )

    response = client.get("/api/home/next-action")
    assert response.status_code == 200, response.text
    action = response.json()
    assert set(action) == EXPECTED_KEYS
    assert action["code"] == expected_code


def test_home_next_action_continues_most_recent_incomplete_active_project(client):
    """The home card must prefer an unfinished active project over the example fallback."""
    older_id = _quick_project(client)
    newer_id = _quick_project(client)
    client.app.state.db.execute(
        "UPDATE projects SET updated_at='2026-08-28T00:00:00+00:00' WHERE id=?", (older_id,)
    )
    client.app.state.db.execute(
        "UPDATE projects SET updated_at='2026-08-28T00:00:01+00:00' WHERE id=?", (newer_id,)
    )

    response = client.get("/api/home/next-action")
    assert response.status_code == 200, response.text
    action = response.json()
    assert set(action) == EXPECTED_KEYS
    assert action["code"] == "continue_project"
    assert action["view"] == f"project:{newer_id}"
    assert action["control_id"] == f"project-select:{newer_id}"


def test_project_next_action_uses_existing_claim_priority_scoring(client):
    """A feasibility claim's documented priority bonus must not be lost in guidance."""
    project_id = _quick_project(client)
    _confirm_brief(client, project_id)
    _select_solution(client, project_id, _generate_solutions(client, project_id))
    claims = client.get(f"/api/projects/{project_id}/claims").json()
    problem_claim = next(item for item in claims if item["claim_type"] == "user_problem")
    feasibility_claim = next(item for item in claims if item["claim_type"] == "feasibility")
    client.app.state.db.execute(
        "UPDATE project_claims SET verification_status='supported' WHERE project_id=?", (project_id,)
    )
    client.app.state.db.execute(
        "UPDATE project_claims SET criticality='critical', verification_status='unverified' WHERE id=?",
        (problem_claim["id"],),
    )
    client.app.state.db.execute(
        "UPDATE project_claims SET criticality='high', verification_status='unverified' WHERE id=?",
        (feasibility_claim["id"],),
    )

    assert feasibility_claim["statement"] in _action(client, project_id)["reason"]


def test_refined_and_reconfirmed_brief_cannot_reuse_stale_solution_candidates(client):
    """A solution run for a superseded IdeaBrief must not become selectable."""
    project_id = _quick_project(client)
    _confirm_brief(client, project_id)
    _generate_solutions(client, project_id)
    refined = client.post(
        f"/api/projects/{project_id}/idea-brief/refine",
        json={"problem": "更新后的问题定义"},
    )
    assert refined.status_code == 200, refined.text
    _confirm_brief(client, project_id)

    _assert_action(client, project_id, ("generate_solutions", "solutions", "generate-solutions-button"))


@pytest.mark.parametrize("health_state", ["missing", "stale"])
def test_document_health_must_exist_and_be_current_before_guidance_advances(client, health_state: str):
    """Missing or stale health cannot be treated as a confirmed PRD."""
    project_id = _ready_project(client, key_prefix=f"health-{health_state}")
    prd = client.app.state.db.fetch_one(
        "SELECT id FROM document_versions WHERE project_id=? AND doc_type='prd' ORDER BY version DESC LIMIT 1",
        (project_id,),
    )
    if health_state == "missing":
        client.app.state.db.execute(
            "DELETE FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
            (prd["id"],),
        )
    else:
        client.app.state.db.execute(
            """
            UPDATE artifact_health SET health_status='stale_evidence'
            WHERE artifact_type='document_version' AND artifact_id=?
            """,
            (prd["id"],),
        )

    _assert_action(client, project_id, ("generate_or_update_prd", "documents", "documents-content"))


def test_canvas_edit_routes_to_snapshot_review_instead_of_impossible_document_confirmation(client):
    """A Canvas edit invalidates the accepted Snapshot, not merely its documents."""
    project_id = _ready_project(client, key_prefix="canvas")
    edited = client.put(
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
    assert edited.status_code == 200, edited.text
    proposal = next(
        item
        for item in client.get(f"/api/projects/{project_id}/change-proposals").json()
        if item["status"] == "open"
    )

    _assert_action(
        client,
        project_id,
        ("review_project_snapshot", "evidence", f"proposal-actions:{proposal['id']}"),
    )


def test_snapshot_health_without_open_proposal_routes_to_reconfirmation_that_repairs_health(client):
    """A health-only Snapshot block must expose a real, idempotent recovery transition."""
    project_id = _ready_project(client, key_prefix="snapshot-health-only")
    snapshot = client.get(f"/api/projects/{project_id}/snapshot").json()
    client.app.state.db.execute(
        "UPDATE artifact_health SET health_status='stale_evidence' "
        "WHERE artifact_type='project_snapshot' AND artifact_id=?",
        (snapshot["id"],),
    )

    _assert_action(
        client,
        project_id,
        ("reconfirm_project_snapshot", "snapshot", "snapshot-health-reconfirm"),
    )
    repaired = client.post(
        f"/api/projects/{project_id}/snapshot/reconfirm",
        json={"human_confirmed": True, "note": "已检查当前 Snapshot 仍可执行"},
    )
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["health"]["health_status"] == "current"
    assert client.app.state.db.fetch_one(
        "SELECT health_status FROM artifact_health WHERE artifact_type='project_snapshot' AND artifact_id=?",
        (snapshot["id"],),
    )["health_status"] == "current"
    repeated = client.post(
        f"/api/projects/{project_id}/snapshot/reconfirm",
        json={"human_confirmed": True, "note": "重复确认不应改变状态"},
    )
    assert repeated.status_code == 200, repeated.text
    _assert_action(client, project_id, ("ready", "handoff", "handoff-content"))


def test_snapshot_review_selects_newest_current_open_proposal_for_exact_focus(client):
    """Two current proposals must not share a focus target or leave selection to DOM order."""
    project_id = _ready_project(client, key_prefix="proposal-priority")
    older = _create_open_snapshot_proposal(client, project_id, summary="较早的建议")
    newer = _create_open_snapshot_proposal(client, project_id, summary="较新的建议")
    client.app.state.db.execute(
        "UPDATE change_proposals SET created_at='2026-08-28T00:00:00+00:00' WHERE id=?",
        (older["id"],),
    )
    client.app.state.db.execute(
        "UPDATE change_proposals SET created_at='2026-08-28T00:00:01+00:00' WHERE id=?",
        (newer["id"],),
    )

    _assert_action(
        client,
        project_id,
        ("review_project_snapshot", "evidence", f"proposal-actions:{newer['id']}"),
    )


def test_completed_handoff_must_match_current_snapshot_and_confirmed_document_versions(client):
    """An export becomes stale when a newer Snapshot and document pair are accepted."""
    project_id = _ready_project(client, key_prefix="handoff-v1")
    _assert_action(client, project_id, ("ready", "handoff", "handoff-content"))

    _accept_new_snapshot(client, project_id)
    _generate_valid_document(client, project_id, "prd", key_prefix="handoff-v2")
    _generate_valid_document(client, project_id, "techdoc", key_prefix="handoff-v2")
    for doc_type in ("prd", "techdoc"):
        version = client.app.state.db.fetch_one(
            "SELECT id FROM document_versions WHERE project_id=? AND doc_type=? ORDER BY version DESC LIMIT 1",
            (project_id, doc_type),
        )
        _confirm_document(client, version["id"])

    _assert_action(client, project_id, ("export_handoff", "handoff", "export-handoff-button"))
    exported = client.post(
        f"/api/projects/{project_id}/handoff/export", json={"target_client": "codex"}
    )
    assert exported.status_code == 200, exported.text
    _assert_action(client, project_id, ("ready", "handoff", "handoff-content"))


def test_home_continue_action_encodes_exact_project_id_when_titles_are_duplicated(client):
    """The home deep link must select the most recent project without relying on its title."""
    older_id = _quick_project(client)
    newer_id = _quick_project(client)
    client.app.state.db.execute("UPDATE projects SET title='同名项目' WHERE id IN (?, ?)", (older_id, newer_id))
    client.app.state.db.execute(
        "UPDATE projects SET updated_at='2099-01-01T00:00:00+00:00' WHERE id=?", (older_id,)
    )
    client.app.state.db.execute(
        "UPDATE projects SET updated_at='2099-01-01T00:00:01+00:00' WHERE id=?", (newer_id,)
    )

    response = client.get("/api/home/next-action")
    assert response.status_code == 200, response.text
    action = response.json()
    assert set(action) == EXPECTED_KEYS
    assert (action["code"], action["view"], action["control_id"]) == (
        "continue_project",
        f"project:{newer_id}",
        f"project-select:{newer_id}",
    )
