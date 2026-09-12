from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import httpx

from app.schemas import IdeaBriefDraft, QuickStartRequest, SolutionSetDraft
from app.services.ai_runtime import DeterministicDemoRuntime
from app.services.credential_store import CredentialStore
from app.services.model_profiles import ModelProfileService
from app.services.projects import ProjectService
from app.services.provider_adapters import ProviderCallError
from app.services.quick_start import QuickStartService
from app.services.solution_design import SolutionDesignService


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"


class MemoryCredentialBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def _brief(idea: str) -> IdeaBriefDraft:
    return IdeaBriefDraft(
        original_idea=idea,
        target_user="设备运维人员",
        problem="需要更早识别风险",
        desired_outcome="获得可复核的预警",
        known_resources=[],
        constraints=[],
        unknowns=["真实误报率"],
        provenance={"problem": "model_hypothesis"},
        clarification_required=False,
        clarification_question=None,
    )


class ScriptedAdapter:
    def __init__(self, script: list[Any]) -> None:
        self.script = script
        self.calls = 0
        self.closed = False

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        self.calls += 1
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(request)
        return outcome

    def design_solutions(self, _brief: IdeaBriefDraft):
        self.calls += 1
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def analyze_evidence(self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]):
        self.calls += 1
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            return outcome(claim, chunks)
        return outcome

    def close(self) -> None:
        self.closed = True


class RecordingAdapterFactory:
    def __init__(self, scripts: dict[str, list[Any]]) -> None:
        self.scripts = scripts
        self.configurations: list[dict[str, Any]] = []
        self.adapters: list[ScriptedAdapter] = []

    def __call__(self, **configuration: Any) -> ScriptedAdapter:
        self.configurations.append(dict(configuration))
        adapter = ScriptedAdapter(self.scripts[configuration["model"]])
        self.adapters.append(adapter)
        return adapter


@pytest.fixture()
def profile_service(db):
    return ModelProfileService(
        db,
        credential_store=CredentialStore(backend=MemoryCredentialBackend()),
    )


def _hybrid(profile_service, factory: RecordingAdapterFactory):
    from app.services.hybrid_runtime import HybridStructuredRuntime

    return HybridStructuredRuntime(
        profile_service,
        local_runtime=DeterministicDemoRuntime(fixture_path=FIXTURE_PATH),
        adapter_factory=factory,
        max_model_rounds=2,
        max_tool_rounds=4,
    )


def _create_profile(
    service: ModelProfileService,
    *,
    provider: str,
    model_id: str,
    api_key: str,
    is_default: bool = False,
) -> dict[str, Any]:
    return service.create(
        display_name=model_id,
        provider=provider,
        model_id=model_id,
        api_key=api_key,
        is_default=is_default,
    )


def test_global_default_profile_is_resolved_when_request_starts(profile_service):
    _create_profile(
        profile_service,
        provider="qwen",
        model_id="qwen-model",
        api_key="global-secret",
        is_default=True,
    )
    factory = RecordingAdapterFactory({"qwen-model": [lambda request: _brief(request.idea)]})
    hybrid = _hybrid(profile_service, factory)

    runtime = hybrid.for_project(None)
    result = runtime.interpret_idea(QuickStartRequest(idea="工业设备未来窗口预警"))

    assert (runtime.provider, runtime.model) == ("qwen", "qwen-model")
    assert result.original_idea == "工业设备未来窗口预警"
    assert factory.configurations[0]["api_key"] == "global-secret"
    assert factory.adapters[0].closed is True


def test_project_override_wins_without_mutating_global_selection(db, profile_service):
    global_profile = _create_profile(
        profile_service,
        provider="qwen",
        model_id="global-model",
        api_key="global-secret",
        is_default=True,
    )
    project_profile = _create_profile(
        profile_service,
        provider="deepseek",
        model_id="project-model",
        api_key="project-secret",
    )
    project = ProjectService(db).create_project(
        title="项目级模型", summary="验证 profile override", actor="tester"
    )
    profile_service.set_project_override(project["id"], project_profile["id"])
    hybrid = _hybrid(
        profile_service,
        RecordingAdapterFactory({"global-model": [], "project-model": []}),
    )

    assert hybrid.for_project(project["id"]).model == "project-model"
    assert hybrid.for_project(None).model == "global-model"
    assert global_profile["is_default"] is True


