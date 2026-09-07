"""Run unified-draft acceptance flows in an isolated real Chromium session."""
import asyncio, json, os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in list(os.environ):
    if key.startswith(("INSIGHTFORGE_", "BETA_", "MANAGED_", "OPENAI_")) or any(marker in key.upper() for marker in ("API_KEY", "TOKEN", "PASSWORD")):
        os.environ.pop(key, None)
blocked = []
original_connect = socket.socket.connect

def loopback(sock, address):
    if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
        blocked.append(address); raise AssertionError("external connection forbidden")
    return original_connect(sock, address)
socket.socket.connect = loopback
socket.socket.connect_ex = loopback

def install_fake_transport(counter_path, release_path):
    from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter
    from test_normal_dispatch_control_integration import _solution_payload
    payload = _solution_payload()
    # The production validator intentionally rejects near-duplicate solutions.
    # Keep the fake response structurally valid and materially distinct so this
    # browser test exercises task recovery rather than post-processing failure.
    candidates = payload["candidates"]
    candidates[0].update({"mechanism": "workflow_based", "summary": "synthetic guided workflow", "user_flow": ["collect", "guide", "review"], "complexity": "medium", "automation_level": "medium", "human_role": "reviews"})
    candidates[1].update({"mechanism": "assistant", "summary": "synthetic self service assistant", "user_flow": ["configure", "run", "export"], "complexity": "low", "automation_level": "high", "human_role": "approves"})
    def bump(kind):
        counts = {"generation": 0, "comparison": 0}
        if counter_path.exists(): counts.update(json.loads(counter_path.read_text(encoding="utf-8")))
        counts[kind] += 1; counter_path.write_text(json.dumps(counts), encoding="utf-8")
    def text(value):
        if isinstance(value, str): return value
        if isinstance(value, list): return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in value)
        return str(value)
    def response(request):
        body = json.loads(request.content)
        system = text(body.get("messages", [{}])[0].get("content", ""))
        if "Compare only" in system and "candidate" in system:
            bump("comparison"); data = json.loads(text(body["messages"][-1]["content"]))
            comparison = {"competitors": [{"candidate_id": x["candidate_id"], "name": x["name"], "target_users": "暂未确认", "core_problem": x.get("description") or "暂未确认", "main_flow": "暂未确认", "main_output": "暂未确认", "adoption_barrier": "暂未确认", "strengths_to_learn": ["分步引导"], "things_not_to_copy": ["复杂后台"], "impact_on_current_project": "可作为参考", "uncertainties": ["来源由用户提供，尚未核实"]} for x in data.get("candidates", [])], "project_level": {"similarities": [], "differentiation_options": [], "risks": [], "recommended_scope_implications": []}, "uncertainty_notice": "AI分析参考，建议结合实际产品页面核对。"}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(comparison, ensure_ascii=False)}}]})
        bump("generation")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
    async_init, sync_init = AsyncModelAdapter.__init__, ModelAdapter.__init__
    async def async_response(request):
        body = json.loads(request.content)
        system = text(body.get("messages", [{}])[0].get("content", ""))
        if "Compare only" in system and "candidate" in system:
            bump("comparison")
            data = json.loads(text(body["messages"][-1]["content"]))
            comparison = {"competitors": [{"candidate_id": x["candidate_id"], "name": x["name"], "target_users": "暂未确认", "core_problem": x.get("description") or "暂未确认", "main_flow": "暂未确认", "main_output": "暂未确认", "adoption_barrier": "暂未确认", "strengths_to_learn": ["分步引导"], "things_not_to_copy": ["复杂后台"], "impact_on_current_project": "可作为参考", "uncertainties": ["来源由用户提供，尚未核实"]} for x in data.get("candidates", [])], "project_level": {"similarities": [], "differentiation_options": [], "risks": [], "recommended_scope_implications": []}, "uncertainty_notice": "AI分析参考，建议结合实际产品页面核对。"}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(comparison, ensure_ascii=False)}}]})
        bump("generation")
        while not release_path.exists():
            await asyncio.sleep(.05)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
    def async_init_patched(self, **kwargs):
        async def send(request): return await async_response(request)
        async_init(self, **{**kwargs, "client": httpx.AsyncClient(transport=httpx.MockTransport(send))})
    def sync_init_patched(self, **kwargs):
        def send(request): return response(request)
        sync_init(self, **{**kwargs, "client": httpx.Client(transport=httpx.MockTransport(send))})
    AsyncModelAdapter.__init__ = async_init_patched; ModelAdapter.__init__ = sync_init_patched

