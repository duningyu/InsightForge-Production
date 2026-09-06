"""Account HTTP -> real worker/adapter -> fake HTTP -> durable result."""
import json
import time
from collections import Counter
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter
from test_open_accounts import claim
from test_normal_dispatch_control_integration import _solution_payload


def test_four_generations_account_scope_replay_and_worker_reconstruction(tmp_path, monkeypatch):
    calls = []
    original = AsyncModelAdapter.__init__
    payload = _solution_payload()
    payload["candidates"][1].update(human_role="synthetic author", core_decision_logic="manual checklist")

    def injected(self, **kwargs):
        def transport(request):
            calls.append((kwargs.get("generation_intent_id"), kwargs.get("generation_run_id")))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
        original(self, **{**kwargs, "client": httpx.AsyncClient(transport=httpx.MockTransport(transport))})

    monkeypatch.setattr(AsyncModelAdapter, "__init__", injected)
    settings = Settings(accounts_enabled=True, accounts_dir=tmp_path / "accounts",
                        database_path=tmp_path / "unused.sqlite3", runtime_dir=tmp_path / "unused-runtime",
                        beta_mode=True, beta_managed_mode=True, daily_user_limits_enabled=False,
                        managed_qwen_api_key="TEST_ONLY_SYNTHETIC", managed_bailian_api_key="TEST_ONLY_SYNTHETIC")
    app = create_app(settings_override=settings, seed=False)
    with TestClient(app, headers={"X-InsightForge-Request": "1"}) as client:
        runs = {}
        for user, count in ((1, 4), (2, 1)):
            claim(app, client, user)
            project = client.post("/api/projects", json={"title": f"Synthetic {user}", "summary": "local"}).json()["id"]
            account_id = client.get("/api/auth/me").json()["id"]
            child = app.state.workspace_pool.entries[account_id]["child"]
            child.state.beta_usage.clock = lambda: datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
            db = child.state.async_generation_repository.db
            # Only the confirmed-brief prerequisite is a fixture; never seed a task/result.
            db.execute("""INSERT INTO idea_briefs(id,project_id,version,original_idea,target_user,problem,
                desired_outcome,known_resources_json,constraints_json,unknowns_json,provenance_json,
                confirmation_status,created_at) VALUES (?,?,1,?,?,?,?, '[]','[]','[]','{}','confirmed',?)""",
                (f"brief-{user}", project, "Synthetic idea", "synthetic users", "synthetic problem",
                 "synthetic outcome", "2026-09-06T00:00:00+00:00"))
            path = f"/api/projects/{project}/solutions/generate"
            user_runs = []
            for ordinal in range(count):
                headers = {"X-Generation-Mode": "async", "X-Idempotency-Key": f"shared-key-{ordinal}"}
                response = client.post(path, headers=headers)
                assert response.status_code == 202, response.text
                run_id = response.json()["generation_run_id"]
                deadline = time.monotonic() + 20
                while True:
                    terminal = client.get(f"{path}/{run_id}").json()
                    if terminal.get("status") in {"SUCCEEDED", "FAILED"}:
                        break
                    assert time.monotonic() < deadline, terminal
                    time.sleep(.02)  # bounded terminal polling, not concurrency synchronization
                assert terminal["status"] == "SUCCEEDED", terminal
                assert terminal["status_code"] == 201, terminal
                row = db.fetch_one("SELECT * FROM async_solution_generation_runs WHERE generation_run_id=?", (run_id,))
                assert row["quota_status"] == "CHARGED"  # existing async terminal vocabulary
                assert row["response_json"]
                user_runs.append((row["generation_intent_id"], run_id))
                before = len(calls)
                assert client.post(path, headers=headers).status_code == 200
                assert client.get(f"{path}/{run_id}").status_code == 200
                assert len(calls) == before
            assert db.fetch_one("SELECT COUNT(*) AS n FROM solution_candidates")["n"] == count * 2
            assert db.fetch_one("SELECT SUM(request_count) AS n FROM beta_daily_usage WHERE operation_type='solution_generation'")["n"] == count
            assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='COMMITTED'")["n"] == count
            assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='RESERVED'")["n"] == 0
            runs[user] = (project, user_runs, account_id)
            if user == 2:
                foreign_project, foreign_runs, _ = runs[1]
                denied = client.get(f"/api/projects/{foreign_project}/solutions/generate/{foreign_runs[0][1]}",
                                    params={"workspace": runs[1][2], "user_id": runs[1][2], "participant": runs[1][2]})
                assert denied.status_code == 404
                assert foreign_runs[0][1] not in denied.text
            client.post("/api/auth/logout")
        assert Counter(calls) == Counter(pair for _, pairs, _ in runs.values() for pair in pairs)
        assert len(calls) == 5
        pool = app.state.workspace_pool
        idle_now = max(entry["last_used"] for entry in pool.entries.values()) + 1801
        pool.clock = lambda: idle_now
        client.portal.call(pool.sweep)
        assert not pool.entries
        client.post("/api/auth/login", json={"username": "synthetic1", "password": "SYNTHETIC-only-passphrase!"})
        project, pairs, _ = runs[1]
        for _, run_id in pairs:
            assert client.get(f"/api/projects/{project}/solutions/generate/{run_id}").json()["status"] == "SUCCEEDED"
        assert len(calls) == 5