def test_absent_profile_preserves_unknown_idea_and_returns_exact_local_guidance_payload(
    db, profile_service
):
    request = QuickStartRequest(
        idea="做一个完全未知的火星矿业调度产品",
        target_user="火星矿工",
        resources=["现场访谈"],
        priority="fast_mvp",
    )
    hybrid = _hybrid(profile_service, RecordingAdapterFactory({}))
    service = QuickStartService(db, ProjectService(db), hybrid)

    result = service.quick_start(request, actor="tester")

    assert set(result) == {"error_code", "message", "recovery_actions", "preserved_input"}
    assert result["error_code"] == "LOCAL_GUIDANCE_REQUIRED"
    assert "本地引导" in result["message"]
    assert result["preserved_input"] == request.model_dump(mode="json")
    assert "DETERMINISTIC_DEMO_UNSUPPORTED" not in json.dumps(result, ensure_ascii=False)
    saved = db.fetch_one("SELECT id, summary FROM projects WHERE summary = ?", (request.idea,))
    assert saved is not None
    assert db.fetch_one(
        "SELECT id FROM idea_briefs WHERE project_id = ?", (saved["id"],)
    ) is None


def test_invalid_key_returns_safe_recovery_without_key_or_raw_provider_error(
    db, profile_service
):
    sentinel = "sk-SENTINEL-INVALID-KEY"
    _create_profile(
        profile_service,
        provider="openai",
        model_id="bad-key-model",
        api_key=sentinel,
        is_default=True,
    )
    factory = RecordingAdapterFactory(
        {
            "bad-key-model": [
                ProviderCallError("unauthorized", "Provider authentication was rejected.", False)
            ]
        }
    )
    service = QuickStartService(db, ProjectService(db), _hybrid(profile_service, factory))

    result = service.quick_start(
        QuickStartRequest(idea="工业时序异常告警排序"), actor="tester"
    )

    assert set(result) == {"error_code", "message", "recovery_actions", "preserved_input"}
    assert result["error_code"] == "MODEL_CREDENTIAL_INVALID"
    serialized = json.dumps(result, ensure_ascii=False)
    assert sentinel not in serialized
    assert "Provider authentication" not in serialized
    assert "密钥" in serialized


def test_schema_repair_is_limited_to_one_retry_and_trace_reports_the_bound(
    profile_service,
):
    _create_profile(
        profile_service,
        provider="openai",
        model_id="repair-model",
        api_key="secret",
        is_default=True,
    )
    factory = RecordingAdapterFactory(
        {
            "repair-model": [
                ProviderCallError(
                    "invalid_content", "Provider response did not match the required schema.", False
                ),
                lambda request: _brief(request.idea),
            ]
        }
    )
    runtime = _hybrid(profile_service, factory).for_project(None)

    result = runtime.interpret_idea(QuickStartRequest(idea="未来窗口预警"))

    assert result.original_idea == "未来窗口预警"
    assert runtime.model_rounds_used == 2
    assert runtime.max_model_rounds == 2
    assert runtime.max_tool_rounds == 4
    assert factory.adapters[0].calls == 2


def test_terminal_schema_failure_does_not_persist_a_fake_brief(db, profile_service):
    _create_profile(
        profile_service,
        provider="openai",
        model_id="always-invalid",
        api_key="secret",
        is_default=True,
    )
    invalid = ProviderCallError(
        "invalid_content", "Provider response did not match the required schema.", False
    )
    factory = RecordingAdapterFactory({"always-invalid": [invalid, invalid, _brief("never")]})
    service = QuickStartService(db, ProjectService(db), _hybrid(profile_service, factory))

    result = service.quick_start(QuickStartRequest(idea="任意新 Idea"), actor="tester")

    assert result["error_code"] == "MODEL_OUTPUT_SCHEMA_INVALID"
    assert factory.adapters[0].calls == 2
    assert db.fetch_one("SELECT COUNT(*) AS count FROM idea_briefs") == {"count": 0}


