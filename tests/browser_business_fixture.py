"""Synthetic prerequisites only; browser owns generation/analysis actions."""
import json
from collections import Counter
import httpx
from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter
from test_normal_dispatch_control_integration import _solution_payload


def install_transport():
    calls = {"generation": [], "claims": []}
    payload = _solution_payload()
    payload["candidates"][1].update(human_role="synthetic author", core_decision_logic="manual checklist")
    async_init, sync_init = AsyncModelAdapter.__init__, ModelAdapter.__init__

    def asynchronous(self, **kwargs):
        def send(request):
            calls["generation"].append(kwargs.get("generation_run_id"))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
        async_init(self, **{**kwargs, "client": httpx.AsyncClient(transport=httpx.MockTransport(send))})

    def synchronous(self, **kwargs):
        def send(request):
            body = json.loads(request.content)
            context = json.loads(body["messages"][-1]["content"])
            calls["claims"].append(context["claim"]["id"])
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"relations": []}'}}]})
        sync_init(self, **{**kwargs, "client": httpx.Client(transport=httpx.MockTransport(send))})
    AsyncModelAdapter.__init__, ModelAdapter.__init__ = asynchronous, synchronous
    return calls


def prepare(app, url, invite):
    with httpx.Client(base_url=url, headers={"X-InsightForge-Request": "1"}) as client:
        credentials = {"username": "business-browser", "password": "SYNTHETIC-only-passphrase!"}
        assert client.post("/api/auth/claim", json={**credentials, "invite": invite}).status_code == 201
        assert client.post("/api/auth/login", json=credentials).status_code == 200
        account = client.get("/api/auth/me").json()["id"]
        projects = []
        for ordinal in range(4):
            response = client.post("/api/projects", json={"title": f"Synthetic browser {ordinal}", "summary": "test"})
            assert response.status_code == 201, response.text
            project = response.json()["id"]
            projects.append(project)
            child = app.state.workspace_pool.entries[account]["child"]
            db = child.state.async_generation_repository.db
            db.execute("""INSERT INTO idea_briefs(id,project_id,version,original_idea,target_user,problem,
                desired_outcome,known_resources_json,constraints_json,unknowns_json,provenance_json,
                confirmation_status,created_at) VALUES (?,?,1,?,?,?,?, '[]','[]','[]','{}','confirmed',?)""",
                (f"browser-brief-{ordinal}", project, "Synthetic idea", "synthetic users", "synthetic problem",
                 "synthetic outcome", "2026-09-06T00:00:00+00:00"))
        claims = []
        with db.connect() as connection:
            for ordinal in range(6):
                item = child.state.project_claims._insert_claim_tx(connection, project_id=projects[-1],
                    claim_type="user_problem", statement=f"Synthetic browser unresolved {ordinal}",
                    provenance="model_hypothesis", criticality="normal", scope_note="synthetic")
                claims.append(item["id"])
        client.post("/api/auth/logout")
    return {**credentials, "account": account, "projects": projects, "claims": claims}


def verify(app, data, calls):
    db = app.state.workspace_pool.entries[data["account"]]["child"].state.async_generation_repository.db
    rows = db.fetch_all("SELECT * FROM async_solution_generation_runs")
    assert len(rows) == 4 and all(row["status"] == "SUCCEEDED" and row["response_json"] for row in rows)
    assert Counter(calls["generation"]) == Counter(row["generation_run_id"] for row in rows)
    assert Counter(calls["claims"]) == Counter(data["claims"])
    assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='COMMITTED'")["n"] == 10
    assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='RESERVED'")["n"] == 0
    for operation, count in (("solution_generation", 4), ("evidence_analysis", 6)):
        assert db.fetch_one("SELECT SUM(request_count) AS n FROM beta_daily_usage WHERE operation_type=?", (operation,))["n"] == count
    print("PASS browser business persistence: generation UI actions/tasks/transport=4/4/4; analysis UI actions/claims/transport=1/6/6; committed=10; active=0")