def prepare(app, url, invites):
    credentials, projects = [], []
    with httpx.Client(base_url=url, headers={"X-InsightForge-Request": "1"}) as client:
        for ordinal, invite in enumerate(invites):
            user = {"username": f"draft-browser-{ordinal}", "password": "SYNTHETIC-only-passphrase!"}
            assert client.post("/api/auth/claim", json={**user, "invite": invite}).status_code == 201
            assert client.post("/api/auth/login", json=user).status_code == 200
            account = client.get("/api/auth/me").json()["id"]
            result = client.post("/api/projects", json={"title": f"Draft browser {ordinal}", "summary": "synthetic"})
            assert result.status_code == 201, result.text
            project = result.json()["id"]; projects.append(project)
            db = app.state.workspace_pool.entries[account]["child"].state.async_generation_repository.db
            db.execute("""INSERT INTO idea_briefs(id,project_id,version,original_idea,target_user,problem,desired_outcome,known_resources_json,constraints_json,unknowns_json,provenance_json,confirmation_status,created_at) VALUES (?,?,1,?,?,?,?, '[]','[]','[]','{}','confirmed',?)""", (f"draft-browser-brief-{ordinal}", project, "Synthetic idea", "synthetic users", "synthetic problem", "synthetic outcome", "2026-09-06T00:00:00+00:00"))
            client.post("/api/auth/logout"); credentials.append({**user, "account": account})
    return credentials, projects

with tempfile.TemporaryDirectory(prefix="insightforge-draft-browser-") as temporary:
    temporary = Path(temporary); os.environ["INSIGHTFORGE_DATABASE_PATH"] = str(temporary / "unused.sqlite3"); os.environ["RUNTIME_DIR"] = str(temporary / "unused-runtime")
    from app.config import Settings
    from app.main import create_app
    import uvicorn
    counter_path, release_path = temporary / "adapter-counts.json", temporary / "release-generation"
    counter_path.write_text(json.dumps({"generation": 0, "comparison": 0}), encoding="utf-8")
    install_fake_transport(counter_path, release_path)
    app = create_app(seed=False, settings_override=Settings(
        accounts_enabled=True, accounts_dir=temporary / "accounts",
        beta_mode=True, beta_managed_mode=True, daily_user_limits_enabled=False,
        managed_qwen_api_key="TEST_ONLY_SYNTHETIC", managed_bailian_api_key="TEST_ONLY_SYNTHETIC",
    ))
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="info", access_log=False)); thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True); thread.start()
    try:
        for _ in range(200):
            if server.started: break
            time.sleep(.05)
        assert server.started, "lifespan startup failed"
        credentials, projects = prepare(app, f"http://127.0.0.1:{port}", [app.state.accounts.issue_invite() for _ in range(2)])
        data = {"url": f"http://127.0.0.1:{port}", "userA": credentials[0], "userB": credentials[1], "projectA": projects[0], "projectB": projects[1], "releasePath": str(release_path)}
        browser_env = os.environ.copy()
        runtime_root = Path.home() / ".cache" / "codex-runtimes"
        playwright_modules = list(runtime_root.glob("**/node_modules/playwright"))
        chromium_binaries = list(runtime_root.glob("**/chromium-*/chrome-win64/chrome.exe"))
        if playwright_modules:
            browser_env["PLAYWRIGHT_MODULE"] = str(playwright_modules[0])
        if chromium_binaries:
            browser_env["CHROMIUM_PATH"] = str(chromium_binaries[0])
        result = subprocess.run(["node", str(ROOT / "tests" / "draft_recovery_browser.cjs")], input=json.dumps(data), text=True, cwd=ROOT, env=browser_env)
        counts = json.loads(counter_path.read_text(encoding="utf-8"))
        if result.returncode != 0:
            for account in credentials:
                child = app.state.workspace_pool.entries[account["account"]]["child"]
                db = child.state.async_generation_repository.db
                rows = db.fetch_all("SELECT generation_run_id, status, status_code, provider_call_count, quota_status, response_json, solution_run_id FROM async_solution_generation_runs ORDER BY created_at")
                print(json.dumps({"account": account["account"], "runs": rows}, ensure_ascii=False, default=str))
        assert result.returncode == 0, "draft browser scenario failed"; assert not blocked, blocked
        assert counts == {"generation": 1, "comparison": 1}, counts
        print(f"Application lifespan executed; fake adapter calls={counts}; real external connections=0; blocked attempts=0")
    finally:
        # Let the ASGI lifespan close every account workspace before the
        # temporary directory is removed.  On Windows the child SQLite files
        # remain locked until that async shutdown completes.
        server.should_exit = True
        thread.join(timeout=60)
        listener.close()
        assert not thread.is_alive(), "isolated browser server did not shut down cleanly"