def test_terminal_provider_failure_never_tries_another_paid_profile(db, profile_service):
    _create_profile(
        profile_service,
        provider="openai",
        model_id="selected-model",
        api_key="selected-secret",
        is_default=True,
    )
    _create_profile(
        profile_service,
        provider="deepseek",
        model_id="unselected-model",
        api_key="other-secret",
    )
    factory = RecordingAdapterFactory(
        {
            "selected-model": [ProviderCallError("quota_exhausted", "Quota exhausted.", False)],
            "unselected-model": [lambda request: _brief(request.idea)],
        }
    )
    service = QuickStartService(db, ProjectService(db), _hybrid(profile_service, factory))

    result = service.quick_start(QuickStartRequest(idea="异常排序"), actor="tester")

    assert result["error_code"] == "MODEL_QUOTA_EXHAUSTED"
    assert [item["model"] for item in factory.configurations] == ["selected-model"]


class HttpAdapterFactory:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.clients: list[httpx.Client] = []

    def __call__(self, **configuration: Any):
        from app.services.provider_adapters import ModelAdapter

        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        self.clients.append(client)
        return ModelAdapter(**configuration, client=client)

    def close(self) -> None:
        for client in self.clients:
            client.close()


def _http_brief_response(idea: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": _brief(idea).model_dump_json()}}
            ]
        },
    )


def test_openai_response_format_rejection_falls_back_once_with_global_round_accounting(
    profile_service,
):
    _create_profile(
        profile_service,
        provider="openai",
        model_id="plain-fallback-model",
        api_key="secret",
        is_default=True,
    )
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return _http_brief_response("未来窗口预警")

    factory = HttpAdapterFactory(handler)
    runtime = _hybrid(profile_service, factory).for_project(None)
    try:
        result = runtime.interpret_idea(QuickStartRequest(idea="未来窗口预警"))
    finally:
        factory.close()

    assert result.original_idea == "未来窗口预警"
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in requests[1]
    assert len(requests) == 2
    assert runtime.model_rounds_used == 2


def test_plain_fallback_is_strictly_parsed_and_cannot_exceed_global_budget(
    profile_service,
):
    from app.errors import StructuredRuntimeRecoveryError

    _create_profile(
        profile_service,
        provider="openai",
        model_id="invalid-plain-fallback-model",
        api_key="secret",
        is_default=True,
    )
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"not":"a brief"}'}}]},
        )

    factory = HttpAdapterFactory(handler)
    runtime = _hybrid(profile_service, factory).for_project(None)
    try:
        with pytest.raises(StructuredRuntimeRecoveryError) as caught:
            runtime.interpret_idea(QuickStartRequest(idea="严格解析"))
    finally:
        factory.close()

    assert caught.value.error_code == "MODEL_OUTPUT_SCHEMA_INVALID"
    assert len(requests) == 2
    assert runtime.model_rounds_used == runtime.max_model_rounds == 2


@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [(401, "MODEL_CREDENTIAL_INVALID"), (402, "MODEL_QUOTA_EXHAUSTED")],
)
def test_auth_and_quota_failures_never_trigger_plain_or_blind_retry(
    profile_service, status_code, error_code
):
    from app.errors import StructuredRuntimeRecoveryError

    _create_profile(
        profile_service,
        provider="openai",
        model_id=f"terminal-{status_code}",
        api_key="secret",
        is_default=True,
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, text="unsafe provider body")

    factory = HttpAdapterFactory(handler)
    runtime = _hybrid(profile_service, factory).for_project(None)
    try:
        with pytest.raises(StructuredRuntimeRecoveryError) as caught:
            runtime.interpret_idea(QuickStartRequest(idea="不要盲目重试"))
    finally:
        factory.close()

    assert caught.value.error_code == error_code
    assert calls == 1
    assert runtime.model_rounds_used == 1


