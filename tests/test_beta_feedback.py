from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def _client(monkeypatch, root, participant="beta_001", *, beta=True):
    monkeypatch.setenv("BETA_MODE", "true" if beta else "false")
    monkeypatch.setenv("BETA_PARTICIPANT_ID", participant)
    monkeypatch.setenv("BETA_CONSENT_VERSION", "1")
    monkeypatch.setenv("RUNTIME_DIR", str(root / "runtime"))
    return TestClient(create_app(database_path=root / "insightforge.db", seed=False))


def _consent(client):
    assert client.post("/api/beta/consent", json={"accepted": True, "consent_version": 1}).status_code == 200


def _project(client):
    response = client.post("/api/projects", json={"title": "Feedback project", "summary": "Feedback scope"})
    assert response.status_code == 201
    return response.json()["id"]


def _payload(project_id=None, **overrides):
    payload = {
        "project_id": project_id,
        "project_stage": "snapshot",
        "rating": 4,
        "feedback_type": "helpful",
        "comment": "  这一步很清楚  ",
    }
    payload.update(overrides)
    return payload


def test_valid_feedback_is_trimmed_bound_to_server_participant_and_analytics_excludes_comment(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        _consent(client)
        project_id = _project(client)
        response = client.post("/api/beta/feedback", json=_payload(project_id))
        assert response.status_code == 201
        row = client.app.state.db.fetch_one("SELECT * FROM beta_feedback")
        assert row["participant_id"] == "beta_001"
        assert row["project_id"] == project_id
        assert row["comment"] == "这一步很清楚"
        event = client.app.state.db.fetch_one("SELECT properties_json FROM product_events WHERE event_name='beta_feedback_submitted'")
        assert event["properties_json"] == '{"feedback_type": "helpful", "project_stage": "snapshot", "rating_bucket": "4_5"}'
        assert "这一步很清楚" not in event["properties_json"]


def test_feedback_validation_rejects_out_of_contract_values(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        _consent(client)
        project_id = _project(client)
        invalid = [
            _payload(project_id, rating=0),
            _payload(project_id, rating=6),
            _payload(project_id, feedback_type="surprise"),
            _payload(project_id, project_stage="admin"),
            _payload(project_id, comment="   "),
            _payload(project_id, comment="x" * 2001),
            {**_payload(project_id), "participant_id": "beta_999"},
            {**_payload(project_id), "session_id": "client-session"},
        ]
        for payload in invalid:
            assert client.post("/api/beta/feedback", json=payload).status_code == 422
        assert client.app.state.db.fetch_one("SELECT id FROM beta_feedback") is None


def test_feedback_requires_beta_consent_and_known_project(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        assert client.post("/api/beta/feedback", json=_payload()).status_code == 403
        _consent(client)
        assert client.post("/api/beta/feedback", json=_payload("missing-project")).status_code == 404
    with _client(monkeypatch, tmp_path / "non-beta", beta=False) as client:
        assert client.post("/api/beta/feedback", json=_payload()).status_code == 403


def test_feedback_participant_database_isolation_and_restart_persistence(monkeypatch, tmp_path):
    first_root = tmp_path / "beta_001"
    with _client(monkeypatch, first_root, "beta_001") as first:
        _consent(first)
        assert first.post("/api/beta/feedback", json=_payload()).status_code == 201
    with _client(monkeypatch, tmp_path / "beta_002", "beta_002") as second:
        assert second.app.state.db.fetch_one("SELECT id FROM beta_feedback") is None
        _consent(second)
        assert second.post("/api/beta/feedback", json=_payload(comment="beta two")).status_code == 201
    with _client(monkeypatch, first_root, "beta_001") as restarted:
        rows = restarted.app.state.db.fetch_all("SELECT comment FROM beta_feedback")
        assert [row["comment"] for row in rows] == ["这一步很清楚"]


def test_feedback_persistence_survives_analytics_side_effect_failure(monkeypatch, tmp_path):
    with _client(monkeypatch, tmp_path) as client:
        _consent(client)
        client.app.state.beta_analytics.record_safe = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("analytics down"))
        response = client.post("/api/beta/feedback", json=_payload(comment="feedback survives"))
        assert response.status_code == 201
        assert client.app.state.db.fetch_one("SELECT comment FROM beta_feedback")["comment"] == "feedback survives"


def test_feedback_script_text_is_returned_only_as_escaped_ui_input(monkeypatch, tmp_path):
    script = "<script>alert(1)</script>"
    with _client(monkeypatch, tmp_path) as client:
        _consent(client)
        response = client.post("/api/beta/feedback", json=_payload(comment=script))
        assert response.status_code == 201
        assert script not in response.text
