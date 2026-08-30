from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import create_app


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


def _client(monkeypatch, tmp_path, participant="beta_001", *, beta=True, version=1):
    monkeypatch.setenv("BETA_MODE", "true" if beta else "false")
    monkeypatch.setenv("BETA_PARTICIPANT_ID", participant)
    monkeypatch.setenv("BETA_CONSENT_VERSION", str(version))
    monkeypatch.setenv("BETA_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path / "runtime"))
    return TestClient(create_app(database_path=tmp_path / "db.sqlite3", seed=False))


def _accept(client: TestClient) -> None:
    response = client.post(
        "/api/beta/consent", json={"accepted": True, "consent_version": 1}
    )
    assert response.status_code == 200


def _events(client: TestClient, name: str | None = None) -> list[dict]:
    sql = "SELECT * FROM product_events"
    params = ()
    if name:
        sql += " WHERE event_name=?"
        params = (name,)
    return client.app.state.db.fetch_all(sql + " ORDER BY occurred_at, id", params)


def test_consent_gate_server_session_and_event_allowlist(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        assert client.get("/api/beta/consent").json() == {
            "beta_mode": True, "consented": False, "consent_version": 1,
        }
        assert client.post("/api/beta/events", json={"event_name": "snapshot_viewed", "properties": {}}).status_code == 403
        _accept(client)
        accepted = client.post("/api/beta/events", json={"event_name": "snapshot_viewed", "properties": {}})
        assert accepted.status_code == 200 and accepted.json()["recorded"] is True
        assert _events(client, "snapshot_viewed")[0]["session_id"]
        assert client.post("/api/beta/events", json={"event_name": "unknown", "properties": {}}).status_code == 422
        assert client.post("/api/beta/events", json={"event_name": "snapshot_viewed", "session_id": "client-owned", "properties": {}}).status_code == 422


def test_privacy_filter_and_property_allowlists_fail_closed(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        _accept(client)
        response = client.post("/api/beta/events", json={"event_name": "next_action_shown", "properties": {"nested": {"Prompt": "do not store"}}})
        assert response.status_code == 422
        assert client.post("/api/beta/events", json={"event_name": "next_action_shown", "properties": {"location": "home", "action_type": "not_allowed"}}).status_code == 422
        assert _events(client, "next_action_shown") == []


def test_same_session_within_30_minutes_and_rollover(monkeypatch, tmp_path):
    clock = Clock()
    with _client(monkeypatch, tmp_path) as client:
        client.app.state.beta_sessions.clock = clock
        first = client.get("/api/beta/consent")
        first_cookie = first.cookies.get("insightforge_beta_session")
        assert first_cookie and first_cookie != "beta_001"
        clock.value += timedelta(minutes=30)
        second = client.get("/api/beta/consent")
        assert second.cookies.get("insightforge_beta_session", first_cookie) == first_cookie
        clock.value += timedelta(minutes=30, seconds=1)
        third = client.get("/api/beta/consent")
        assert third.cookies.get("insightforge_beta_session") not in (None, first_cookie)


def test_session_started_only_after_consent(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        client.get("/api/beta/consent")
        assert _events(client, "beta_session_started") == []
        _accept(client)
        assert len(_events(client, "beta_session_started")) == 1


def test_consent_persists_across_refresh_restart_and_version_upgrade(monkeypatch, tmp_path):
    db_path = tmp_path / "db.sqlite3"
    with _client(monkeypatch, tmp_path) as client:
        _accept(client)
        assert client.get("/api/beta/consent").json()["consented"] is True
    monkeypatch.setenv("BETA_CONSENT_VERSION", "1")
    with TestClient(create_app(database_path=db_path, seed=False)) as restarted:
        assert restarted.get("/api/beta/consent").json()["consented"] is True
    monkeypatch.setenv("BETA_CONSENT_VERSION", "2")
    with TestClient(create_app(database_path=db_path, seed=False)) as upgraded:
        status = upgraded.get("/api/beta/consent").json()
        assert status["consented"] is False and status["consent_version"] == 2
        assert upgraded.app.state.db.fetch_one("SELECT id FROM beta_consents WHERE consent_version=1") is not None


def test_non_beta_analytics_is_noop(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path, beta=False) as client:
        assert client.get("/api/beta/consent").json()["beta_mode"] is False
        response = client.post("/api/beta/events", json={"event_name": "snapshot_viewed", "properties": {}})
        assert response.status_code == 200 and response.json()["recorded"] is False
        assert _events(client) == []


def test_p0_funnel_is_server_recorded_and_contains_no_idea_text(monkeypatch, tmp_path):
    secret_idea = "我要做一个包含 UNIQUE_SECRET_IDEA_123 的便利店补货产品"
    with _client(monkeypatch, tmp_path) as client:
        _accept(client)
        created = client.post("/api/projects/quick-start", json={"idea": secret_idea, "target_user": "用户", "resources": [], "priority": "fast_mvp"})
        assert created.status_code == 201
        project_id = created.json()["project_id"]
        assert client.post(
            f"/api/projects/{project_id}/idea-brief/confirm",
            json={"human_confirmed": True, "note": "test"},
        ).status_code == 200
        generated = client.post(f"/api/projects/{project_id}/solutions/generate")
        assert generated.status_code == 201
        candidates = generated.json()["candidates"]
        selected = client.post(f"/api/projects/{project_id}/solutions/select", json={"strategy": "single", "candidate_ids": [candidates[0]["id"]], "rationale": "test", "human_confirmed": True})
        assert selected.status_code == 201
        names = [row["event_name"] for row in _events(client)]
        assert all(names.count(name) == 1 for name in ("idea_submitted", "solutions_generated", "solution_selected", "snapshot_created")), names
        serialized = "\n".join(row["properties_json"] for row in _events(client))
        assert secret_idea not in serialized
        assert json.loads(_events(client, "idea_submitted")[0]["properties_json"])["idea_length_bucket"] == "21_50"


def test_analytics_failure_never_rolls_back_business_result(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        _accept(client)
        client.app.state.beta_analytics.record = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("analytics unavailable"))
        created = client.post("/api/projects/quick-start", json={"idea": "便利店补货项目仍应创建成功", "target_user": None, "resources": [], "priority": "fast_mvp"})
        assert created.status_code == 201
        assert client.app.state.db.fetch_one("SELECT id FROM projects") is not None


def test_project_event_rejects_unknown_project(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        _accept(client)
        response = client.post("/api/beta/events", json={"event_name": "snapshot_viewed", "project_id": "missing", "properties": {}})
        assert response.status_code == 404
        assert _events(client, "snapshot_viewed") == []


def test_participant_sessions_and_events_are_database_isolated(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path / "one", "beta_001") as first:
        _accept(first)
        first.post("/api/beta/events", json={"event_name": "snapshot_viewed", "properties": {}})
        assert len(_events(first)) == 2
    with _client(monkeypatch, tmp_path / "two", "beta_002") as second:
        assert _events(second) == []
        assert second.app.state.db.fetch_one("SELECT id FROM beta_sessions") is None


def test_actual_evidence_prd_prompt_completion_and_credentials_do_not_leak(monkeypatch, tmp_path, caplog):
    markers = {
        "evidence": "UNIQUE_EVIDENCE_TEXT_789",
        "prd": "UNIQUE_PRD_TEXT_456",
        "prompt": "UNIQUE_PROMPT_SECRET_ABC",
        "completion": "UNIQUE_COMPLETION_SECRET_XYZ",
        "key": "sk-beta-test-DO-NOT-STORE",
        "authorization": "Bearer beta-authorization-secret",
    }
    with _client(monkeypatch, tmp_path) as client:
        _accept(client)
        created = client.post("/api/projects/quick-start", json={"idea": "便利店补货测试", "target_user": None, "resources": [], "priority": "fast_mvp"})
        project_id = created.json()["project_id"]
        source = client.post(
            f"/api/projects/{project_id}/sources",
            json={"title": "测试资料", "source_type": "user_input", "authority": 0.5, "content": markers["evidence"], "filename": "evidence.txt"},
        )
        assert source.status_code == 201
        client.app.state.document_loop.run = lambda *args, **kwargs: {
            "version_id": "mock-version", "content": markers["prd"],
            "prompt": markers["prompt"], "completion": markers["completion"],
        }
        generated = client.post(f"/api/projects/{project_id}/documents/generate", json={"doc_type": "prd"})
        assert generated.status_code == 200
        rejected = client.post(
            "/api/beta/events",
            json={"event_name": "snapshot_viewed", "properties": {"authorization": markers["authorization"], "api_key": markers["key"]}},
        )
        assert rejected.status_code == 422
        serialized = "\n".join(row["properties_json"] for row in _events(client)) + caplog.text
        for marker in markers.values():
            assert marker not in serialized


def test_beta_cookie_is_opaque_httponly_and_samesite_lax(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        response = client.get("/api/beta/consent")
        cookie = response.headers["set-cookie"]
        assert "insightforge_beta_session=" in cookie
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert "beta_001" not in cookie


def test_secondary_workflow_routes_emit_only_controlled_events(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        _accept(client)
        created = client.post("/api/projects/quick-start", json={"idea": "便利店补货测试", "target_user": None, "resources": [], "priority": "fast_mvp"})
        project_id = created.json()["project_id"]

        client.app.state.document_loop.run = lambda *args, **kwargs: {"version_id": "generated"}
        assert client.post(f"/api/projects/{project_id}/documents/generate", json={"doc_type": "prd"}).status_code == 200
        assert client.post(f"/api/projects/{project_id}/documents/generate", json={"doc_type": "techdoc"}).status_code == 200

        workspace = client.app.state.document_workspace
        workspace.get_draft = lambda *args, **kwargs: {"content": "old"}
        workspace.save_draft = lambda *args, **kwargs: {"content": kwargs["content"]}
        assert client.put(f"/api/projects/{project_id}/documents/prd/draft", json={"base_version_id": "v1", "content": "new draft"}).status_code == 200

        client.app.state.document_versions.confirm = lambda *args, **kwargs: {"project_id": project_id, "doc_type": "prd", "version": 2}
        assert client.post("/api/document-versions/v2/confirm", json={"actor": "tester", "note": "ok", "human_confirmed": True}).status_code == 200

        walkthrough = client.app.state.walkthrough
        walkthrough.start = lambda *_: {"status": "active", "current_step": "idea"}
        walkthrough.advance = lambda *_: {"status": "completed", "current_step": "completed"}
        walkthrough.get = lambda *_: {"status": "active", "current_step": "idea"}
        walkthrough.skip = lambda *_: {"status": "skipped"}
        walkthrough.restart = lambda *_: {"status": "active", "current_step": "idea"}
        assert client.post(f"/api/projects/{project_id}/walkthrough/start").status_code == 200
        assert client.post(f"/api/projects/{project_id}/walkthrough/advance", json={"step": "idea"}).status_code == 200
        assert client.post(f"/api/projects/{project_id}/walkthrough/skip").status_code == 200
        assert client.post(f"/api/projects/{project_id}/walkthrough/restart").status_code == 200

        client.app.state.handoff.readiness = lambda *_: {"ready": False, "missing": []}
        client.app.state.handoff.build_zip = lambda *args, **kwargs: (b"zip", {"package_sha256": "safe", "handoff_run_id": "run"})
        assert client.get(f"/api/projects/{project_id}/handoff/readiness").status_code == 200
        assert client.post(f"/api/projects/{project_id}/handoff/export", json={"target_client": "codex"}).status_code == 200

        ui_events = [
            ("snapshot_viewed", {}),
            ("evidence_impact_viewed", {"impact_count": 1}),
            ("prd_editor_opened", {"doc_type": "prd", "version_no": 2}),
            ("next_action_shown", {"location": "project", "action_type": "generate_or_update_prd"}),
            ("next_action_clicked", {"location": "project", "action_type": "generate_or_update_prd"}),
        ]
        for event_name, properties in ui_events:
            response = client.post("/api/beta/events", json={"event_name": event_name, "project_id": project_id, "properties": properties})
            assert response.status_code == 200

        names = [row["event_name"] for row in _events(client)]
        for required in (
            "prd_generated", "techdoc_generated", "prd_draft_saved", "prd_version_confirmed",
            "walkthrough_started", "walkthrough_step_completed", "walkthrough_completed",
            "walkthrough_skipped", "walkthrough_restarted", "handoff_opened", "handoff_exported",
            "snapshot_viewed", "evidence_impact_viewed", "prd_editor_opened",
            "next_action_shown", "next_action_clicked",
        ):
            assert names.count(required) == 1, (required, names)