def test_anthropic_compatible_path_uses_one_plain_strictly_parsed_attempt(
    profile_service,
):
    profile_service.create(
        display_name="Anthropic compatible",
        provider="custom",
        protocol="anthropic_messages",
        base_url="https://anthropic-compatible.invalid/v1",
        model_id="anthropic-compatible-model",
        api_key="secret",
        is_default=True,
    )
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": _brief("Anthropic 兼容").model_dump_json()}
                ]
            },
        )

    factory = HttpAdapterFactory(handler)
    runtime = _hybrid(profile_service, factory).for_project(None)
    try:
        result = runtime.interpret_idea(QuickStartRequest(idea="Anthropic 兼容"))
    finally:
        factory.close()

    assert result.original_idea == "Anthropic 兼容"
    assert len(requests) == 1
    assert "response_format" not in requests[0]
    assert runtime.model_rounds_used == 1


def test_unknown_tool_and_invalid_arguments_are_rejected_before_handler(registry):
    from app.tools import ToolSpec, _object_schema

    called: list[bool] = []
    registry._register(
        ToolSpec(
            name="test_guarded_write",
            description="test-only guarded write",
            risk_level="L1",
            permission_class="local_write",
            parameters=_object_schema({"value": {"type": "string"}}, ["value"]),
            handler=lambda _arguments, _actor: called.append(True),
        )
    )

    with pytest.raises(KeyError, match="not registered"):
        registry.execute("invented_tool", {}, actor="tester", human_confirmed=True)
    with pytest.raises(ValueError, match="unknown arguments"):
        registry.execute(
            "test_guarded_write",
            {"value": "ok", "unexpected": True},
            actor="tester",
            human_confirmed=False,
        )
    assert called == []


@pytest.mark.parametrize("permission_class", ["network_read", "local_write", "delete", "export"])
def test_non_local_read_permissions_require_confirmation_immediately_before_handler(
    registry, permission_class
):
    from app.tools import ToolSpec, _object_schema

    calls: list[tuple[dict[str, Any], str]] = []
    name = f"test_{permission_class}"
    registry._register(
        ToolSpec(
            name=name,
            description="test-only permission boundary",
            risk_level="L1",
            permission_class=permission_class,
            parameters=_object_schema({"value": {"type": "string"}}, ["value"]),
            handler=lambda arguments, actor: calls.append((arguments, actor)) or {"ok": True},
        )
    )

    with pytest.raises(PermissionError, match="explicit human confirmation"):
        registry.execute(name, {"value": "safe"}, actor="tester", human_confirmed=False)
    with pytest.raises(PermissionError, match="explicit human confirmation"):
        registry.execute(name, {"value": "safe"}, actor="tester")
    assert calls == []
    assert registry.execute(
        name, {"value": "safe"}, actor="tester", human_confirmed=True
    ) == {"ok": True}
    assert calls == [({"value": "safe"}, "tester")]


def test_local_read_auto_runs_and_all_schemas_publish_permission_class(registry):
    result = registry.execute(
        "get_project_canvas",
        {"project_id": "project_insightforge_demo"},
        actor="tester",
        human_confirmed=False,
    )

    assert result["project_id"] == "project_insightforge_demo"
    for tool in registry.schemas():
        assert tool["function"]["x-permission-class"] in {
            "local_read",
            "network_read",
            "local_write",
            "delete",
            "export",
        }


def test_application_wires_hybrid_runtime_to_the_shared_profile_service(client):
    from app.services.hybrid_runtime import HybridStructuredRuntime

    assert isinstance(client.app.state.structured_runtime, HybridStructuredRuntime)
    assert client.app.state.structured_runtime.profile_service is client.app.state.model_profiles


