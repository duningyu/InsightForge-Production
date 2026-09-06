"""Real account entry and database-routing boundary, synthetic data only."""
from dataclasses import replace
import socket

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def portal(tmp_path, monkeypatch):
    original = socket.socket.connect
    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            pytest.fail("external network forbidden")
        return original(sock, address)
    monkeypatch.setattr(socket.socket, "connect", local_only)
    settings = Settings(database_path=tmp_path / "unclaimed.sqlite3", runtime_dir=tmp_path / "old-runtime")
    # The public account entry must exist; no direct insertion of account rows.
    settings = replace(settings, accounts_enabled=True, accounts_dir=tmp_path / "accounts")
    app = create_app(settings_override=settings, seed=False)
    with TestClient(app, headers={"X-InsightForge-Request": "1"}) as client:
        yield app, client


def claim(app, client, number):
    invite = app.state.accounts.issue_invite()
    response = client.post("/api/auth/claim", json={
        "invite": invite, "username": f"synthetic{number}", "password": "SYNTHETIC-only-passphrase!",
    })
    assert response.status_code == 201, response.text
    response = client.post("/api/auth/login", json={
        "username": f"synthetic{number}", "password": "SYNTHETIC-only-passphrase!",
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_five_users_use_claim_login_and_cannot_list_or_read_other_projects(portal):
    app, client = portal
    projects = []
    for number in range(5):
        claim(app, client, number)
        assert client.get("/api/projects").json() == []
        project = client.post("/api/projects", json={"title": f"Synthetic {number}", "summary": "private"})
        assert project.status_code == 201, project.text
        own = project.json()["id"]
        assert client.get(f"/api/projects/{own}").status_code == 200
        for other in projects:
            assert client.get(f"/api/projects/{other}").status_code == 404
            assert client.get(f"/api/projects/{other}/handoff/readiness").status_code == 404
        projects.append(own)
        old_cookie = client.cookies.get("insightforge_account")
        assert client.post("/api/auth/logout").status_code == 200
        client.cookies.set("insightforge_account", old_cookie)
        assert client.get("/api/projects").status_code == 401
        client.cookies.clear()


def test_invite_is_single_use_and_client_cannot_choose_workspace(portal):
    app, client = portal
    token = app.state.accounts.issue_invite()
    payload = {"invite": token, "username": "first", "password": "SYNTHETIC-only-passphrase!"}
    assert client.post("/api/auth/claim", json={**payload, "workspace_id": "legacy"}).status_code == 422
    assert client.post("/api/auth/claim", json=payload).status_code == 201
    assert client.post("/api/auth/claim", json={**payload, "username": "second"}).status_code == 400
    assert client.post("/api/auth/login", json={"username": "first", "password": "wrong"}).status_code == 401


def test_cookie_mutations_require_same_origin_request_header(portal):
    app, client = portal
    claim(app, client, 1)
    assert client.post("/api/projects", headers={"Origin": "https://untrusted.invalid"},
                       json={"title": "bad", "summary": "bad"}).status_code == 403


def test_foreign_project_subresources_are_denied_not_empty_success(portal):
    app, client = portal
    claim(app, client, 1)
    foreign = client.post("/api/projects", json={"title": "Private", "summary": "Synthetic private project"}).json()["id"]
    client.post("/api/auth/logout")
    claim(app, client, 2)
    for suffix in ("sources", "claims", "snapshots", "retrieval-runs", "solutions",
                   "documents/prd/draft", "documents/prd/versions", "handoff/readiness",
                   "solutions/generate/synthetic-private-run"):
        response = client.get(f"/api/projects/{foreign}/{suffix}")
        assert response.status_code == 404, (suffix, response.status_code)
    for suffix in ("handoff/export", "trash"):
        assert client.post(f"/api/projects/{foreign}/{suffix}", json={}).status_code == 404
    response = client.post(f"/api/projects/{foreign}/sources/upload",
                           data={"title": "Synthetic", "source_type": "real_user_research", "authority": "0.5"},
                           files={"file": ("synthetic.txt", b"private synthetic file", "text/plain")})
    assert response.status_code == 404, response.text


def test_explicit_legacy_mapping_does_not_adopt_unclaimed_data(portal, tmp_path):
    from app.db import Database
    app, client = portal
    legacy_db = tmp_path / "legacy.sqlite3"
    legacy_runtime = tmp_path / "legacy-runtime"
    legacy_runtime.mkdir()
    db = Database(legacy_db)
    db.init_schema()
    db.seed_demo_data()  # Synthetic legacy ownership fixture on current schema, not production.
    claim(app, client, 1)
    assert client.get("/api/projects/project_insightforge_demo").status_code == 404
    client.post("/api/auth/logout")
    invite = app.state.accounts.issue_invite(legacy_binding={
        "database_path": legacy_db, "runtime_path": legacy_runtime, "participant": "beta_003"})
    payload = {"username": "legacy003", "password": "SYNTHETIC-only-passphrase!"}
    assert client.post("/api/auth/claim", json={**payload, "invite": invite}).status_code == 201
    assert client.post("/api/auth/login", json=payload).status_code == 200
    assert client.get("/api/projects/project_insightforge_demo").status_code == 200
    assert db.fetch_one("SELECT id FROM projects WHERE id='project_insightforge_demo'")
    with pytest.raises(ValueError, match="already bound"):
        app.state.accounts.issue_invite(legacy_binding={
            "database_path": legacy_db, "runtime_path": legacy_runtime, "participant": "beta_003"})

    # Real, existing synthetic versions: verify owner access before testing ID substitution.
    # Local DocumentLoop fixture is not a model-transport or handoff E2E claim.
    from app.services.loop import DocumentLoop
    versions = [DocumentLoop(db).run("project_insightforge_demo", kind,
                idempotency_key=f"isolation-{kind}")["version_id"] for kind in ("prd", "techdoc")]
    for version in versions:
        assert client.get(f"/api/documents/{version}").status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "synthetic1",
                       "password": "SYNTHETIC-only-passphrase!"}).status_code == 200
    for version in versions:
        for suffix in ("", "/claims", "/export"):
            assert client.get(f"/api/documents/{version}{suffix}").status_code == 404
        for suffix in ("trash", "restore", "restore-as-new", "validate"):
            assert client.post(f"/api/documents/{version}/{suffix}", json={}).status_code == 404
        assert client.delete(f"/api/documents/{version}").status_code == 404
        assert db.fetch_one("SELECT id FROM document_versions WHERE id=?", (version,))


