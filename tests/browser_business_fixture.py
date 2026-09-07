"""Synthetic prerequisites only; browser owns generation/analysis actions."""
import json
from collections import Counter
import httpx
from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter
from test_normal_dispatch_control_integration import _solution_payload


def install_transport():
    calls = {"generation": [], "generation_contexts": [], "claims": [], "competitors": []}
    payload = _solution_payload()
    payload["candidates"][1].update(human_role="synthetic author", core_decision_logic="manual checklist")
    async_init, sync_init = AsyncModelAdapter.__init__, ModelAdapter.__init__

    def message_text(value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in value
            )
        return str(value)

    def asynchronous(self, **kwargs):
        def send(request):
            body = json.loads(request.content)
            system = message_text(body.get("messages", [{}])[0].get("content", ""))
            if "Compare only" in system and "candidate" in system:
                request_data = json.loads(message_text(body["messages"][-1]["content"]))
                candidates = request_data.get("candidates", [])
                calls["competitors"].append([item.get("candidate_id") for item in candidates])
                comparison = {
                    "competitors": [
                        {
                            "candidate_id": item["candidate_id"],
                            "name": item["name"],
                            "target_users": "暂未确认",
                            "core_problem": item.get("description") or "暂未确认",
                            "main_flow": "暂未确认",
                            "main_output": "暂未确认",
                            "adoption_barrier": "暂未确认",
                            "strengths_to_learn": [],
                            "things_not_to_copy": [],
                            "impact_on_current_project": "暂未确认",
                            "uncertainties": ["来源由用户提供，尚未核实"],
                        }
                        for item in candidates
                    ],
                    "project_level": {
                        "similarities": [],
                        "differentiation_options": [],
                        "risks": [],
                        "recommended_scope_implications": [],
                    },
                    "uncertainty_notice": "AI分析参考，建议结合实际产品页面核对。",
                }
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(comparison, ensure_ascii=False)}}]})
            calls["generation_contexts"].append(message_text(body["messages"][-1]["content"]))
            calls["generation"].append(kwargs.get("generation_run_id"))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
        async_init(self, **{**kwargs, "client": httpx.AsyncClient(transport=httpx.MockTransport(send))})

    def synchronous(self, **kwargs):
        def send(request):
            body = json.loads(request.content)
            system = message_text(body.get("messages", [{}])[0].get("content", ""))
            if "Compare only" in system and "candidate" in system:
                request_data = json.loads(message_text(body["messages"][-1]["content"]))
                candidates = request_data.get("candidates", [])
                calls["competitors"].append([item.get("candidate_id") for item in candidates])
                comparison = {
                    "competitors": [
                        {
                            "candidate_id": item["candidate_id"],
                            "name": item["name"],
                            "target_users": "暂未确认",
                            "core_problem": item.get("description") or "暂未确认",
                            "main_flow": "暂未确认",
                            "main_output": "暂未确认",
                            "adoption_barrier": "暂未确认",
                            "strengths_to_learn": [],
                            "things_not_to_copy": [],
                            "impact_on_current_project": "暂未确认",
                            "uncertainties": ["来源由用户提供，尚未核实"],
                        }
                        for item in candidates
                    ],
                    "project_level": {
                        "similarities": [],
                        "differentiation_options": [],
                        "risks": [],
                        "recommended_scope_implications": [],
                    },
                    "uncertainty_notice": "AI分析参考，建议结合实际产品页面核对。",
                }
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(comparison, ensure_ascii=False)}}]})
            context = json.loads(message_text(body["messages"][-1]["content"]))
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


def prepare_competitor(app, url, invite):
    """Create the synthetic browser account without consuming the UI flow."""
    with httpx.Client(base_url=url, headers={"X-InsightForge-Request": "1"}) as client:
        credentials = {"username": "competitor-browser", "password": "SYNTHETIC-only-passphrase!"}
        assert client.post("/api/auth/claim", json={**credentials, "invite": invite}).status_code == 201
        assert client.post("/api/auth/login", json=credentials).status_code == 200
        account = client.get("/api/auth/me").json()["id"]
        response = client.post("/api/projects", json={"title": "Synthetic competitor UI", "summary": "test"})
        assert response.status_code == 201, response.text
        project = response.json()["id"]
        child = app.state.workspace_pool.entries[account]["child"]
        db = child.state.async_generation_repository.db
        db.execute("""INSERT INTO idea_briefs(id,project_id,version,original_idea,target_user,problem,
            desired_outcome,known_resources_json,constraints_json,unknowns_json,provenance_json,
            confirmation_status,created_at) VALUES (?,?,1,?,?,?,?, '[]','[]','[]','{}','confirmed',?)""",
            ("browser-competitor-brief", project, "Synthetic competitor idea", "synthetic users",
             "synthetic problem", "synthetic outcome", "2026-09-06T00:00:00+00:00"))
        client.post("/api/auth/logout")
    return {**credentials, "account": account, "project": project, "prepared": True}


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


def verify_competitor(app, data, calls):
    assert len(calls["competitors"]) == 1
    assert len(calls["competitors"][0]) == 1
    db = app.state.workspace_pool.entries[data["account"]]["child"].state.async_generation_repository.db
    assert db.fetch_one("SELECT COUNT(*) AS n FROM competitor_comparisons")["n"] == 1
    assert db.fetch_one("SELECT COUNT(*) AS n FROM competitor_decision_snapshots")["n"] == 1
    generation_runs = db.fetch_all("SELECT * FROM async_solution_generation_runs WHERE status='SUCCEEDED'")
    assert len(generation_runs) == 1
    snapshot_id = db.fetch_one("SELECT id FROM competitor_decision_snapshots")["id"]
    assert generation_runs[0]["competitor_snapshot_id"] == snapshot_id
    assert len(calls["generation"]) == 1
    assert any("借鉴分步引导" in context for context in calls["generation_contexts"])
    versions = db.fetch_all("SELECT doc_type, competitor_snapshot_id FROM document_versions WHERE project_id=?", (data["project"],))
    assert {row["doc_type"] for row in versions} == {"prd", "techdoc"}
    assert all(row["competitor_snapshot_id"] == snapshot_id for row in versions)
    print("PASS browser competitor business wiring: candidate -> comparison=1 -> snapshot=1 -> generation=1 -> PRD/TechDoc snapshot refs; fake transport=3")