def test_no_profile_fallback_ignores_legacy_paid_environment(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import app.services.ai_runtime as ai_runtime
    from app.main import create_app

    paid_runtime_constructions: list[dict[str, Any]] = []

    class ForbiddenPaidRuntime:
        mode = "llm_structured"
        provider = "forbidden-paid"
        model = "forbidden-paid"
        prompt_version = "test"
        schema_version = "test"
        max_model_rounds = 1
        max_tool_rounds = 0
        model_rounds_used = 0

        def __init__(self, **configuration: Any) -> None:
            paid_runtime_constructions.append(configuration)

        def interpret_idea(self, _request):
            from app.errors import StructuredRuntimeUnavailableError

            raise StructuredRuntimeUnavailableError("paid runtime must not run")

    monkeypatch.setattr(ai_runtime, "OpenAIStructuredRuntime", ForbiddenPaidRuntime)
    monkeypatch.setenv("INSIGHTFORGE_STRUCTURED_AI_MODE", "llm_structured")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-LEGACY-ENV-MUST-NOT-BE-USED")
    application = create_app(database_path=tmp_path / "environment-fallback.sqlite3", seed=False)

    with TestClient(application) as isolated_client:
        response = isolated_client.post(
            "/api/projects/quick-start",
            json={
                "idea": "一个没有冻结案例的任意产品",
                "target_user": None,
                "resources": [],
                "priority": "fast_mvp",
            },
        )

    assert paid_runtime_constructions == []
    assert response.status_code == 201
    assert response.json()["error_code"] == "LOCAL_GUIDANCE_REQUIRED"
    assert "sk-LEGACY" not in response.text


def test_legacy_document_generator_ignores_environment_credentials_at_boot_and_invocation(
    monkeypatch, tmp_path, caplog
):
    from fastapi.testclient import TestClient

    import app.services.generation as generation
    from app.main import create_app

    sentinel = "sk-SENTINEL-LEGACY-DOCUMENT-ENV"
    constructions: list[dict[str, Any]] = []

    class ForbiddenRemoteDocumentGenerator:
        def __init__(self, **configuration: Any) -> None:
            constructions.append(configuration)
            raise AssertionError("legacy environment must not construct a remote generator")

    monkeypatch.setattr(
        generation, "LLMDocumentGenerator", ForbiddenRemoteDocumentGenerator
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "https://legacy-provider.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    monkeypatch.setenv("OPENAI_LLM_ENABLED", "true")
    monkeypatch.setenv("INSIGHTFORGE_STRUCTURED_AI_MODE", "llm_structured")
    caplog.set_level(logging.DEBUG)
    application = create_app(
        database_path=tmp_path / "legacy-document-environment.sqlite3", seed=False
    )

    with TestClient(application) as isolated_client:
        generated = isolated_client.app.state.generator.generate(
            "prd",
            {
                "problem": "设备异常需要更早处置",
                "target_users": "设备运维人员",
                "goals": ["提前预警"],
                "non_goals": [],
                "success_metrics": ["减少漏报"],
                "constraints": ["必须人工复核"],
            },
            [],
            project_title="离线文档验收",
        )
        health = isolated_client.get("/api/health")

    assert constructions == []
    assert isinstance(application.state.generator, generation.LocalDocumentGenerator)
    assert generated["content"].startswith("# 离线文档验收")
    assert health.json()["llm_mode"] == "local"
    assert sentinel not in health.text
    assert sentinel not in caplog.text
    with sqlite3.connect(application.state.db.path) as connection:
        assert sentinel not in "\n".join(connection.iterdump())


def test_remote_document_generator_never_resolves_legacy_environment_configuration(
    monkeypatch,
):
    import app.services.generation as generation

    sentinel = "sk-SENTINEL-DIRECT-LEGACY-DOCUMENT"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://legacy-provider.invalid/v1")
    monkeypatch.setenv("OPENAI_MODEL", "legacy-model")
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)

    with pytest.raises(RuntimeError, match="profile-backed configuration") as caught:
        generation.LLMDocumentGenerator()

    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_builtin_l1_tool_rejects_omitted_confirmation(registry):
    with pytest.raises(PermissionError, match="explicit human confirmation"):
        registry.execute(
            "create_document_draft",
            {
                "project_id": "project_insightforge_demo",
                "doc_type": "prd",
                "idempotency_key": "omitted-confirmation-must-not-write",
            },
            actor="tester",
        )


def _insert_evidence_case(db, *, project_id: str, claim_id: str) -> None:
    from app.db import utc_now

    now = utc_now()
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, "证据恢复", "证据恢复", "active", now, now),
    )
    db.execute(
        """
        INSERT INTO project_claims(
            id, project_id, claim_type, statement, provenance, verification_status,
            criticality, scope_note, status, created_at, updated_at
        ) VALUES (?, ?, 'user_problem', ?, 'model_hypothesis', 'unverified',
                  'critical', '当前测试范围', 'active', ?, ?)
        """,
        (claim_id, project_id, "设备运维人员需要可复核的预警", now, now),
    )
    db.add_source(
        project_id=project_id,
        title="访谈原文",
        source_type="real_user_research",
        authority=0.8,
        content="设备运维人员需要可复核的预警",
        filename="interview.txt",
    )


