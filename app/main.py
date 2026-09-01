from __future__ import annotations

import base64
import binascii
import json
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import Database
from app.exporters import ArtifactExporter
from app.ingestion import MAX_UPLOAD_BYTES
from app.schemas import (
    CanonicalExampleResponse,
    EvidenceAnalyzeRequest,
    ExampleCopyResponse,
    HumanConfirmRequest,
    IdeaBriefRefineRequest,
    QuickStartRequest,
    ApprovalRequest,
    WalkthroughAdvanceRequest,
    DocumentDraftSaveRequest,
    DocumentDraftCommitRequest,
    DocumentRestoreAsNewRequest,
    CanvasUpdateRequest,
    GenerateRequest,
    GuidedSourceCreateRequest,
    GuidedRespondRequest,
    HandoffExportRequest,
    ProjectCreateRequest,
    ModelProfileCreateRequest,
    ModelProfileResponse,
    ModelProfileUpdateRequest,
    LiveProviderTestRequest,
    LiveProviderTestResponse,
    ProjectModelProfileRequest,
    ProjectModelProfileResponse,
    RetrievalRequest,
    SourceCreateRequest,
    SolutionSelectRequest,
    BetaConsentRequest,
    BetaEventRequest,
    BetaFeedbackRequest,
)
from app.services.projects import ProjectService
from app.errors import (
    BetaDailyLimitReached,
    ConflictError,
    StructuredRuntimeRecoveryError,
    StructuredRuntimeUnavailableError,
)
from app.services.ai_runtime import build_structured_runtime
from app.services.quick_start import QuickStartService
from app.services.solution_design import SolutionDesignService
from app.services.decisions import DecisionService
from app.services.canvas_projection import CanvasProjectionService
from app.services.project_claims import ProjectClaimService
from app.services.snapshots import SnapshotService
from app.services.artifact_health import ArtifactHealthService
from app.services.change_proposals import ChangeProposalService
from app.services.impact import ImpactResolver
from app.services.document_versions import DocumentVersionService
from app.services.document_workspace import DocumentWorkspaceService
from app.services.walkthrough import WalkthroughService
from app.services.example_copies import ExampleCopyService
from app.services.example_projects import ExampleProjectSeeder
from app.services.legacy_migration import LegacyMigrationService
from app.services.guided_project import GuidedProjectService
from app.services.claims import ClaimService
from app.services.handoff import HandoffService
from app.services.beta_runtime import BetaInstanceContext
from app.services.beta_analytics import BetaAnalyticsService
from app.services.beta_feedback import BetaFeedbackService
from app.services.beta_sessions import BetaSessionService
from app.services.beta_usage import BetaUsageService
from app.services.retrieval_service import ProjectRetrievalService
from app.services.sources import SourceService
from app.services.generation import LLMDocumentGenerator, build_generator
from app.services.loop import DocumentLoop
from app.services.model_profiles import ModelProfileService
from app.services.guidance import GuidanceService
from app.services.hybrid_runtime import HybridStructuredRuntime
from app.services.credential_store import CredentialBackendUnavailable
from app.tools import ToolRegistry
from app.retrieval_profiles import list_retrieval_profiles

STATIC_DIR = Path(__file__).resolve().parent / "static"

_SENSITIVE_VALIDATION_LOCATIONS = {
    "api_key",
    "authorization",
    "credential",
    "credential_ref",
    "password",
    "secret",
}


