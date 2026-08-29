from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.services.example_projects import ExampleProjectSeeder


TOUR_STEPS = ["idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"]


@pytest.fixture()
def example_client(tmp_path: Path):
    db = Database(tmp_path / "examples.sqlite3")
    db.init_schema()
    db.seed_demo_data()
    ExampleProjectSeeder(db).seed()
    app = create_app(database_path=db.path, seed=False)
    with TestClient(app) as client:
        yield client


def test_complete_example_walkthrough_persists_skip_and_restart(example_client):
    examples = example_client.get("/api/examples").json()
    assert examples
    copied = example_client.post(
        f"/api/examples/{examples[0]['id']}/copies", headers={"X-Actor": "tester"}
    )
    assert copied.status_code == 201, copied.text
    project_id = copied.json()["id"]

    started = example_client.post(f"/api/projects/{project_id}/walkthrough/start")
    assert started.status_code == 200, started.text
    assert started.json()["current_step"] == "idea"
    assert started.json()["completed_steps"] == []

    for step in TOUR_STEPS:
        advanced = example_client.post(
            f"/api/projects/{project_id}/walkthrough/advance", json={"step": step}
        )
        assert advanced.status_code == 200, advanced.text
    persisted = example_client.get(f"/api/projects/{project_id}/walkthrough")
    assert persisted.status_code == 200
    assert persisted.json()["current_step"] == "complete"
    assert persisted.json()["completed_steps"] == TOUR_STEPS

    restarted = example_client.post(f"/api/projects/{project_id}/walkthrough/restart")
    assert restarted.status_code == 200
    assert restarted.json()["current_step"] == "idea"
    assert restarted.json()["completed_steps"] == []

    skipped = example_client.post(f"/api/projects/{project_id}/walkthrough/skip")
    assert skipped.status_code == 200
    assert skipped.json()["current_step"] == "skipped"
    assert skipped.json()["dismissed_at"]


def test_history_center_supports_search_filter_sort_pagination_copy_and_trash(client):
    created = []
    for i in range(13):
        response = client.post(
            "/api/projects", json={"title": f"History Project {i:02d}", "summary": f"summary {i:02d}"}
        )
        assert response.status_code == 201
        created.append(response.json())

    page = client.get(
        "/api/projects/history",
        params={"q": "History Project", "status": "active", "sort": "title", "order": "asc", "page": 2, "page_size": 5},
    )
    assert page.status_code == 200, page.text
    payload = page.json()
    assert payload["total"] == 13
    assert payload["page"] == 2
    assert payload["page_size"] == 5
    assert [item["title"] for item in payload["items"]] == [
        "History Project 05", "History Project 06", "History Project 07", "History Project 08", "History Project 09"
    ]

    parent = created[-1]
    copied = client.post(f"/api/projects/{parent['id']}/copy", headers={"X-Actor": "tester"})
    assert copied.status_code == 201, copied.text
    child = copied.json()
    assert child["id"] != parent["id"]
    assert child["parent_project_id"] == parent["id"]
    assert child["relation_type"] == "project_copy"

    trashed = client.post(f"/api/projects/{child['id']}/trash")
    assert trashed.status_code == 200
    trash_page = client.get(
        "/api/projects/history",
        params={"status": "trashed", "page": 1, "page_size": 20},
    )
    assert trash_page.status_code == 200
    assert child["id"] in {item["id"] for item in trash_page.json()["items"]}


def test_document_workspace_autosaves_draft_commits_diff_restores_and_exports_selected_version(client):
    generated = client.post(
        "/api/projects/project_insightforge_demo/generate",
        json={"doc_type": "prd", "idempotency_key": "feedback-doc-v1"},
    )
    assert generated.status_code == 200, generated.text
    v1_id = generated.json()["version_id"]
    v1 = client.get(f"/api/documents/{v1_id}").json()
    edited_content = v1["content"] + "\n\n## 手工补充\n这是在线编辑后的草稿。\n"

    autosaved = client.put(
        "/api/projects/project_insightforge_demo/documents/prd/draft",
        json={"base_version_id": v1_id, "content": edited_content},
    )
    assert autosaved.status_code == 200, autosaved.text
    assert autosaved.json()["content"] == edited_content

    draft = client.get("/api/projects/project_insightforge_demo/documents/prd/draft")
    assert draft.status_code == 200
    assert draft.json()["base_version_id"] == v1_id

    committed = client.post(
        "/api/projects/project_insightforge_demo/documents/prd/draft/commit",
        json={"actor": "tester", "note": "manual edit"},
    )
    assert committed.status_code == 201, committed.text
    v2 = committed.json()
    assert v2["version"] == v1["version"] + 1
    assert v2["content"] == edited_content
    assert v2["validation_status"] == "not_run"

    diff = client.get(
        "/api/documents/diff", params={"from_version_id": v1_id, "to_version_id": v2["id"]}
    )
    assert diff.status_code == 200, diff.text
    assert "手工补充" in diff.json()["unified_diff"]

    restored = client.post(
        f"/api/documents/{v1_id}/restore-as-new",
        json={"actor": "tester", "note": "restore old content"},
    )
    assert restored.status_code == 201, restored.text
    v3 = restored.json()
    assert v3["version"] == v2["version"] + 1
    assert v3["content"] == v1["content"]
    assert v3["restored_from_version_id"] == v1_id

    versions = client.get("/api/projects/project_insightforge_demo/documents/prd/versions")
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()][:3] == [v3["version"], v2["version"], v1["version"]]

    exported_v1 = client.get(f"/api/documents/{v1_id}/export?format=md")
    assert exported_v1.status_code == 200
    assert v1["content"] in exported_v1.text
    assert "手工补充" not in exported_v1.text