def test_evidence_api_returns_exact_safe_recovery_and_audits_resolved_runtime(client):
    project_id = "project_evidence_recovery"
    claim_id = "claim_evidence_recovery"
    _insert_evidence_case(client.app.state.db, project_id=project_id, claim_id=claim_id)
    client.app.state.model_profiles.credential_store = CredentialStore(
        backend=MemoryCredentialBackend()
    )
    profile = _create_profile(
        client.app.state.model_profiles,
        provider="openai",
        model_id="evidence-model",
        api_key="evidence-secret",
        is_default=True,
    )
    invalid = ProviderCallError(
        "invalid_content", "Provider response did not match the required schema.", False
    )
    factory = RecordingAdapterFactory({"evidence-model": [invalid, invalid, []]})
    client.app.state.structured_runtime.adapter_factory = factory

    response = client.post(
        f"/api/projects/{project_id}/evidence/analyze",
        json={"claim_ids": [claim_id]},
    )

    assert response.status_code == 503
    body = response.json()
    assert set(body) == {"error_code", "message", "recovery_actions", "preserved_input"}
    assert body["error_code"] == "MODEL_OUTPUT_SCHEMA_INVALID"
    assert "模型" in body["message"]
    assert "Provider response" not in response.text
    assert "evidence-secret" not in response.text
    assert factory.adapters[0].calls == 2
    assert factory.adapters[0].closed is True
    row = client.app.state.db.fetch_one(
        """
        SELECT payload_json FROM audit_events
        WHERE action='project_evidence_analyzed' AND entity_id=?
        ORDER BY created_at DESC LIMIT 1
        """,
        (claim_id,),
    )
    trace = json.loads(row["payload_json"])
    assert trace["provider"] == "openai"
    assert trace["model"] == "evidence-model"
    assert trace["profile_id"] == profile["id"]
    assert trace["profile_revision"] == 1
    assert trace["model_rounds_used"] == 2
    assert trace["max_model_rounds"] == 2
    assert trace["status"] == "failed"


def test_evidence_schema_repair_is_bounded_and_unexpected_errors_are_sanitized(
    profile_service,
):
    from app.errors import StructuredRuntimeRecoveryError

    _create_profile(
        profile_service,
        provider="openai",
        model_id="bounded-evidence-model",
        api_key="secret",
        is_default=True,
    )
    repaired_factory = RecordingAdapterFactory(
        {"bounded-evidence-model": [{"not": "a relation list"}, []]}
    )
    repaired = _hybrid(profile_service, repaired_factory).for_project(None)

    assert repaired.analyze_evidence(claim={"project_id": "p"}, chunks=[{"x": 1}]) == []
    assert repaired.model_rounds_used == 2
    assert repaired_factory.adapters[0].calls == 2

    crashing_factory = RecordingAdapterFactory(
        {"bounded-evidence-model": [RuntimeError("RAW-SENTINEL-PROVIDER-BODY")]}
    )
    crashing = _hybrid(profile_service, crashing_factory).for_project(None)
    with pytest.raises(StructuredRuntimeRecoveryError) as caught:
        crashing.analyze_evidence(claim={"project_id": "p"}, chunks=[{"x": 1}])
    payload = caught.value.as_payload()
    assert payload["error_code"] == "MODEL_PROVIDER_ERROR"
    assert "RAW-SENTINEL" not in json.dumps(payload, ensure_ascii=False)
    assert crashing.model_rounds_used == 1


