from __future__ import annotations

import json
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from dataclasses import replace
import pytest


def create_quick_project(client, idea: str = "帮小型便利店减少缺货") -> str:
    response = client.post(
        "/api/projects/quick-start",
        json={"idea": idea, "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


@pytest.fixture()
def stage_a_quick_start_client(monkeypatch, tmp_path):
    settings = replace(
        Settings.from_env(),
        accounts_enabled=False,
        safe_fixture_mode=True,
        beta_participant_id="railway_stage_a",
    )
    application = create_app(
        database_path=tmp_path / "stage_a_quick_start.sqlite3",
        seed=False,
        settings_override=settings,
    )
    with TestClient(application) as test_client:
        yield test_client


def test_quick_start_creates_project_and_inferred_brief_without_canvas_or_guide(client):
    response = client.post(
        "/api/projects/quick-start",
        json={
            "idea": "帮小型便利店减少缺货",
            "target_user": None,
            "resources": [],
            "priority": "fast_mvp",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["idea_brief"]["confirmation_status"] == "inferred"
    assert body["idea_brief"]["provenance"]["problem"] == "model_hypothesis"
    assert body["clarification_required"] is False
    assert body["runtime_mode"] == "deterministic_demo"
    project_id = body["project_id"]
    assert client.get(f"/api/projects/{project_id}/canvas").status_code == 404
    assert client.app.state.db.fetch_one(
        "SELECT id FROM guided_sessions WHERE project_id = ?", (project_id,)
    ) is None
    assert client.app.state.db.fetch_one(
        "SELECT id FROM project_snapshots WHERE project_id = ?", (project_id,)
    ) is None


def test_quick_start_brief_uses_current_input_instead_of_fixture_context(stage_a_quick_start_client):
    idea = "CLOUD_ACCEPTANCE_UNIQUE_IDEA_20260918"
    target_user = "CLOUD_ACCEPTANCE_UNIQUE_TARGET_20260918"
    response = stage_a_quick_start_client.post(
        "/api/projects/quick-start",
        json={
            "idea": idea,
            "target_user": target_user,
            "resources": [],
            "priority": "fast_mvp",
        },
    )
    assert response.status_code == 201, response.text
    brief = response.json()["idea_brief"]
    assert brief["original_idea"] == idea
    assert brief["target_user"] == target_user
    serialized = json.dumps(brief, ensure_ascii=False)
    for unrelated in ("求职者", "面试", "投递", "便利店", "B2B"):
        assert unrelated not in serialized


def test_quick_start_persists_complete_runtime_trace(client):
    project_id = create_quick_project(client)
    row = client.app.state.db.fetch_one(
        "SELECT payload_json FROM audit_events WHERE entity_type = 'idea_brief' AND entity_id IN "
        "(SELECT id FROM idea_briefs WHERE project_id = ?) ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    assert row is not None
    import json

    payload = json.loads(row["payload_json"])
    for key in (
        "provider", "model", "prompt_version", "schema_version", "interpreter_version",
        "input_sha256", "output_sha256", "latency_ms", "status", "runtime_mode",
    ):
        assert key in payload
    assert payload["status"] == "completed"


def test_confirming_brief_does_not_upgrade_provenance_to_market_evidence(client):
    project_id = create_quick_project(client)
    response = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "理解准确"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmation_status"] == "confirmed"
    assert "model_hypothesis" in body["provenance"].values()


def test_brief_confirmation_requires_explicit_human_gate(client):
    project_id = create_quick_project(client)
    response = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": False, "note": ""},
    )
    assert response.status_code == 403


def test_ambiguous_quick_start_returns_only_one_clarification_question(client):
    response = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮学生选学校", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["clarification_required"] is True
    assert isinstance(body["clarification_question"], str)
    assert body["clarification_question"]


def test_clarification_required_solution_attempt_returns_mapped_user_error(client):
    response = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮学生选学校", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    project_id = response.json()["project_id"]
    blocked = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert blocked.status_code == 409
    assert blocked.json() == {
        "detail": "为了生成更准确的方案，还需要补充一项信息。",
        "code": "IDEA_BRIEF_CLARIFICATION_REQUIRED",
        "action": "open_idea_brief_clarification",
        "clarification_question": response.json()["clarification_question"],
    }


def test_clarification_answer_requires_explicit_confirmation_before_solutions(client):
    response = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮学生选学校", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    project_id = response.json()["project_id"]
    refined = client.post(
        f"/api/projects/{project_id}/idea-brief/refine",
        json={"clarification_answer": "筛选已有论文阅读路径"},
    )
    assert refined.status_code == 200
    assert refined.json()["clarification_required"] is False
    assert refined.json()["confirmation_status"] == "inferred"
    blocked = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "IDEA_BRIEF_NOT_CONFIRMED"


def test_refine_brief_creates_new_version_and_marks_user_patch_provenance(client):
    project_id = create_quick_project(client)
    response = client.post(
        f"/api/projects/{project_id}/idea-brief/refine",
        json={"problem": "店主难以及时判断哪些商品需要补货"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["confirmation_status"] == "inferred"
    assert body["provenance"]["problem"] == "user_input"
    old = client.app.state.db.fetch_one(
        "SELECT confirmation_status FROM idea_briefs WHERE project_id = ? AND version = 1",
        (project_id,),
    )
    assert old["confirmation_status"] == "superseded"


def test_unknown_quick_start_preserves_input_and_returns_local_guidance_recovery(client):
    response = client.post(
        "/api/projects/quick-start",
        json={
            "idea": "做一个完全未知的火星矿业调度产品",
            "target_user": None,
            "resources": [],
            "priority": "fast_mvp",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"error_code", "message", "recovery_actions", "preserved_input"}
    assert body["error_code"] == "LOCAL_GUIDANCE_REQUIRED"
    assert body["preserved_input"]["idea"] == "做一个完全未知的火星矿业调度产品"
    assert "本地引导" in body["message"]
    assert "DETERMINISTIC_DEMO_UNSUPPORTED" not in response.text


def test_hr_resume_screening_idea_generates_domain_specific_project_solutions(client):
    response = client.post(
        "/api/projects/quick-start",
        json={
            "idea": "做一个给HR筛选简历的应用",
            "target_user": "HR",
            "resources": [],
            "priority": "fast_mvp",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["idea_brief"]["target_user"] == "HR"
    assert "简历" in body["idea_brief"]["problem"]

    project_id = body["project_id"]
    confirmed = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "理解准确"},
    )
    assert confirmed.status_code == 200
    generated = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert generated.status_code == 201, generated.text
    candidates = generated.json()["candidates"]
    assert len(candidates) == 3
    assert {item["mechanism"] for item in candidates} == {
        "rule_based",
        "recommendation_based",
        "human_in_the_loop",
    }
    assert all("简历" in "".join([item["title"], item["summary"], *item["inputs"]]) for item in candidates)