def test_six_uncached_claim_analyses_real_adapter_and_settlement(tmp_path, monkeypatch):
    calls = []
    original = ModelAdapter.__init__

    def injected(self, **kwargs):
        def transport(request):
            body = json.loads(request.content)
            content = json.loads(body["messages"][-1]["content"])
            calls.append(content["claim"]["id"])
            # No source supplied: a valid empty relation set must not invent evidence.
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"relations": []}'}}]})
        original(self, **{**kwargs, "client": httpx.Client(transport=httpx.MockTransport(transport))})

    monkeypatch.setattr(ModelAdapter, "__init__", injected)
    settings = Settings(accounts_enabled=True, accounts_dir=tmp_path / "accounts",
                        database_path=tmp_path / "unused.sqlite3", runtime_dir=tmp_path / "unused-runtime",
                        beta_mode=True, beta_managed_mode=True, daily_user_limits_enabled=False,
                        managed_qwen_api_key="TEST_ONLY_SYNTHETIC", managed_bailian_api_key="TEST_ONLY_SYNTHETIC")
    app = create_app(settings_override=settings, seed=False)
    with TestClient(app, headers={"X-InsightForge-Request": "1"}) as client:
        claim(app, client, 1)
        project = client.post("/api/projects", json={"title": "Synthetic analysis", "summary": "local"}).json()["id"]
        account_id = client.get("/api/auth/me").json()["id"]
        child = app.state.workspace_pool.entries[account_id]["child"]
        child.state.beta_usage.clock = lambda: datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
        db = child.state.async_generation_repository.db
        claim_ids = []
        with db.connect() as connection:
            for ordinal in range(6):
                item = child.state.project_claims._insert_claim_tx(connection, project_id=project,
                    claim_type="user_problem", statement=f"Synthetic unresolved problem {ordinal}",
                    provenance="model_hypothesis", criticality="normal", scope_note="synthetic")
                claim_ids.append(item["id"])
        for claim_id in claim_ids:
            response = client.post(f"/api/projects/{project}/evidence/analyze", json={"claim_ids": [claim_id]})
            assert response.status_code == 200, response.text
            assert not response.json().get("not_analyzed"), response.text
        assert Counter(calls) == Counter(claim_ids)
        assert db.fetch_one("SELECT SUM(request_count) AS n FROM beta_daily_usage WHERE operation_type='evidence_analysis'")["n"] == 6
        assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='COMMITTED'")["n"] == 6
        assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='RESERVED'")["n"] == 0
