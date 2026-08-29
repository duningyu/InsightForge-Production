import pytest

from app.services.example_projects import ExampleProjectSeeder
from app.services.projects import ProjectService


def test_project_delete_moves_it_to_trash_and_restore_returns_it_to_catalog(db):
    projects = ProjectService(db)
    created = projects.create_project(title="待删除项目", summary="用于验证回收箱。", actor="tester")

    trashed = projects.move_to_trash(created["id"], actor="tester")
    assert trashed["status"] == "trashed"
    assert created["id"] not in {item["id"] for item in projects.list_projects()}
    assert created["id"] in {item["id"] for item in projects.list_trashed_projects()}

    restored = projects.restore_from_trash(created["id"], actor="tester")
    assert restored["status"] == "active"
    assert created["id"] in {item["id"] for item in projects.list_projects()}


def test_permanent_delete_requires_trash_and_removes_project_data(db):
    projects = ProjectService(db)
    created = projects.create_project(title="永久删除项目", summary="用于验证永久删除。", actor="tester")

    with pytest.raises(ValueError, match="trash"):
        projects.purge_from_trash(created["id"], actor="tester")

    projects.move_to_trash(created["id"], actor="tester")
    result = projects.purge_from_trash(created["id"], actor="tester")
    assert result["id"] == created["id"]
    assert db.fetch_one("SELECT id FROM projects WHERE id = ?", (created["id"],)) is None


def test_example_seeder_creates_two_complete_browsable_examples(db):
    ExampleProjectSeeder(db).seed()
    projects = ProjectService(db)
    titles = {item["title"] for item in projects.list_projects()}
    assert {"示例｜便利店智能补货提醒", "示例｜B2B 采购审批助手"} <= titles

    detail = projects.get_project_detail("project_example_inventory_alert")
    assert detail["canvas"] is not None
    assert len(detail["sources"]) >= 2
    assert {item["doc_type"] for item in detail["document_versions"]} == {"prd", "techdoc"}
    assert db.fetch_one(
        "SELECT id FROM document_claims WHERE project_id = ? LIMIT 1",
        ("project_example_inventory_alert",),
    ) is not None


def test_project_lifecycle_api_exposes_trash_restore_and_purge(client):
    created = client.post("/api/projects", json={"title": "API 回收箱", "summary": "验证 API。"}).json()
    project_id = created["id"]

    assert client.post(f"/api/projects/{project_id}/trash").json()["status"] == "trashed"
    assert project_id not in {item["id"] for item in client.get("/api/projects").json()}
    assert project_id in {item["id"] for item in client.get("/api/projects/trash").json()}
    assert client.post(f"/api/projects/{project_id}/restore").json()["status"] == "active"
    assert client.post(f"/api/projects/{project_id}/trash").status_code == 200
    assert client.delete(f"/api/projects/{project_id}").status_code == 200


def test_project_with_model_override_can_be_trashed_and_purged_transactionally(client):
    profile = client.post(
        "/api/settings/model-profiles",
        json={
            "display_name": "Purge-safe profile",
            "provider": "qwen",
            "model_id": "qwen-plus",
        },
    ).json()
    project = client.post(
        "/api/projects",
        json={"title": "Override purge", "summary": "Must not leave an FK row"},
    ).json()
    project_id = project["id"]
    selected = client.put(
        f"/api/projects/{project_id}/model-profile",
        json={"profile_id": profile["id"]},
    )
    assert selected.status_code == 200

    assert client.post(f"/api/projects/{project_id}/trash").status_code == 200
    purged = client.delete(f"/api/projects/{project_id}")

    assert purged.status_code == 200, purged.text
    assert client.app.state.db.fetch_one(
        "SELECT project_id FROM project_model_profiles WHERE project_id = ?",
        (project_id,),
    ) is None
    assert client.app.state.db.fetch_one(
        "SELECT id FROM model_profiles WHERE id = ?", (profile["id"],)
    ) is not None
    with client.app.state.db.connect() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
