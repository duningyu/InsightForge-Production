"""Full authenticated UI journey in an isolated fake-transport FastAPI app."""
import json, os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
for key in list(os.environ):
    if key.startswith(("INSIGHTFORGE_", "BETA_", "MANAGED_", "OPENAI_")) or any(x in key.upper() for x in ("API_KEY", "TOKEN", "PASSWORD")): os.environ.pop(key, None)
blocked=[]; original_connect=socket.socket.connect
def loopback(sock, address):
    if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}: blocked.append(address); raise AssertionError("external connection forbidden")
    return original_connect(sock, address)
socket.socket.connect=loopback; socket.socket.connect_ex=loopback

def install_fake_transport(counter):
    from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter
    from test_normal_dispatch_control_integration import _solution_payload
    solution = _solution_payload()
    # The application validator requires materially different solution paths;
    # the shared smoke payload intentionally uses two near-identical examples,
    # so make the second synthetic path genuinely distinct for this journey.
    solution["candidates"][1].update(
        mechanism="workflow_based",
        summary="synthetic workflow summary",
        why_fit="synthetic workflow fit",
        core_decision_logic="workflow checklist",
        user_flow=["step", "review"],
        required_data_class="synthetic workflow inputs",
        automation_level="medium",
        human_role="synthetic reviewer",
        major_dependency="synthetic workflow dependency",
    )
    def text(value):
        if isinstance(value, str): return value
        if isinstance(value, list): return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in value)
        return str(value)
    def send(request):
        body=json.loads(request.content); system=text(body.get("messages", [{}])[0].get("content", ""))
        if "Interpret this product idea" in system:
            kind="brief"; request=json.loads(text(body["messages"][-1]["content"]))
            data={"original_idea":request.get("idea", "帮助学生整理求职准备并逐步验证需求"),"target_user":request.get("target_user") or "正在准备求职的学生","problem":"不知道先验证什么","desired_outcome":"形成可交接的最小方案","known_resources":request.get("resources", []),"constraints":[],"unknowns":["真实用户是否频繁遇到该问题"],"clarification_required":False,"clarification_question":None,"provenance":{"target_user":"user_input","problem":"model_hypothesis","desired_outcome":"model_hypothesis","known_resources":"user_input","constraints":"model_hypothesis","unknowns":"model_hypothesis"}}
        elif "conservative brainstorming" in system.lower() or "reference suggestions" in system.lower():
            kind="ai"; data={"possible_target_users":["准备求职的学生"],"possible_scenarios":["整理求职准备"],"possible_user_problems":["不知道先验证什么"],"missing_information":["真实用户是否频繁遇到该问题"],"mvp_thoughts":["先做最小引导流程"],"questions_to_validate":["目标用户是否愿意持续使用"],"research_directions":["访谈目标用户"],"uncertainty_notice":"AI生成参考，尚未经外部资料核实。"}
        elif "Compare only" in system and "candidate" in system:
            kind="comparison"; req=json.loads(text(body["messages"][-1]["content"])); candidates=req.get("candidates", [])
            data={"competitors":[{"candidate_id":c["candidate_id"],"name":c["name"],"target_users":"暂未确认","core_problem":c.get("description") or "暂未确认","main_flow":"暂未确认","main_output":"暂未确认","adoption_barrier":"暂未确认","strengths_to_learn":["分步引导"],"things_not_to_copy":["复杂后台"],"impact_on_current_project":"借鉴分步引导","uncertainties":["来源由用户提供，尚未核实"]} for c in candidates],"project_level":{"similarities":[],"differentiation_options":[],"risks":[],"recommended_scope_implications":[]},"uncertainty_notice":"AI分析参考，建议结合实际产品页面核对。"}
        else: kind="generation"; data=solution
        counts=json.loads(counter.read_text()); counts[kind]=counts.get(kind,0)+1; counter.write_text(json.dumps(counts))
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(data,ensure_ascii=False)}}]})
    ai_init, sync_init=AsyncModelAdapter.__init__, ModelAdapter.__init__
    def async_init(self, **kwargs):
        async def request(r): return send(r)
        ai_init(self, **{**kwargs,"client":httpx.AsyncClient(transport=httpx.MockTransport(request))})
    def model_init(self, **kwargs): sync_init(self, **{**kwargs,"client":httpx.Client(transport=httpx.MockTransport(send))})
    AsyncModelAdapter.__init__=async_init; ModelAdapter.__init__=model_init

with tempfile.TemporaryDirectory(prefix="insightforge-final-journey-") as raw:
    td=Path(raw); os.environ["INSIGHTFORGE_DATABASE_PATH"]=str(td/"unused.sqlite3"); os.environ["RUNTIME_DIR"]=str(td/"unused-runtime")
    from app.config import Settings; from app.main import create_app; import uvicorn
    counter=td/"counts.json"; counter.write_text(json.dumps({"brief":0,"ai":0,"comparison":0,"generation":0}))
    install_fake_transport(counter)
    app=create_app(seed=False,settings_override=Settings(accounts_enabled=True,accounts_dir=td/"accounts",beta_mode=True,beta_managed_mode=True,daily_user_limits_enabled=False,managed_qwen_api_key="TEST_ONLY_SYNTHETIC",managed_bailian_api_key="TEST_ONLY_SYNTHETIC"))
    listener=socket.socket(); listener.bind(("127.0.0.1",0)); port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level="warning",access_log=False)); thread=threading.Thread(target=server.run,kwargs={"sockets":[listener]},daemon=True); thread.start()
    try:
        for _ in range(200):
            if server.started: break
            time.sleep(.05)
        assert server.started
        invite=app.state.accounts.issue_invite()
        invite_b=app.state.accounts.issue_invite()
        env=os.environ.copy(); roots=list((Path.home()/".cache"/"codex-runtimes").glob("**/node_modules/playwright")); bins=list((Path.home()/".cache"/"codex-runtimes").glob("**/chromium-*/chrome-win64/chrome.exe"))
        if roots: env["PLAYWRIGHT_MODULE"]=str(roots[0])
        if bins: env["CHROMIUM_PATH"]=str(bins[0])
        payload={"url":f"http://127.0.0.1:{port}","invite":invite,"username":"final-journey-user","password":"SYNTHETIC-only-passphrase!","inviteB":invite_b,"usernameB":"final-journey-control","passwordB":"SYNTHETIC-control-passphrase!"}
        result=subprocess.run(["node",str(ROOT/"tests/final_user_journey_browser.cjs")],input=json.dumps(payload),text=True,cwd=ROOT,env=env)
        counts=json.loads(counter.read_text()); assert result.returncode==0, "final browser journey failed"; assert counts["ai"]==1 and counts["comparison"]==1 and counts["generation"] >= 1; assert not blocked, blocked
        print(f"PASS final authenticated Chromium journey; fake provider calls={counts}; external=0; UI bypass=0")
    finally:
        server.should_exit=True; thread.join(timeout=15); listener.close()