def test_early_solution_recovery_is_audited_with_actual_profile_and_rounds(
    db, profile_service
):
    project_service = ProjectService(db)
    local_hybrid = _hybrid(profile_service, RecordingAdapterFactory({}))
    quick_start = QuickStartService(db, project_service, local_hybrid)
    created = quick_start.quick_start(
        QuickStartRequest(idea="帮小型便利店减少缺货"), actor="tester"
    )
    project_id = created["project_id"]
    quick_start.confirm_brief(
        project_id, human_confirmed=True, note="确认", actor="tester"
    )
    profile = _create_profile(
        profile_service,
        provider="deepseek",
        model_id="solution-failure-model",
        api_key="secret",
        is_default=True,
    )
    factory = RecordingAdapterFactory(
        {
            "solution-failure-model": [
                ProviderCallError("unauthorized", "raw provider detail", False)
            ]
        }
    )
    service = SolutionDesignService(db, _hybrid(profile_service, factory))

    result = service.generate(project_id, actor="tester")

    assert result["error_code"] == "MODEL_CREDENTIAL_INVALID"
    assert db.fetch_one(
        "SELECT id FROM solution_runs WHERE project_id = ?", (project_id,)
    ) is None
    row = db.fetch_one(
        """
        SELECT payload_json FROM audit_events
        WHERE action='solution_generation_recovery_required' AND entity_id=?
        ORDER BY created_at DESC LIMIT 1
        """,
        (project_id,),
    )
    assert row is not None
    trace = json.loads(row["payload_json"])
    assert trace["provider"] == "deepseek"
    assert trace["model"] == "solution-failure-model"
    assert trace["profile_id"] == profile["id"]
    assert trace["profile_revision"] == 1
    assert trace["model_rounds_used"] == 1
    assert trace["max_model_rounds"] == 2
    assert trace["status"] == "recovery_required"


def _insert_multi_claim_evidence_project(db, *, project_id: str, count: int) -> list[str]:
    from app.db import utc_now

    now = utc_now()
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, "多判断证据", "多判断证据", "active", now, now),
    )
    claim_ids: list[str] = []
    for index in range(count):
        claim_id = f"claim_multi_{index}"
        statement = f"第{index}个设备风险需要独立证据"
        db.execute(
            """
            INSERT INTO project_claims(
                id, project_id, claim_type, statement, provenance, verification_status,
                criticality, scope_note, status, created_at, updated_at
            ) VALUES (?, ?, 'user_problem', ?, 'model_hypothesis', 'unverified',
                      'critical', '当前测试范围', 'active', ?, ?)
            """,
            (claim_id, project_id, statement, now, now),
        )
        db.add_source(
            project_id=project_id,
            title=f"访谈{index}",
            source_type="real_user_research",
            authority=0.8,
            content=statement,
            filename=f"interview-{index}.txt",
        )
        claim_ids.append(claim_id)
    return claim_ids


