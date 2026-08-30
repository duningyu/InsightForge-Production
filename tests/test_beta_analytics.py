from __future__ import annotations
from fastapi.testclient import TestClient
from app.main import create_app

def _client(monkeypatch, tmp_path, participant='beta_001'):
    monkeypatch.setenv('BETA_MODE','true'); monkeypatch.setenv('BETA_PARTICIPANT_ID',participant); monkeypatch.setenv('RUNTIME_DIR',str(tmp_path/'runtime'))
    return TestClient(create_app(database_path=tmp_path/'db.sqlite3', seed=False))

def test_consent_gate_and_event_allowlist(monkeypatch, tmp_path):
    with _client(monkeypatch,tmp_path) as c:
        assert c.post('/api/beta/events',json={'event_name':'idea_submitted','session_id':'s1','properties':{'idea_length_bucket':'50_100'}}).status_code == 403
        assert c.post('/api/beta/consent').status_code == 200
        assert c.post('/api/beta/events',json={'event_name':'idea_submitted','session_id':'s1','properties':{'idea_length_bucket':'50_100'}}).status_code == 200
        assert c.post('/api/beta/events',json={'event_name':'unknown','session_id':'s1','properties':{}}).status_code == 422

def test_privacy_filter_rejects_nested_forbidden_property(monkeypatch, tmp_path):
    with _client(monkeypatch,tmp_path) as c:
        c.post('/api/beta/consent')
        response=c.post('/api/beta/events',json={'event_name':'idea_submitted','session_id':'s1','properties':{'nested':{'Prompt':'do not store'}}})
        assert response.status_code == 422
        assert c.app.state.db.fetch_one('SELECT id FROM product_events') is None
