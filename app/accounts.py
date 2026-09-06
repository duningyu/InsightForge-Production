"""Authenticated same-process workspace routing for the existing business app.

Each app's services and background worker use only its bound database/runtime.
Unclaimed legacy data is never mounted into a new account's app.
"""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
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


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class Claim(Login):
    invite: str = Field(min_length=1, max_length=128)


def create_account_app(settings):
    children = {}
    lock = asyncio.Lock()
    stack = AsyncExitStack()

    @asynccontextmanager
    async def lifespan(app):
        app.state.accounts = AccountRegistry(settings.accounts_dir)
        async with stack:
            yield
        children.clear()

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
                async with lock:
                    if account["id"] not in children:
                        from app.main import create_app
                        child = create_app(seed=False, settings_override=replace(
                            settings, accounts_enabled=False, database_path=Path(account["database_path"]),
                            runtime_dir=Path(account["runtime_path"]), beta_participant_id=account["participant"],
                            access_username=None, access_password=None))
                        await stack.enter_async_context(child.router.lifespan_context(child))
                        children[account["id"]] = child
                # Dispatch through a mounted ASGI app, including streaming/download responses.
                # Never allow caller-supplied actor identity to become the audit header.
                request.scope["headers"] = [(k, v) for k, v in request.scope["headers"]
                                            if k.lower() not in {b"x-actor", b"authorization"}]
                request.scope["headers"].append((b"x-actor", account["id"].encode()))
                request.scope["workspace_app"] = children[account["id"]]
                response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    async def workspace(scope, receive, send):
        await scope["workspace_app"](scope, receive, send)

    app.mount("/", workspace)
    return app