def _relation_for_claim(claim: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunk = next(item for item in chunks if claim["statement"] in item["content"])
    return [
        {
            "source_id": chunk["source_id"],
            "chunk_id": chunk["chunk_id"],
            "relation": "supports",
            "directness": "direct",
            "scope_fit": "fit",
            "recency_state": "current",
            "evidence_span": claim["statement"],
            "reason": "原文直接支持当前判断",
        }
    ]


def _project_claim_service(db, runtime):
    from app.services.project_claims import ProjectClaimService
    from app.services.retrieval_service import ProjectRetrievalService

    return ProjectClaimService(
        db=db,
        retrieval=ProjectRetrievalService(db),
        runtime=runtime,
    )


def test_three_evidence_claims_each_receive_an_independent_runtime_and_trace(
    db, profile_service
):
    project_id = "project_three_evidence_claims"
    claim_ids = _insert_multi_claim_evidence_project(db, project_id=project_id, count=3)
    _create_profile(
        profile_service,
        provider="openai",
        model_id="multi-claim-model",
        api_key="secret",
        is_default=True,
    )
    factory = RecordingAdapterFactory(
        {"multi-claim-model": [_relation_for_claim, _relation_for_claim, _relation_for_claim]}
    )
    service = _project_claim_service(db, _hybrid(profile_service, factory))

    result = service.analyze_project_evidence(project_id, actor="tester")

    assert len(result["changes"]) == 3
    traces: dict[str, dict[str, Any]] = {}
    for claim_id in claim_ids:
        row = db.fetch_one(
            """
            SELECT payload_json FROM audit_events
            WHERE action='project_evidence_analyzed' AND entity_id=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (claim_id,),
        )
        traces[claim_id] = json.loads(row["payload_json"])
    assert {trace["model_rounds_used"] for trace in traces.values()} == {1}
    assert {trace["model"] for trace in traces.values()} == {"multi-claim-model"}
    assert len(factory.adapters) == 3


def test_repaired_first_evidence_claim_does_not_consume_second_claim_rounds(
    db, profile_service
):
    project_id = "project_repaired_then_fresh_claim"
    claim_ids = _insert_multi_claim_evidence_project(db, project_id=project_id, count=2)
    _create_profile(
        profile_service,
        provider="openai",
        model_id="repair-then-fresh-model",
        api_key="secret",
        is_default=True,
    )
    schema_error = ProviderCallError("invalid_content", "invalid schema", False)
    factory = RecordingAdapterFactory(
        {
            "repair-then-fresh-model": [
                schema_error,
                _relation_for_claim,
                _relation_for_claim,
            ]
        }
    )
    service = _project_claim_service(db, _hybrid(profile_service, factory))

    result = service.analyze_project_evidence(project_id, actor="tester")

    assert len(result["changes"]) == 2
    used_rounds = []
    for claim_id in claim_ids:
        row = db.fetch_one(
            """
            SELECT payload_json FROM audit_events
            WHERE action='project_evidence_analyzed' AND entity_id=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (claim_id,),
        )
        used_rounds.append(json.loads(row["payload_json"])["model_rounds_used"])
    assert used_rounds == [2, 1]
    assert [adapter.calls for adapter in factory.adapters] == [2, 1]


class InvalidLocalSolutionRuntime:
    mode = "deterministic_demo"
    provider = "local-test"
    model = "invalid-local-solutions"
    prompt_version = "local-test-v1"
    schema_version = "v3-p0-1"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 0

    def __init__(self) -> None:
        self.calls = 0

    def design_solutions(self, _brief: IdeaBriefDraft) -> SolutionSetDraft:
        self.calls += 1
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        first = dict(fixture["convenience_replenishment"]["solutions"][0])
        second = {**first, "title": f"{first['title']}副本"}
        return SolutionSetDraft(candidates=[first, second], llm_core_required=False)


def test_two_local_solution_calls_are_counted_monotonically_in_failure_audit(
    db, profile_service
):
    projects = ProjectService(db)
    quick_start = QuickStartService(
        db, projects, DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    )
    created = quick_start.quick_start(
        QuickStartRequest(idea="帮小型便利店减少缺货"), actor="tester"
    )
    project_id = created["project_id"]
    quick_start.confirm_brief(
        project_id, human_confirmed=True, note="确认", actor="tester"
    )
    local_runtime = InvalidLocalSolutionRuntime()
    from app.services.hybrid_runtime import HybridStructuredRuntime

    hybrid = HybridStructuredRuntime(
        profile_service,
        local_runtime=local_runtime,
        adapter_factory=RecordingAdapterFactory({}),
        max_model_rounds=2,
        max_tool_rounds=4,
    )
    service = SolutionDesignService(db, hybrid)

    result = service.generate(project_id, actor="tester")
    assert result["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"

    assert local_runtime.calls == 2
    row = db.fetch_one(
        """
        SELECT payload_json FROM audit_events
        WHERE action='solution_generation_recovery_required' AND entity_type='solution_run'
        ORDER BY created_at DESC LIMIT 1
        """
    )
    trace = json.loads(row["payload_json"])
    assert trace["model_rounds_used"] == 2
    assert trace["max_model_rounds"] == 2