def test_existing_drafts_same_local_project_id_and_anonymous_boundary(portal, tmp_path):
    """Local IDs may collide; server session, not a client hint, chooses the DB."""
    from app.db import Database
    from app.services.loop import DocumentLoop
    app, client = portal
    resources = []
    project = "project_insightforge_demo"
    route = f"/api/projects/{project}/documents/prd/draft"
    for number in (1, 2):
        path = tmp_path / f"owner{number}.sqlite3"
        runtime = tmp_path / f"owner{number}-runtime"
        runtime.mkdir()
        db = Database(path)
        db.init_schema()
        db.seed_demo_data()
        version = DocumentLoop(db).run(project, "prd", idempotency_key="same-local-key")["version_id"]
        invite = app.state.accounts.issue_invite(legacy_binding={
            "database_path": path, "runtime_path": runtime, "participant": f"beta_00{number}"})
        login = {"username": f"draft-owner{number}", "password": "SYNTHETIC-only-passphrase!"}
        assert client.post("/api/auth/claim", json={**login, "invite": invite}).status_code == 201
        assert client.post("/api/auth/login", json=login).status_code == 200
        identity = client.get("/api/auth/me").json()["id"]
        content = f"Synthetic private draft owner {number}"
        response = client.put(route, headers={"X-Actor": "forged-owner"},
                              json={"base_version_id": version, "content": content})
        assert response.status_code == 200, response.text
        assert response.json()["updated_by"] == identity
        resources.append((db, login, content))
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get(route).status_code == 401
        assert client.put(route, json={"base_version_id": version, "content": "attack"}).status_code == 401
    for index, (db, login, content) in enumerate(resources):
        assert client.post("/api/auth/login", json=login).status_code == 200
        other_db = resources[1-index][0]
        before = other_db.fetch_one("SELECT * FROM document_edit_drafts")
        response = client.get(route, params={"user_id": "other", "participant": "beta_002",
                              "workspace": "other", "database_path": str(other_db.path)})
        assert response.status_code == 200
        assert response.json()["content"] == content
        assert resources[1-index][2] not in response.text
        assert other_db.fetch_one("SELECT * FROM document_edit_drafts") == before
        assert client.post("/api/auth/logout").status_code == 200


def test_missing_header_and_invalid_sessions_never_fall_back(portal):
    app, client = portal
    claim(app, client, 9)
    client.headers.pop("X-InsightForge-Request")
    assert client.post("/api/projects", json={"title": "blocked", "summary": "blocked"}).status_code == 403
    client.cookies.clear()
    client.cookies.set("insightforge_account", "SYNTHETIC-invalid-session")
    for route in ("/api/projects", "/api/settings/model-profiles", "/api/audit", "/api/usage/policy"):
        assert client.get(route).status_code == 401
