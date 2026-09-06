from fastapi.testclient import TestClient

from app.main import create_app
from test_open_accounts import portal


def _claim(app, client, number):
    invite = app.state.accounts.issue_invite()
    credentials = {
        "invite": invite,
        "username": f"draft-user-{number}",
        "password": "SYNTHETIC-only-passphrase!",
    }
    assert client.post("/api/auth/claim", json=credentials).status_code == 201
    login = {key: credentials[key] for key in ("username", "password")}
    assert client.post("/api/auth/login", json=login).status_code == 200
    return client.get("/api/auth/me").json()["id"]


def test_unified_draft_round_trip_and_revision_conflict(db):
    with TestClient(create_app(database_path=db.path, seed=False)) as client:
        project_id = client.get("/api/projects").json()[0]["id"]

        first = client.put(
            f"/api/projects/{project_id}/drafts/idea/main",
            json={"payload": {"idea": "先写下来的想法"}, "base_revision": None},
        )
        assert first.status_code == 200
        assert first.json()["revision"] == 1

        latest = client.get(f"/api/projects/{project_id}/drafts/idea/main")
        assert latest.status_code == 200
        assert latest.json()["payload"]["idea"] == "先写下来的想法"

        updated = client.put(
            f"/api/projects/{project_id}/drafts/idea/main",
            json={"payload": {"idea": "第一标签页的更新"}, "base_revision": 1},
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2

        stale = client.put(
            f"/api/projects/{project_id}/drafts/idea/main",
            json={"payload": {"idea": "第二标签页的旧内容"}, "base_revision": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "DRAFT_CONFLICT"
        assert stale.json()["latest"]["payload"]["idea"] == "第一标签页的更新"
        assert client.get(f"/api/projects/{project_id}/drafts/idea/main").json()["payload"]["idea"] == "第一标签页的更新"


def test_document_draft_rejects_stale_revision_without_overwriting(db):
    import uuid

    with TestClient(create_app(database_path=db.path, seed=False)) as client:
        project_id = client.get("/api/projects").json()[0]["id"]
        now = "2026-09-06T00:00:00+00:00"
        document_id = f"document_{uuid.uuid4().hex}"
        version_id = f"document_version_{uuid.uuid4().hex}"
        with db.connect() as connection:
            connection.execute(
                "INSERT INTO documents(id, project_id, doc_type, title, created_at) VALUES (?, ?, ?, ?, ?)",
                (document_id, project_id, "prd", "测试 PRD", now),
            )
            connection.execute(
                """INSERT INTO document_versions(
                    id, document_id, project_id, doc_type, version, canvas_version,
                    status, content, citations_json, validation_status, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, 1, 1, 'draft', ?, '[]', 'not_run', ?, ?)""",
                (version_id, document_id, project_id, "prd", "初始内容", f"test:{uuid.uuid4().hex}", now),
            )
        version = {"id": version_id}

        first = client.put(
            f"/api/projects/{project_id}/documents/prd/draft",
            json={"base_version_id": version["id"], "content": "第一版草稿"},
        )
        assert first.status_code == 200
        assert first.json()["revision"] == 1

        second = client.put(
            f"/api/projects/{project_id}/documents/prd/draft",
            json={"base_version_id": version["id"], "content": "新草稿", "base_revision": 1},
        )
        assert second.status_code == 200
        assert second.json()["revision"] == 2

        stale = client.put(
            f"/api/projects/{project_id}/documents/prd/draft",
            json={"base_version_id": version["id"], "content": "旧标签页覆盖", "base_revision": 1},
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "DRAFT_CONFLICT"
        assert client.get(f"/api/projects/{project_id}/documents/prd/draft").json()["content"] == "新草稿"


def test_unified_draft_is_scoped_to_authenticated_account_and_project(portal):
    app, client = portal
    account_a = _claim(app, client, "a")
    project_a = client.post("/api/projects", json={"title": "A 私有项目", "summary": "A"}).json()["id"]
    saved_a = client.put(
        f"/api/projects/{project_a}/drafts/idea/main",
        json={"payload": {"idea": "仅属于 A 的想法"}},
    )
    assert saved_a.status_code == 200
    child_a = app.state.workspace_pool.entries[account_a]["child"]
    assert child_a.state.db.fetch_one(
        "SELECT updated_by FROM unified_drafts WHERE project_id = ?",
        (project_a,),
    )["updated_by"] == account_a

    assert client.post("/api/auth/logout").status_code == 200
    _claim(app, client, "b")
    project_b = client.post("/api/projects", json={"title": "B 私有项目", "summary": "B"}).json()["id"]
    saved_b = client.put(
        f"/api/projects/{project_b}/drafts/idea/main",
        json={"payload": {"idea": "仅属于 B 的想法"}},
    )
    assert saved_b.status_code == 200

    # The same local scope is valid inside each workspace, but A's project is
    # never selected by a client-supplied user/workspace field.
    assert client.get(f"/api/projects/{project_b}/drafts/idea/main").json()["payload"]["idea"] == "仅属于 B 的想法"
    foreign = client.get(f"/api/projects/{project_a}/drafts/idea/main")
    assert foreign.status_code == 404
    forged = client.put(
        f"/api/projects/{project_a}/drafts/idea/main",
        json={
            "payload": {"idea": "伪造归属不能写入"},
            "user_id": account_a,
            "workspace": account_a,
            "database_path": "not-used",
        },
    )
    assert forged.status_code in {404, 422}

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get(f"/api/projects/{project_b}/drafts/idea/main").status_code == 401