def _sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove reflected credential input while preserving unrelated diagnostics."""

    def strip_sensitive_details(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: strip_sensitive_details(item)
                for key, item in value.items()
                if key not in {"input", "ctx"}
            }
        if isinstance(value, list):
            return [strip_sensitive_details(item) for item in value]
        if isinstance(value, tuple):
            return [strip_sensitive_details(item) for item in value]
        return value

    sanitized: list[dict[str, Any]] = []
    for error in errors:
        location = {
            str(part).strip().casefold() for part in error.get("loc", ())
        }
        sanitized.append(
            strip_sensitive_details(error)
            if location & _SENSITIVE_VALIDATION_LOCATIONS
            else dict(error)
        )
    return sanitized


def create_app(*, database_path: str | Path | None = None, seed: bool = True) -> FastAPI:
    settings = Settings.from_env()
    db = Database(database_path or settings.database_path)
    beta_context = BetaInstanceContext.from_settings(settings)

    def managed_settings_read_only() -> None:
        if settings.beta_mode and settings.beta_managed_mode:
            raise HTTPException(status_code=409, detail="MANAGED_MODEL_CONFIGURATION_READ_ONLY")

    def managed_profile() -> dict[str, Any]:
        return {
            "id": "managed_qwen",
            "display_name": "阿里云百炼官方 Qwen 服务",
            "provider": "qwen",
            "protocol": "openai_chat_completions",
            "base_url": settings.managed_qwen_base_url,
            "model_id": settings.managed_qwen_model,
            "credential_status": "configured" if settings.managed_qwen_api_key else "missing",
            "enabled": True,
            "is_default": True,
            "capabilities": {},
            "capabilities_checked_at": None,
            "last_test_status": None,
            "last_tested_at": None,
            "last_live_test_status": None,
            "last_live_tested_at": None,
            "last_live_latency_ms": None,
            "last_live_error_code": None,
            "last_live_model_returned": None,
            "revision": 1,
            "created_at": "managed",
            "updated_at": "managed",
        }

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        db.init_schema()
        if seed:
            db.seed_demo_data()
            ExampleProjectSeeder(db).seed()
        LegacyMigrationService(db).migrate_all()
        application.state.db = db
        application.state.settings = settings
        application.state.beta_context = beta_context
        application.state.beta_analytics = BetaAnalyticsService(
            db, participant_id=settings.beta_participant_id,
            release_id=settings.beta_release_id, beta_mode=settings.beta_mode,
            consent_version=settings.beta_consent_version,
        )
        application.state.beta_feedback = BetaFeedbackService(
            db,
            application.state.beta_analytics,
            participant_id=settings.beta_participant_id,
            release_id=settings.beta_release_id,
            beta_mode=settings.beta_mode,
        )
        application.state.beta_usage = BetaUsageService(
            db,
            participant_id=settings.beta_participant_id,
            beta_mode=settings.beta_mode,
            timezone_name=settings.beta_timezone,
            limits=(
                {"solution_generation": 3, "document_generation": 3, "evidence_analysis": 5}
                if settings.beta_managed_mode
                else None
            ),
        )
        if settings.beta_mode:
            application.state.beta_sessions = BetaSessionService(
                db,
                participant_id=settings.beta_participant_id or "",
                release_id=settings.beta_release_id,
                idle_timeout_minutes=settings.beta_session_idle_timeout_minutes,
            )
        application.state.projects = ProjectService(db)
        application.state.example_copies = ExampleCopyService(db)
        application.state.model_profiles = ModelProfileService(db)
        application.state.guidance = GuidanceService(db)
        application.state.structured_runtime = HybridStructuredRuntime(
            application.state.model_profiles,
            local_runtime=build_structured_runtime(
                mode="deterministic_demo", model=settings.openai_model
            ),
            before_provider_call=application.state.beta_usage.consume,
            managed_runtime=(
                build_structured_runtime(
                    mode="managed_qwen",
                    model=settings.managed_qwen_model,
                    api_key=settings.managed_qwen_api_key,
                    base_url=settings.managed_qwen_base_url,
                    before_provider_call=application.state.beta_usage.consume,
                )
                if settings.beta_mode and settings.beta_managed_mode
                else None
            ),
        )
        application.state.quick_start = QuickStartService(
            db, application.state.projects, application.state.structured_runtime
        )
        application.state.solution_design = SolutionDesignService(
            db, application.state.structured_runtime
        )
        application.state.decisions = DecisionService()
        application.state.retrieval = ProjectRetrievalService(db)
        application.state.project_claims = ProjectClaimService(
            db=db,
            retrieval=application.state.retrieval,
            runtime=application.state.structured_runtime,
        )
        application.state.canvas_projection = CanvasProjectionService()
        application.state.artifact_health = ArtifactHealthService(db)
        application.state.snapshots = SnapshotService(
            db,
            application.state.projects,
            application.state.decisions,
            application.state.project_claims,
            application.state.canvas_projection,
            application.state.artifact_health,
        )
        application.state.change_proposals = ChangeProposalService(db, application.state.snapshots)
        application.state.impact = ImpactResolver(
            db, application.state.artifact_health, application.state.change_proposals
        )
        application.state.project_claims.impact_resolver = application.state.impact
        application.state.document_versions = DocumentVersionService(db)
        application.state.document_workspace = DocumentWorkspaceService(db)
        application.state.walkthrough = WalkthroughService(db)
        application.state.guided = GuidedProjectService(db, application.state.projects)
        application.state.claims = ClaimService(db)
        application.state.handoff = HandoffService(db)
        application.state.sources = SourceService(
            db, application.state.project_claims, application.state.impact
        )
        generator = build_generator()
        application.state.generator = generator
        application.state.document_loop = DocumentLoop(
            db, generator=generator, max_rounds=settings.max_loop_rounds
        )
        application.state.tools = ToolRegistry(
            db,
            generator=generator,
            max_loop_rounds=settings.max_loop_rounds,
            structured_runtime=application.state.structured_runtime,
        )
        application.state.llm_mode = "llm" if isinstance(generator, LLMDocumentGenerator) else "local"
        yield

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Project-scoped knowledge base with cited PRD/TechDoc generation, "
            "bounded validation, source governance, and human approval."
        ),
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def beta_session_middleware(request: Request, call_next):
        if not settings.beta_mode:
            return await call_next(request)
        resolution = application.state.beta_sessions.resolve(
            request.cookies.get("insightforge_beta_session")
        )
        request.state.beta_session_id = resolution.session_id
        if resolution.created and application.state.beta_analytics.has_consent():
            application.state.beta_analytics.record_session_started_once(resolution.session_id)
        response = await call_next(request)
        if resolution.created:
            response.set_cookie(
                "insightforge_beta_session",
                resolution.session_id,
                httponly=True,
                samesite="lax",
                secure=settings.beta_session_cookie_secure,
                max_age=60 * 60 * 24 * 30,
            )
        return response

    if settings.access_username and settings.access_password:
        @application.middleware("http")
        async def require_basic_auth(request: Request, call_next):
            if request.url.path == "/api/health":
                return await call_next(request)
            authorization = request.headers.get("Authorization", "")
            authenticated = False
            if authorization.startswith("Basic "):
                try:
                    raw = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
                    username, password = raw.split(":", 1)
                    authenticated = secrets.compare_digest(
                        username, settings.access_username
                    ) and secrets.compare_digest(password, settings.access_password)
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    authenticated = False
            if not authenticated:
                return Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="InsightForge", charset="UTF-8"'},
                )
            return await call_next(request)

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = _sanitize_validation_errors(exc.errors())
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(errors)},
        )

    @application.exception_handler(KeyError)
    async def key_error_handler(_request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'")})

    @application.exception_handler(PermissionError)
    async def permission_error_handler(_request, exc: PermissionError):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @application.exception_handler(ConflictError)
    async def conflict_error_handler(_request, exc: ConflictError):
        detail = str(exc)
        if detail.startswith("IDEA_BRIEF_REQUIRED"):
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "生成方案前还需要完善并确认项目定义。",
                    "code": "IDEA_BRIEF_REQUIRED",
                    "action": "open_idea_brief",
                },
            )
        if detail == "IDEA_BRIEF_NOT_CONFIRMED":
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "请先查看并确认项目定义，再生成方案。",
                    "code": "IDEA_BRIEF_NOT_CONFIRMED",
                    "action": "open_idea_brief",
                },
            )
        if detail == "SOLUTION_GENERATION_NO_VALID_CANDIDATES":
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "这次没有生成可用方案，你的项目内容已经保留，请重新生成。",
                    "code": "SOLUTION_GENERATION_NO_VALID_CANDIDATES",
                    "action": "retry_solution_generation",
                },
            )
        return JSONResponse(status_code=409, content={"detail": detail})

    @application.exception_handler(BetaDailyLimitReached)
    async def beta_daily_limit_handler(_request, exc: BetaDailyLimitReached):
        return JSONResponse(status_code=429, content=exc.as_payload())

    @application.exception_handler(StructuredRuntimeUnavailableError)
    async def structured_runtime_error_handler(_request, exc: StructuredRuntimeUnavailableError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @application.exception_handler(StructuredRuntimeRecoveryError)
    async def structured_runtime_recovery_handler(
        _request, exc: StructuredRuntimeRecoveryError
    ):
        return JSONResponse(status_code=503, content=exc.as_payload())

    @application.exception_handler(CredentialBackendUnavailable)
    async def credential_backend_error_handler(_request, _exc: CredentialBackendUnavailable):
        return JSONResponse(
            status_code=503,
            content={"detail": "Credential storage is unavailable."},
        )

    @application.exception_handler(ValueError)
    async def value_error_handler(_request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.app_version,
            "mode": "local_project_rag",
            "llm_mode": getattr(application.state, "llm_mode", "local"),
            "structured_runtime_mode": getattr(application.state.structured_runtime, "mode", None),
            "max_loop_rounds": settings.max_loop_rounds,
            "beta_mode": settings.beta_mode,
            "beta_release_id": settings.beta_release_id,
            "participant_id": settings.beta_participant_id if settings.beta_mode else None,
        }

    @application.get("/api/beta/consent")
    def beta_consent_status() -> dict[str, Any]:
        analytics = application.state.beta_analytics
        return {"beta_mode": settings.beta_mode, "consented": analytics.has_consent(), "consent_version": settings.beta_consent_version}

    @application.post("/api/beta/consent")
    def beta_consent(payload: BetaConsentRequest, request: Request) -> dict[str, Any]:
        result = application.state.beta_analytics.consent(**payload.model_dump())
        application.state.beta_analytics.record_session_started_once(request.state.beta_session_id)
        return result

    @application.post("/api/beta/events")
    def beta_event(payload: BetaEventRequest, request: Request) -> dict[str, Any]:
        if not settings.beta_mode:
            return {"recorded": False, "reason": "not_beta"}
        return application.state.beta_analytics.record(
            payload.event_name, payload.properties,
            session_id=request.state.beta_session_id, project_id=payload.project_id,
        )

    @application.post("/api/beta/feedback", status_code=201)
    def beta_feedback(payload: BetaFeedbackRequest, request: Request) -> dict[str, Any]:
        return application.state.beta_feedback.submit(
            **payload.model_dump(),
            session_id=getattr(request.state, "beta_session_id", ""),
        )

    def record_product_event(request: Request, event_name: str, properties: dict[str, Any] | None = None, *, project_id: str | None = None) -> None:
        if settings.beta_mode:
            application.state.beta_analytics.record_safe(
                event_name, properties or {}, session_id=request.state.beta_session_id,
                project_id=project_id,
            )

    def idea_length_bucket(length: int) -> str:
        if length <= 20: return "0_20"
        if length <= 50: return "21_50"
        if length <= 100: return "51_100"
        if length <= 200: return "101_200"
        return "200_plus"

    def size_bucket(size: int) -> str:
        if size <= 1_000: return "0_1kb"
        if size <= 10_000: return "1_10kb"
        if size <= 100_000: return "10_100kb"
        return "100kb_plus"

    @application.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return application.state.projects.list_projects()

    @application.get("/api/examples", response_model=list[CanonicalExampleResponse])
    def list_canonical_examples() -> list[dict[str, Any]]:
        return application.state.example_copies.list_examples()

    @application.post(
        "/api/examples/{example_id}/copies",
        status_code=201,
        response_model=ExampleCopyResponse,
    )
    def copy_canonical_example(
        example_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.example_copies.copy(example_id, actor=x_actor)

    @application.get("/api/home/next-action")
    def home_next_action() -> dict[str, str]:
        return application.state.guidance.home_next_action()

    @application.get("/api/projects/{project_id}/next-action")
    def project_next_action(project_id: str) -> dict[str, str]:
        return application.state.guidance.project_next_action(project_id)

    @application.get(
        "/api/settings/model-profiles", response_model=list[ModelProfileResponse]
    )
    def list_model_profiles() -> list[dict[str, Any]]:
        if settings.beta_mode and settings.beta_managed_mode:
            return [managed_profile()]
        return application.state.model_profiles.list()

    @application.get("/api/settings/mode")
    def get_settings_mode() -> dict[str, Any]:
        return {
            "managed_beta_mode": settings.beta_mode and settings.beta_managed_mode,
            "provider": "qwen" if settings.beta_mode and settings.beta_managed_mode else None,
            "model": settings.managed_qwen_model if settings.beta_mode and settings.beta_managed_mode else None,
            "status": (
                "configured" if settings.managed_qwen_api_key else "missing"
            ) if settings.beta_mode and settings.beta_managed_mode else "local",
        }

    @application.post(
        "/api/settings/model-profiles", status_code=201, response_model=ModelProfileResponse
    )
    def create_model_profile(
        payload: ModelProfileCreateRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        managed_settings_read_only()
        return application.state.model_profiles.create(
            display_name=payload.display_name,
            provider=payload.provider,
            protocol=payload.protocol,
            base_url=payload.base_url,
            model_id=payload.model_id,
            api_key=payload.api_key.get_secret_value() if payload.api_key is not None else None,
            enabled=payload.enabled,
            is_default=payload.is_default,
            actor=x_actor,
        )

    @application.patch(
        "/api/settings/model-profiles/{profile_id}", response_model=ModelProfileResponse
    )
    def update_model_profile(
        profile_id: str,
        payload: ModelProfileUpdateRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        managed_settings_read_only()
        changes = payload.model_dump(exclude_unset=True)
        if "api_key" in changes and changes["api_key"] is not None:
            changes["api_key"] = changes["api_key"].get_secret_value()
        return application.state.model_profiles.update(
            profile_id, changes=changes, actor=x_actor
        )

    @application.delete("/api/settings/model-profiles/{profile_id}", status_code=204)
    def delete_model_profile(
        profile_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> Response:
        managed_settings_read_only()
        application.state.model_profiles.delete(profile_id, actor=x_actor)
        return Response(status_code=204)

    @application.post(
        "/api/settings/model-profiles/{profile_id}/test", response_model=ModelProfileResponse
    )
    def test_model_profile_connection(
        profile_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        managed_settings_read_only()
        return application.state.model_profiles.test_connection(profile_id, actor=x_actor)


    @application.post(
        "/api/settings/model-profiles/{profile_id}/live-test",
        response_model=LiveProviderTestResponse,
    )
    def live_test_model_profile_connection(
        profile_id: str,
        payload: LiveProviderTestRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        managed_settings_read_only()
        return application.state.model_profiles.live_test_connection(
            profile_id, actor=x_actor
        )

    @application.post(
        "/api/settings/model-profiles/{profile_id}/set-default",
        response_model=ModelProfileResponse,
    )
    def set_default_model_profile(
        profile_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        managed_settings_read_only()
        return application.state.model_profiles.set_default(profile_id, actor=x_actor)

    @application.get(
        "/api/projects/{project_id}/model-profile",
        response_model=ProjectModelProfileResponse,
    )
    def get_project_model_profile(project_id: str) -> dict[str, Any]:
        return application.state.model_profiles.get_project_override(project_id)

    @application.put(
        "/api/projects/{project_id}/model-profile",
        response_model=ProjectModelProfileResponse,
    )
    def set_project_model_profile(
        project_id: str,
        payload: ProjectModelProfileRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        managed_settings_read_only()
        return application.state.model_profiles.set_project_override(
            project_id, payload.profile_id, actor=x_actor
        )

    @application.post("/api/projects", status_code=201)
    def create_project(
        payload: ProjectCreateRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.projects.create_project(
            title=payload.title,
            summary=payload.summary,
            actor=x_actor,
        )

    @application.post("/api/projects/quick-start", status_code=201)
    def quick_start_project(
        payload: QuickStartRequest,
        request: Request,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        result = application.state.quick_start.quick_start(payload, actor=x_actor)
        if result.get("project_id"):
            record_product_event(request, "idea_submitted", {"idea_length_bucket": idea_length_bucket(len(payload.idea))}, project_id=result["project_id"])
        return result

    @application.get("/api/projects/history")
    def project_history(
        q: str = Query(default="", max_length=300),
        status: str = Query(default="all", pattern="^(all|active|example|trashed)$"),
        sort: str = Query(default="updated_at", pattern="^(updated_at|created_at|title)$"),
        order: str = Query(default="desc", pattern="^(asc|desc)$"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        return application.state.projects.history(
            query=q, status=status, sort=sort, order=order, page=page, page_size=page_size
        )

    @application.get("/api/projects/trash")
    def list_trashed_projects() -> list[dict[str, Any]]:
        return application.state.projects.list_trashed_projects()

    @application.post("/api/projects/{project_id}/trash")
    def trash_project(
        project_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.projects.move_to_trash(project_id, actor=x_actor)

    @application.post("/api/projects/{project_id}/restore")
    def restore_project(
        project_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.projects.restore_from_trash(project_id, actor=x_actor)

    @application.delete("/api/projects/{project_id}")
    def permanently_delete_project(
        project_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.projects.purge_from_trash(project_id, actor=x_actor)

    @application.post("/api/projects/{project_id}/copy", status_code=201)
    def copy_project(
        project_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.example_copies.copy_project(project_id, actor=x_actor)

    @application.get("/api/projects/{project_id}/walkthrough")
    def get_walkthrough(project_id: str) -> dict[str, Any]:
        return application.state.walkthrough.get(project_id)

    @application.post("/api/projects/{project_id}/walkthrough/start")
    def start_walkthrough(project_id: str, request: Request) -> dict[str, Any]:
        result = application.state.walkthrough.start(project_id)
        record_product_event(request, "walkthrough_started", {}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/walkthrough/advance")
    def advance_walkthrough(project_id: str, payload: WalkthroughAdvanceRequest, request: Request) -> dict[str, Any]:
        result = application.state.walkthrough.advance(project_id, payload.step)
        step_no = ["idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"].index(payload.step) + 1
        record_product_event(request, "walkthrough_step_completed", {"step_no": step_no}, project_id=project_id)
        if result.get("status") == "completed":
            record_product_event(request, "walkthrough_completed", {}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/walkthrough/skip")
    def skip_walkthrough(project_id: str, request: Request) -> dict[str, Any]:
        before = application.state.walkthrough.get(project_id)
        result = application.state.walkthrough.skip(project_id)
        step = before.get("current_step")
        step_no = ["idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"].index(step) + 1 if step in {"idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"} else 1
        record_product_event(request, "walkthrough_skipped", {"step_no": step_no}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/walkthrough/restart")
    def restart_walkthrough(project_id: str, request: Request) -> dict[str, Any]:
        result = application.state.walkthrough.restart(project_id)
        record_product_event(request, "walkthrough_restarted", {}, project_id=project_id)
        return result

    @application.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return application.state.projects.get_project_detail(project_id)

    @application.get("/api/projects/{project_id}/idea-brief")
    def get_idea_brief(project_id: str) -> dict[str, Any]:
        return application.state.quick_start.get_brief(project_id)

    @application.post("/api/projects/{project_id}/idea-brief/confirm")
    def confirm_idea_brief(
        project_id: str,
        payload: HumanConfirmRequest,
        request: Request,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        result = application.state.quick_start.confirm_brief(
            project_id,
            human_confirmed=payload.human_confirmed,
            note=payload.note,
            actor=x_actor,
        )
        record_product_event(request, "idea_brief_confirmed", {}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/idea-brief/refine")
    def refine_idea_brief(
        project_id: str,
        payload: IdeaBriefRefineRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.quick_start.refine_brief(project_id, payload, actor=x_actor)

    @application.post("/api/projects/{project_id}/solutions/generate", status_code=201)
    def generate_solutions(
        project_id: str,
        request: Request,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        result = application.state.solution_design.generate(project_id, actor=x_actor)
        candidates = result.get("candidates") or []
        if "error_code" in result and not candidates:
            return JSONResponse(status_code=503, content=result)
        if not candidates:
            return JSONResponse(
                status_code=503,
                content={
                    "error_code": "SOLUTION_GENERATION_NO_VALID_CANDIDATES",
                    "message": "这次没有生成可用方案，你的项目内容已经保留，请重新生成。",
                    "recovery_actions": ["重新生成"],
                    "preserved_input": None,
                },
            )
        record_product_event(request, "solutions_generated", {"solution_count": len(candidates), "mechanisms": [item["mechanism"] for item in candidates]}, project_id=project_id)
        return result

    @application.get("/api/projects/{project_id}/solutions")
    def list_solutions(project_id: str) -> dict[str, Any]:
        return application.state.solution_design.list_candidates(project_id)

    @application.post("/api/projects/{project_id}/solutions/select", status_code=201)
    def select_solution(
        project_id: str,
        payload: SolutionSelectRequest,
        request: Request,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        result = application.state.snapshots.confirm_initial_solution(
            project_id,
            strategy=payload.strategy,
            candidate_ids=payload.candidate_ids,
            rationale=payload.rationale,
            human_confirmed=payload.human_confirmed,
            actor=x_actor,
        )
        record_product_event(request, "solution_selected", {"mechanism": result["solution"]["mechanism"], "selection_strategy": "staged" if payload.strategy == "staged" else "manual"}, project_id=project_id)
        record_product_event(request, "snapshot_created", {"snapshot_version": result["version"]}, project_id=project_id)
        return result

    @application.get("/api/projects/{project_id}/claims")
    def list_project_claims(project_id: str) -> list[dict[str, Any]]:
        return application.state.project_claims.list_claims(project_id)

    @application.get("/api/projects/{project_id}/claims/{claim_id}")
    def get_project_claim(project_id: str, claim_id: str) -> dict[str, Any]:
        return application.state.project_claims.get_claim(project_id, claim_id)

    @application.post("/api/projects/{project_id}/evidence/analyze")
    def analyze_project_evidence(
        project_id: str,
        payload: EvidenceAnalyzeRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.project_claims.analyze_project_evidence(
            project_id, claim_ids=payload.claim_ids, actor=x_actor
        )

    @application.get("/api/projects/{project_id}/evidence/impact")
    def project_evidence_impact(project_id: str) -> dict[str, Any]:
        summary = application.state.project_claims.impact_summary(project_id)
        summary["change_proposals"] = application.state.change_proposals.list_for_project(project_id)
        return summary

    @application.get("/api/projects/{project_id}/change-proposals")
    def list_change_proposals(project_id: str) -> list[dict[str, Any]]:
        return application.state.change_proposals.list_for_project(project_id)

    @application.post("/api/change-proposals/{proposal_id}/accept")
    def accept_change_proposal(
        proposal_id: str,
        payload: HumanConfirmRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.change_proposals.accept(
            proposal_id,
            human_confirmed=payload.human_confirmed,
            note=payload.note,
            actor=x_actor,
        )

    @application.post("/api/change-proposals/{proposal_id}/reject")
    def reject_change_proposal(
        proposal_id: str,
        payload: HumanConfirmRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.change_proposals.reject(
            proposal_id,
            human_confirmed=payload.human_confirmed,
            note=payload.note,
            actor=x_actor,
        )

    @application.post("/api/change-proposals/{proposal_id}/defer")
    def defer_change_proposal(
        proposal_id: str,
        payload: HumanConfirmRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.change_proposals.defer(
            proposal_id,
            human_confirmed=payload.human_confirmed,
            note=payload.note,
            actor=x_actor,
        )

    @application.get("/api/projects/{project_id}/snapshot")
    def get_current_snapshot(project_id: str) -> dict[str, Any]:
        return application.state.snapshots.get_current(project_id)

    @application.post("/api/projects/{project_id}/snapshot/reconfirm")
    def reconfirm_current_snapshot_health(
        project_id: str,
        payload: HumanConfirmRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.snapshots.reconfirm_current_health(
            project_id,
            human_confirmed=payload.human_confirmed,
            note=payload.note,
            actor=x_actor,
        )

    @application.get("/api/projects/{project_id}/snapshots")
    def list_project_snapshots(project_id: str) -> list[dict[str, Any]]:
        return application.state.snapshots.list_versions(project_id)

    @application.get("/api/project-snapshots/{snapshot_id}")
    def get_project_snapshot(snapshot_id: str) -> dict[str, Any]:
        return application.state.snapshots.get(snapshot_id)

    @application.get("/api/projects/{project_id}/canvas")
    def get_canvas(project_id: str) -> dict[str, Any]:
        return application.state.projects.get_canvas(project_id)

    @application.get("/api/projects/{project_id}/guide", deprecated=True)
    def get_guided_state(project_id: str) -> dict[str, Any]:
        return application.state.guided.get_state(project_id)

    @application.post("/api/projects/{project_id}/guide/respond", deprecated=True)
    def respond_to_guide(
        project_id: str,
        payload: GuidedRespondRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.guided.respond(
            project_id,
            answer=payload.answer,
            choice_id=payload.choice_id,
            actor=x_actor,
        )

    @application.post("/api/projects/{project_id}/guide/apply", deprecated=True)
    def apply_guided_canvas(
        project_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.guided.apply_canvas(project_id, actor=x_actor)

    @application.post("/api/projects/{project_id}/guide/reset", deprecated=True)
    def reset_guided_state(
        project_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.guided.reset(project_id, actor=x_actor)

    @application.post("/api/projects/{project_id}/guide/back", deprecated=True)
    def go_back_in_guided_state(
        project_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.guided.go_back(project_id, actor=x_actor)

    @application.get("/api/projects/{project_id}/solution-proposals")
    def get_solution_proposals(project_id: str) -> dict[str, Any]:
        return application.state.guided.solution_proposals(project_id)

    @application.put("/api/projects/{project_id}/canvas")
    def update_canvas(
        project_id: str,
        payload: CanvasUpdateRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.projects.update_canvas(
            project_id,
            **payload.model_dump(),
            actor=x_actor,
        )

    @application.get("/api/source-guidance")
    def source_guidance() -> list[dict[str, Any]]:
        return application.state.sources.guidance.describe_categories()

    @application.post("/api/projects/{project_id}/sources/guided", status_code=201)
    def add_guided_source(
        project_id: str,
        payload: GuidedSourceCreateRequest,
    ) -> dict[str, Any]:
        application.state.projects.get_project(project_id)
        return application.state.sources.add_guided_source(
            project_id=project_id,
            **payload.model_dump(),
        )

    @application.get("/api/projects/{project_id}/sources")
    def list_sources(project_id: str) -> list[dict[str, Any]]:
        application.state.projects.get_project(project_id)
        return application.state.sources.list_sources(project_id)

    @application.post("/api/projects/{project_id}/sources/{source_id}/archive")
    def archive_source(
        project_id: str,
        source_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.sources.archive(project_id, source_id, actor=x_actor)

    @application.post("/api/projects/{project_id}/sources/{source_id}/restore")
    def restore_source(
        project_id: str,
        source_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.sources.restore(project_id, source_id, actor=x_actor)

    @application.post("/api/projects/{project_id}/sources", status_code=201)
    def add_source(
        project_id: str,
        payload: SourceCreateRequest,
        request: Request,
    ) -> dict[str, Any]:
        result = application.state.sources.add_source(
            project_id=project_id,
            **payload.model_dump(),
        )
        record_product_event(request, "evidence_added", {"source_type": payload.source_type, "file_type": Path(payload.filename or "text.txt").suffix.lower().lstrip(".") or "text", "size_bucket": size_bucket(len(payload.content.encode("utf-8")))}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/sources/upload", status_code=201)
    async def upload_source(
        project_id: str,
        request: Request,
        title: str = Form(..., min_length=1, max_length=200),
        source_type: str = Form(...),
        authority: float = Form(..., ge=0, le=1),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise ValueError(f"file exceeds {MAX_UPLOAD_BYTES} bytes")
            chunks.append(chunk)
        data = b"".join(chunks)
        result = application.state.sources.add_uploaded_source(
            project_id=project_id,
            title=title,
            source_type=source_type,
            authority=authority,
            filename=file.filename or "source.txt",
            data=data,
        )
        record_product_event(request, "evidence_added", {"source_type": source_type, "file_type": Path(file.filename or "file").suffix.lower().lstrip(".") or "unknown", "size_bucket": size_bucket(total)}, project_id=project_id)
        return result

    @application.get("/api/retrieval/profiles")
    def retrieval_profiles() -> list[dict[str, Any]]:
        return list_retrieval_profiles()

    @application.post("/api/projects/{project_id}/retrieve")
    def retrieve(
        project_id: str,
        payload: RetrievalRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        result = application.state.retrieval.execute_retrieval(
            project_id,
            payload.query,
            profile_id=payload.profile_id,
            top_k=payload.top_k,
            source_types=list(payload.source_types or []),
            purpose="advanced_manual_search",
            actor=x_actor,
        )
        db.insert_audit(
            actor=x_actor,
            action="retrieval_run_created",
            entity_type="retrieval_run",
            entity_id=result["run_id"],
            payload={
                "project_id": project_id,
                "profile_id": payload.profile_id,
                "purpose": "advanced_manual_search",
            },
        )
        return result

    @application.get("/api/projects/{project_id}/retrieval-runs")
    def list_retrieval_runs(
        project_id: str,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return application.state.retrieval.list_runs(project_id, limit=limit)

    @application.get("/api/retrieval/runs/{run_id}")
    def get_retrieval_run(run_id: str) -> dict[str, Any]:
        return application.state.retrieval.get_run(run_id)

    @application.post("/api/projects/{project_id}/documents/generate")
    def generate_snapshot_aware_document(
        project_id: str,
        payload: GenerateRequest,
        request: Request,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        key = payload.idempotency_key or f"v3:{project_id}:{payload.doc_type}:{uuid.uuid4().hex}"
        result = application.state.document_loop.run(
            project_id, payload.doc_type, idempotency_key=key, require_snapshot=True
        )
        event_name = "prd_generated" if payload.doc_type == "prd" else "techdoc_generated"
        record_product_event(request, event_name, {"doc_type": payload.doc_type, "generation_status": "succeeded"}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/generate")
    def generate(
        project_id: str,
        payload: GenerateRequest,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        key = payload.idempotency_key or f"api:{project_id}:{payload.doc_type}:{uuid.uuid4().hex}"
        return application.state.tools.execute(
            "create_document_draft",
            {
                "project_id": project_id,
                "doc_type": payload.doc_type,
                "idempotency_key": key,
            },
            actor=x_actor,
            human_confirmed=True,
        )

    @application.get("/api/projects/{project_id}/documents/{doc_type}/versions")
    def list_document_versions(project_id: str, doc_type: str) -> list[dict[str, Any]]:
        return application.state.document_workspace.list_versions(project_id, doc_type)

    @application.get("/api/projects/{project_id}/documents/{doc_type}/draft")
    def get_document_edit_draft(project_id: str, doc_type: str) -> dict[str, Any]:
        return application.state.document_workspace.get_draft(project_id, doc_type)

    @application.put("/api/projects/{project_id}/documents/{doc_type}/draft")
    def save_document_edit_draft(
        project_id: str,
        doc_type: str,
        payload: DocumentDraftSaveRequest,
        request: Request,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        try:
            before = application.state.document_workspace.get_draft(project_id, doc_type)
        except KeyError:
            before = {"content": ""}
        result = application.state.document_workspace.save_draft(
            project_id, doc_type, base_version_id=payload.base_version_id,
            content=payload.content, actor=x_actor
        )
        if doc_type == "prd":
            before_length = len(before.get("content") or "")
            after_length = len(payload.content)
            record_product_event(request, "prd_draft_saved", {"doc_type": "prd", "chars_before": before_length, "chars_after": after_length, "chars_added": max(0, after_length-before_length), "chars_removed": max(0, before_length-after_length)}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/documents/{doc_type}/draft/commit", status_code=201)
    def commit_document_edit_draft(
        project_id: str, doc_type: str, payload: DocumentDraftCommitRequest
    ) -> dict[str, Any]:
        return application.state.document_workspace.commit_draft(
            project_id,
            doc_type,
            actor=payload.actor,
            note=payload.note,
            expected_base_version_id=payload.expected_base_version_id,
        )

    @application.get("/api/documents/diff")
    def diff_document_versions(
        from_version_id: str = Query(min_length=1, max_length=200),
        to_version_id: str = Query(min_length=1, max_length=200),
    ) -> dict[str, Any]:
        return application.state.document_workspace.diff(from_version_id, to_version_id)

    @application.post("/api/documents/{version_id}/restore-as-new", status_code=201)
    def restore_document_as_new(
        version_id: str, payload: DocumentRestoreAsNewRequest
    ) -> dict[str, Any]:
        return application.state.document_workspace.restore_as_new(
            version_id, actor=payload.actor, note=payload.note
        )

    @application.get("/api/documents/{version_id}")
    def get_document_version(version_id: str) -> dict[str, Any]:
        return application.state.tools.execute(
            "get_document_version",
            {"version_id": version_id},
            actor="web_user",
        )

    @application.get("/api/documents/{version_id}/claims")
    def get_document_claims(version_id: str) -> dict[str, Any]:
        return application.state.claims.list_for_version(version_id)

    @application.get("/api/projects/{project_id}/documents/trash")
    def list_trashed_document_versions(project_id: str) -> list[dict[str, Any]]:
        application.state.projects.get_project(project_id)
        return application.state.document_versions.list_trashed(project_id)

    @application.post("/api/documents/{version_id}/trash")
    def trash_document_version(
        version_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.document_versions.move_to_trash(version_id, actor=x_actor)

    @application.post("/api/documents/{version_id}/restore")
    def restore_document_version(
        version_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.document_versions.restore_from_trash(version_id, actor=x_actor)

    @application.delete("/api/documents/{version_id}")
    def permanently_delete_document_version(
        version_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.document_versions.purge_from_trash(version_id, actor=x_actor)

    @application.get("/api/projects/{project_id}/handoff/readiness")
    def get_handoff_readiness(project_id: str, request: Request) -> dict[str, Any]:
        result = application.state.handoff.readiness(project_id)
        record_product_event(request, "handoff_opened", {"handoff_type": "codex"}, project_id=project_id)
        return result

    @application.post("/api/projects/{project_id}/handoff/export")
    def export_handoff(
        project_id: str,
        payload: HandoffExportRequest,
        request: Request,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> Response:
        data, manifest = application.state.handoff.build_zip(
            project_id,
            target_client=payload.target_client,
            actor=x_actor,
        )
        record_product_event(request, "handoff_exported", {"format": "zip", "handoff_type": payload.target_client}, project_id=project_id)
        filename = f"InsightForge_Handoff_{project_id}_{payload.target_client}.zip"
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Handoff-SHA256": manifest["package_sha256"],
                "X-Handoff-Run-ID": manifest["handoff_run_id"],
            },
        )

    @application.post("/api/documents/{version_id}/validate")
    def validate_document(
        version_id: str,
        x_actor: str = Header(default="web_user", alias="X-Actor"),
    ) -> dict[str, Any]:
        return application.state.tools.execute(
            "run_document_validator",
            {"version_id": version_id},
            actor=x_actor,
            human_confirmed=True,
        )

    @application.post("/api/document-versions/{version_id}/confirm")
    def confirm_document(version_id: str, payload: ApprovalRequest, request: Request) -> dict[str, Any]:
        result = application.state.document_versions.confirm(
            version_id, actor=payload.actor, note=payload.note, human_confirmed=payload.human_confirmed
        )
        if result.get("doc_type") == "prd":
            record_product_event(request, "prd_version_confirmed", {"doc_type": "prd", "version_no": result.get("version", 1)}, project_id=result.get("project_id"))
        return result

    @application.post("/api/documents/{version_id}/approve", deprecated=True)
    def approve_document(version_id: str, payload: ApprovalRequest) -> dict[str, Any]:
        return application.state.document_versions.confirm(
            version_id, actor=payload.actor, note=payload.note, human_confirmed=payload.human_confirmed
        )

    @application.get("/api/documents/{version_id}/export")
    def export_document(
        version_id: str,
        format: str = Query(default="md", pattern="^(md|json|docx)$"),
    ) -> Response:
        version = application.state.tools.execute(
            "get_document_version",
            {"version_id": version_id},
            actor="web_user",
        )
        exporter = ArtifactExporter()
        basename = f"{version['doc_type']}_v{version['version']}"
        if format == "md":
            return Response(
                content=exporter.to_markdown(version),
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{basename}.md"'},
            )
        if format == "json":
            return Response(
                content=exporter.to_json_bytes(version),
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{basename}.json"'},
            )
        return Response(
            content=exporter.to_docx_bytes(version),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{basename}.docx"'},
        )

    @application.get("/api/audit")
    def audit(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        rows = db.fetch_all(
            "SELECT * FROM audit_events ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    @application.get("/api/tools")
    def tools() -> list[dict[str, Any]]:
        return application.state.tools.schemas()

    return application


app = create_app()