def test_project_model_override_can_be_read_and_cleared_without_exposing_secret(client):
    # Reading the current override must work even when there is no profile configured.
    initial = client.get("/api/projects/project_insightforge_demo/model-profile")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {"project_id": "project_insightforge_demo", "profile_id": None}

    cleared = client.put(
        "/api/projects/project_insightforge_demo/model-profile", json={"profile_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["profile_id"] is None


def test_delivery_scripts_exist_and_are_fail_closed():
    deploy = Path("scripts/deploy_windows.ps1")
    live = Path("scripts/verify_live_providers.py")
    assert deploy.is_file()
    assert live.is_file()
    deploy_text = deploy.read_text(encoding="utf-8")
    assert "E:\\AI_Projects\\InsightForge" in deploy_text
    assert "staging" in deploy_text.casefold()
    assert "backup" in deploy_text.casefold()
    assert "rollback" in deploy_text.casefold()
    live_text = live.read_text(encoding="utf-8")
    for provider in ("qwen", "kimi", "deepseek", "glm"):
        assert provider in live_text.casefold()
    assert "api_key" not in live_text.casefold() or "print(api_key" not in live_text.casefold()


def test_central_trash_can_purge_a_copied_example_with_feedback_completion_state(example_client):
    """Permanent deletion must remove the whole copied project graph, not leave new 3.0/tour/editor rows."""
    example_id = example_client.get("/api/examples").json()[0]["id"]
    copied = example_client.post(f"/api/examples/{example_id}/copies", headers={"X-Actor": "tester"})
    assert copied.status_code == 201, copied.text
    project_id = copied.json()["id"]

    tour = example_client.post(f"/api/projects/{project_id}/walkthrough/start")
    assert tour.status_code == 200, tour.text

    versions = example_client.get(f"/api/projects/{project_id}/documents/prd/versions")
    assert versions.status_code == 200 and versions.json(), versions.text
    base = versions.json()[0]
    draft = example_client.put(
        f"/api/projects/{project_id}/documents/prd/draft",
        json={"base_version_id": base["id"], "content": base["content"] + "\n\nDraft before purge."},
    )
    assert draft.status_code == 200, draft.text

    trashed = example_client.post(f"/api/projects/{project_id}/trash")
    assert trashed.status_code == 200, trashed.text
    purged = example_client.delete(f"/api/projects/{project_id}", headers={"X-Actor": "tester"})
    assert purged.status_code == 200, purged.text
    assert purged.json() == {"id": project_id, "status": "permanently_deleted"}

    db = example_client.app.state.db
    assert db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)) is None
    assert db.fetch_one("SELECT project_id FROM project_tour_progress WHERE project_id=?", (project_id,)) is None
    assert db.fetch_one("SELECT project_id FROM document_edit_drafts WHERE project_id=?", (project_id,)) is None
    assert db.fetch_one("SELECT child_project_id FROM project_relations WHERE child_project_id=?", (project_id,)) is None


def test_live_provider_verifier_requires_explicit_paid_call_confirmation():
    """Local live checks must not create network/API usage without an explicit operator gate."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/verify_live_providers.py"],
        cwd=root,
        env={**__import__("os").environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    combined = (result.stdout + result.stderr).casefold()
    assert "confirm-live-calls" in combined
    assert "qwen" not in combined or "pass" not in combined


def test_document_draft_commit_rejects_a_stale_selected_base_version(client):
    """A hidden autosaved draft must not be committed while the UI is showing another base version."""
    generated = client.post(
        "/api/projects/project_insightforge_demo/generate",
        json={"doc_type": "prd", "idempotency_key": "feedback-stale-draft-v1"},
    )
    assert generated.status_code == 200, generated.text
    v1_id = generated.json()["version_id"]
    v1 = client.get(f"/api/documents/{v1_id}").json()

    saved = client.put(
        "/api/projects/project_insightforge_demo/documents/prd/draft",
        json={"base_version_id": v1_id, "content": v1["content"] + "\n\nDraft A"},
    )
    assert saved.status_code == 200, saved.text

    restored = client.post(
        f"/api/documents/{v1_id}/restore-as-new",
        json={"actor": "tester", "note": "create another visible base"},
    )
    assert restored.status_code == 201, restored.text
    visible_version_id = restored.json()["id"]

    commit = client.post(
        "/api/projects/project_insightforge_demo/documents/prd/draft/commit",
        json={
            "actor": "tester",
            "note": "must not commit hidden draft",
            "expected_base_version_id": visible_version_id,
        },
    )
    assert commit.status_code == 409, commit.text
    assert "draft base" in commit.json()["detail"].casefold()

    draft = client.get("/api/projects/project_insightforge_demo/documents/prd/draft")
    assert draft.status_code == 200
    assert draft.json()["base_version_id"] == v1_id
