"""Authenticated same-process workspace routing for the existing business app.

Each app's services and background worker use only its bound database/runtime.
Unclaimed legacy data is never mounted into a new account's app.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.account_registry import AccountRegistry

COOKIE = "insightforge_account"
STATIC = Path(__file__).parent / "static"


class WorkspacePool:
    """Single-process child lifespans, leased until the ASGI response completes.

    Idle means no request for 30 minutes AND no pending/running durable task.
    Uncertain RUNNING tasks deliberately prevent eviction; they are not retried.
    """

    def __init__(self, factory, busy, *, clock=time.monotonic, idle_seconds=1800):
        self.factory, self.busy = factory, busy
        self.clock, self.idle_seconds = clock, idle_seconds
        self.entries = {}
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def lease(self, account):
        key = account["id"]
        async with self.lock:
            if key not in self.entries:
                context = self.factory(account)
                child = await context.__aenter__()
                self.entries[key] = {"child": child, "context": context,
                                     "leases": 0, "last_used": self.clock()}
            entry = self.entries[key]
            entry["leases"] += 1
        try:
            yield entry["child"]
        finally:
            async with self.lock:
                entry["leases"] -= 1
                entry["last_used"] = self.clock()

    async def sweep(self):
        async with self.lock:
            for key, entry in list(self.entries.items()):
                if entry["leases"] or self.clock() - entry["last_used"] < self.idle_seconds:
                    continue
                # Failure to inspect durable state is fail-closed: retain the child.
                if await run_in_threadpool(self.busy, entry["child"]):
                    continue
                await entry["context"].__aexit__(None, None, None)
                del self.entries[key]

    async def close(self):
        async with self.lock:
            for entry in self.entries.values():
                await entry["context"].__aexit__(None, None, None)
            self.entries.clear()


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class Claim(Login):
    invite: str = Field(min_length=1, max_length=128)


def create_account_app(settings):
    @asynccontextmanager
    async def child_lifespan(account):
        from app.main import create_app
        child = create_app(seed=False, settings_override=replace(
            settings, accounts_enabled=False, database_path=Path(account["database_path"]),
            runtime_dir=Path(account["runtime_path"]), beta_participant_id=account["participant"],
            access_username=None, access_password=None))
        async with child.router.lifespan_context(child):
            yield child

    def has_work(child):
        with child.state.async_generation_repository.db.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM async_solution_generation_runs "
                "WHERE status IN ('PENDING','RUNNING') LIMIT 1"
            ).fetchone() is not None

    pool = WorkspacePool(child_lifespan, has_work)

    async def reap_idle():
        while True:
            await asyncio.sleep(30)
            try:
                await pool.sweep()
            except Exception:
                logging.getLogger(__name__).warning("Account idle cleanup deferred")

    @asynccontextmanager
    async def lifespan(app):
        app.state.accounts = AccountRegistry(settings.accounts_dir)
        app.state.workspace_pool = pool
        reaper = asyncio.create_task(reap_idle())
        try:
            yield
        finally:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper
            await pool.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Never reflect password, invite token or submitted values.
        return JSONResponse({"message": "请检查账号表单字段"}, status_code=422)

    @app.get("/login")
    def login_page():
        return FileResponse(STATIC / "account.html")

    @app.get("/account.js")
    def login_script():
        return FileResponse(STATIC / "account.js")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/auth/claim", status_code=201)
    def claim(payload: Claim):
        try:
            app.state.accounts.claim(payload.invite, payload.username, payload.password)
        except ValueError as exc:
            return JSONResponse({"message": str(exc)}, status_code=400)
        return {"message": "账号已创建，请登录"}

    @app.post("/api/auth/login")
    def login(payload: Login, request: Request):
        token = app.state.accounts.login(payload.username, payload.password)
        if not token:
            return JSONResponse({"message": "账号或密码不正确，或尝试过于频繁"}, status_code=401)
        app.state.accounts.logout(request.cookies.get(COOKIE, ""))
        response = JSONResponse({"authenticated": True})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                            secure=settings.beta_session_cookie_secure, path="/")
        return response

    @app.post("/api/auth/logout")
    def logout(request: Request):
        app.state.accounts.logout(request.cookies.get(COOKIE, ""))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/api/auth/me")
    def me(request: Request):
        return {"account_enabled": True, "username": request.state.account["username"],
                "id": request.state.account["id"]}

    @app.middleware("http")
    async def route_workspace(request, call_next):
        path = request.url.path
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if ((origin and origin != str(request.base_url).rstrip("/")) or
                    request.headers.get("x-insightforge-request") != "1"):
                return JSONResponse({"message": "请求来源校验失败，请刷新后操作"}, status_code=403)
        public = {"/login", "/account.js", "/api/health", "/api/auth/login", "/api/auth/claim", "/api/auth/logout"}
        if path in public:
            response = await call_next(request)
        else:
            account = await run_in_threadpool(app.state.accounts.session, request.cookies.get(COOKIE, ""))
            if account is None:
                return (JSONResponse({"message": "请先登录"}, status_code=401) if path.startswith("/api/")
                        else RedirectResponse("/login", status_code=303))
            request.state.account = account
            if path == "/api/auth/me":
                response = await call_next(request)
            else:
                # Dispatch through a mounted ASGI app, including streaming/download responses.
                # Never allow caller-supplied actor identity to become the audit header.
                request.scope["headers"] = [(k, v) for k, v in request.scope["headers"]
                                            if k.lower() not in {b"x-actor", b"authorization"}]
                request.scope["headers"].append((b"x-actor", account["id"].encode()))
                request.scope["workspace_account"] = account
                response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    async def workspace(scope, receive, send):
        async with pool.lease(scope["workspace_account"]) as child:
            await child(scope, receive, send)

    app.mount("/", workspace)
    return app
