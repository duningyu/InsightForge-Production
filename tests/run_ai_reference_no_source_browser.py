"""Run AI-reference and zero-source handoff flows in isolated Chromium."""
import asyncio, json, os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
for key in list(os.environ):
    if key.startswith(("INSIGHTFORGE_", "BETA_", "MANAGED_", "OPENAI_")) or any(x in key.upper() for x in ("API_KEY", "TOKEN", "PASSWORD")): os.environ.pop(key, None)
blocked=[]; original_connect=socket.socket.connect
def loopback(sock, address):
    if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}: blocked.append(address); raise AssertionError("external connection forbidden")
    return original_connect(sock,address)
socket.socket.connect=loopback; socket.socket.connect_ex=loopback

def install_fake_transport(counter):
    from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter
    from test_normal_dispatch_control_integration import _solution_payload
    solution=_solution_payload(); solution["candidates"][0].update({"mechanism":"workflow_based","summary":"synthetic guided workflow","user_flow":["collect","guide","review"],"complexity":"medium","automation_level":"medium","human_role":"reviews"})
    def text(x): return x if isinstance(x,str) else "".join(y.get("text","") if isinstance(y,dict) else str(y) for y in x) if isinstance(x,list) else str(x)
    def bump(kind):
        data=json.loads(counter.read_text()); data[kind]=data.get(kind,0)+1; counter.write_text(json.dumps(data))
    def payload(request):
        body=json.loads(request.content); system=text(body.get("messages",[{}])[0].get("content",""))
        if "concrete evidence action cards" in system.lower() or "evidence action cards" in system.lower():
            bump("evidence_guidance"); data={"cards":[{"title":"找一次真实的使用经历","question_to_validate":"目标用户是否真的遇到这个问题？","why_it_matters":"帮助判断第一版是否值得解决这个问题。","who_or_where":["最近遇到过类似问题的人"],"action_steps":["请对方回忆最近一次具体经历","记录当时怎么处理以及哪里卡住"],"suggested_questions":["当时具体发生了什么？","你现在是怎么解决的？"],"acceptable_artifacts":["一段匿名原话","一条经过脱敏的操作记录"],"fill_template":["对象：","时间和场景：","对方原话：","我的理解："],"decision_impact":"决定第一版优先解决哪个步骤。","fallback_if_unavailable":"暂时找不到合适的人时，先记录自己的经历并标为待确认。","limitations":"少量反馈不能代表所有用户。"}],"disclosure":"AI建议你去补这些资料，尚未加入项目资料，也不代表已经核实。"}
        elif "conservative brainstorming" in system.lower() or "reference suggestions" in system.lower():
            bump("ai_reference"); data={"possible_target_users":["刚开始验证想法的学生"],"possible_scenarios":["整理一个模糊Idea"],"possible_user_problems":["不知道先验证什么"],"missing_information":["真实用户是否频繁遇到该问题"],"mvp_thoughts":["先做一个最小引导流程"],"questions_to_validate":["目标用户愿不愿意持续使用"],"research_directions":["访谈目标用户"],"uncertainty_notice":"AI生成参考，尚未经外部资料核实。"}
        else: bump("generation"); data=solution
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(data,ensure_ascii=False)}}]})
    async_init,sync_init=AsyncModelAdapter.__init__,ModelAdapter.__init__
    def ai(self,**kwargs):
        async def send(request): return payload(request)
        async_init(self,**{**kwargs,"client":httpx.AsyncClient(transport=httpx.MockTransport(send))})
    def sync(self,**kwargs):
        sync_init(self,**{**kwargs,"client":httpx.Client(transport=httpx.MockTransport(lambda request:payload(request)) )})
    AsyncModelAdapter.__init__=ai; ModelAdapter.__init__=sync

def prepare(app,url,invites):
    creds=[]; projects=[]
    with httpx.Client(base_url=url,headers={"X-InsightForge-Request":"1"}) as c:
        for i,invite in enumerate(invites):
            user={"username":f"ai-browser-{i}","password":"SYNTHETIC-only-passphrase!"}; assert c.post("/api/auth/claim",json={**user,"invite":invite}).status_code==201; assert c.post("/api/auth/login",json=user).status_code==200
            account=c.get("/api/auth/me").json()["id"]; p=c.post("/api/projects",json={"title":f"AI browser {i}","summary":"synthetic"}).json()["id"]; projects.append(p)
            db=app.state.workspace_pool.entries[account]["child"].state.async_generation_repository.db
            db.execute("""INSERT INTO idea_briefs(id,project_id,version,original_idea,target_user,problem,desired_outcome,known_resources_json,constraints_json,unknowns_json,provenance_json,confirmation_status,created_at) VALUES (?,?,1,?,?,?,?, '[]','[]','[]','{}','confirmed',?)""",(f"ai-browser-brief-{i}",p,"模糊的学生项目Idea","学生","如何开始验证","形成可交接草稿","2026-09-06T00:00:00+00:00"))
            c.post("/api/auth/logout"); creds.append({**user,"account":account})
    return creds,projects

with tempfile.TemporaryDirectory(prefix="insightforge-ai-browser-") as td:
    td=Path(td); os.environ["INSIGHTFORGE_DATABASE_PATH"]=str(td/"unused.sqlite3"); os.environ["RUNTIME_DIR"]=str(td/"unused-runtime")
    from app.config import Settings; from app.main import create_app; import uvicorn
    counter=td/"counts.json"; counter.write_text(json.dumps({"ai_reference":0,"evidence_guidance":0,"generation":0}))
    install_fake_transport(counter)
    app=create_app(seed=False,settings_override=Settings(accounts_enabled=True,accounts_dir=td/"accounts",beta_mode=True,beta_managed_mode=True,daily_user_limits_enabled=False,managed_qwen_api_key="TEST_ONLY_SYNTHETIC",managed_bailian_api_key="TEST_ONLY_SYNTHETIC"))
    listener=socket.socket(); listener.bind(("127.0.0.1",0)); port=listener.getsockname()[1]; server=uvicorn.Server(uvicorn.Config(app,log_level="warning",access_log=False)); thread=threading.Thread(target=server.run,kwargs={"sockets":[listener]},daemon=True); thread.start()
    try:
        for _ in range(200):
            if server.started: break
            time.sleep(.05)
        assert server.started
        creds,projects=prepare(app,f"http://127.0.0.1:{port}",[app.state.accounts.issue_invite() for _ in range(2)])
        env=os.environ.copy(); roots=list((Path.home()/".cache"/"codex-runtimes").glob("**/node_modules/playwright")); bins=list((Path.home()/".cache"/"codex-runtimes").glob("**/chromium-*/chrome-win64/chrome.exe"));
        if roots: env["PLAYWRIGHT_MODULE"]=str(roots[0])
        if bins: env["CHROMIUM_PATH"]=str(bins[0])
        data={"url":f"http://127.0.0.1:{port}","userA":creds[0],"userB":creds[1],"aiProject":projects[0],"zeroProject":projects[1]}
        result=subprocess.run(["node",str(ROOT/"tests/ai_reference_no_source_browser.cjs")],input=json.dumps(data),text=True,cwd=ROOT,env=env)
        counts=json.loads(counter.read_text()); assert result.returncode==0, "browser scenario failed"; assert counts["ai_reference"]==1, counts; assert counts["evidence_guidance"]==1, counts; assert not blocked,blocked
        print(f"AI/no-source Chromium flows executed; fake calls={counts}; real external connections=0; blocked attempts=0")
    finally:
        server.should_exit=True; thread.join(timeout=15); listener.close()
