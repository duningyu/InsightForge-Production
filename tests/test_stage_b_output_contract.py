from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter, ProviderCallError

from types import SimpleNamespace
from dataclasses import replace

from app.errors import StructuredOutputContractError
from app.schemas import AIReferenceDraft, EvidenceGuidanceDraft, QuickStartRequest
from app.services.ai_reference import AIReferenceService
from app.services.evidence_coach import EvidenceCoachService
from app.services.ai_runtime import DeterministicDemoRuntime
from app.services.solution_design import SolutionDesignService, validate_solution_set, validate_with_one_regeneration
from app.services.async_generation import AsyncGenerationRepository
from app.services.generation import LocalDocumentGenerator
from app.services.loop import DocumentLoop
from app.services.validation import PRD_HEADINGS, TECHDOC_HEADINGS


def _complete_solutions():
    runtime = DeterministicDemoRuntime(fixture_path=Path(__file__).parent / "fixtures" / "v3_golden_cases.json")
    brief = runtime.interpret_idea(QuickStartRequest(idea="帮小型便利店减少缺货"))
    return runtime.design_solutions(brief).candidates


def _card():
    return {
        "title": "访谈使用者", "question_to_validate": "是否需要补货提醒",
        "why_it_matters": "决定提醒功能是否进入 MVP", "who_or_where": ["便利店店主"],
        "action_steps": ["约一位店主，记录最近一次缺货处理过程"],
        "suggested_questions": ["上次如何发现缺货？"], "acceptable_artifacts": ["匿名访谈记录"],
        "fill_template": ["日期：；处理过程：；耗时："], "decision_impact": "决定提醒功能范围",
        "fallback_if_unavailable": "先记录自己的流程并标注假设", "limitations": "一次访谈不能代表全部店主",
    }


@pytest.mark.parametrize("body", [{}, {"mvp_thoughts": ["  "]}, {"mvp_thoughts": ["有效建议", "\t"]}, {"mvp_thoughts": {"raw_response": "PRIVATE_SENTINEL"}}])
def test_reference_domain_rejection_is_typed_safe_and_never_persisted(db, body):
    runtime = SimpleNamespace(generate_ai_reference=lambda context: body)
    with pytest.raises(StructuredOutputContractError) as caught:
        AIReferenceService(db).generate("project_insightforge_demo", actor="test", runtime=runtime)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "PRIVATE_SENTINEL" not in json.dumps(caught.value.as_payload())
    assert db.fetch_one("SELECT COUNT(*) AS n FROM ai_reference_results")["n"] == 0


@pytest.mark.parametrize("field,value", [
    ("question_to_validate", " "), ("title", " "), ("why_it_matters", " "),
    ("who_or_where", []), ("who_or_where", [" "]),
    ("action_steps", ["执行步骤", " "]), ("acceptable_artifacts", [" "]),
    ("fill_template", []), ("decision_impact", " "),
    ("fallback_if_unavailable", " "), ("limitations", " "),
])
def test_every_card_must_be_actionable_before_any_card_is_saved(db, field, value):
    broken = {**_card(), field: value}
    runtime = SimpleNamespace(generate_evidence_guidance=lambda context: {"cards": [_card(), broken]})
    with pytest.raises(StructuredOutputContractError) as caught:
        EvidenceCoachService(db).generate("project_insightforge_demo", actor="test", runtime=runtime)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert db.fetch_one("SELECT COUNT(*) AS n FROM evidence_guidance_results")["n"] == 0


def test_complete_card_survives_generation_and_replay_without_creating_sources(db):
    runtime = SimpleNamespace(generate_evidence_guidance=lambda context: {"cards": [_card()]})
    service = EvidenceCoachService(db)
    before = db.fetch_one("SELECT COUNT(*) AS n FROM sources")["n"]
    result = service.generate("project_insightforge_demo", actor="test", runtime=runtime, idempotency_key="card")
    assert result["result"]["cards"] == [_card()]
    assert service.get("project_insightforge_demo", result["id"], actor="test") == result
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sources")["n"] == before


@pytest.mark.parametrize("field,value", [("summary", " "), ("user_flow", [" "]), ("human_role", " "), ("required_data_class", " "), ("major_dependency", " ")])
def test_solution_completeness_rejects_blank_content_even_in_constructed_models(field, value):
    candidates = _complete_solutions()
    candidates[0] = candidates[0].model_copy(update={field: value})
    with pytest.raises(StructuredOutputContractError):
        validate_solution_set(candidates, llm_core_required=False)


def test_solution_difference_dimensions_ignore_case_and_whitespace():
    candidates = _complete_solutions()
    candidates[1] = candidates[0].model_copy(update={"title": "不同名称", "human_role": " " + candidates[0].human_role.upper() + " ", "major_dependency": " " + candidates[0].major_dependency.upper() + " "})
    with pytest.raises(StructuredOutputContractError):
        validate_solution_set(candidates, llm_core_required=False)


def test_invalid_triplet_is_never_salvaged_as_two_solutions():
    candidates = _complete_solutions()
    candidates[2] = candidates[0].model_copy(update={"title": "同样机制"})
    with pytest.raises(StructuredOutputContractError):
        validate_with_one_regeneration(candidates, llm_core_required=False, regenerate=lambda: candidates)


def test_complete_solution_triplet_is_accepted():
    result = validate_solution_set(_complete_solutions(), llm_core_required=False)
    assert len(result) == 3
    assert len({c.title for c in result}) == 3


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED"])
def test_async_public_projects_nested_payload_and_cannot_overwrite_run_identity(db, status):
    repository = AsyncGenerationRepository(db)
    run = repository.create_or_replay("test", "project_insightforge_demo", "public")
    response = {"generation_run_id": "forged", "status": "forged", "raw_response": "PRIVATE_SENTINEL",
                "provider_payload": {"authorization": "PRIVATE_SENTINEL"}, "system_prompt": "PRIVATE_SENTINEL",
                "traceback": "ValidationError PRIVATE_SENTINEL", "preserved_input": {"debug_prompt": "PRIVATE_SENTINEL"}}
    if status == "SUCCEEDED":
        response.update(candidates=[{**c.model_dump(), "id": f"c{i}", "provider_payload": "PRIVATE_SENTINEL"} for i, c in enumerate(_complete_solutions())],
                        run={"id": "safe-run", "status": "completed", "raw_response": "PRIVATE_SENTINEL"})
    else:
        response.update(error_code="MODEL_OUTPUT_CONTRACT_FAILED", message="生成失败，请重试。", recovery_actions=["重新生成"])
    public = replace(run, status=status, response=response, status_code=201 if status == "SUCCEEDED" else 503).public()
    assert public["generation_run_id"] == run.generation_run_id
    assert public["status"] == status
    assert "PRIVATE_SENTINEL" not in json.dumps(public)
    if status == "SUCCEEDED":
        assert public["run"] == {"id": "safe-run", "status": "completed"}
        assert len(public["candidates"]) == 3
    else:
        assert public["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"


@pytest.mark.parametrize("candidates", [[], [{"id": "incomplete"}], [{"id": "a"}, {"id": "b"}, {"id": "c"}]])
def test_async_finish_cannot_mark_incomplete_surface_succeeded(db, candidates):
    repository = AsyncGenerationRepository(db)
    run = repository.create_or_replay("test", "project_insightforge_demo", "incomplete")
    repository.claim_next()
    repository.finish(run.generation_run_id, {"candidates": candidates}, status_code=201)
    terminal = repository.get("test", "project_insightforge_demo", run.generation_run_id)
    assert terminal.status == "FAILED"
    assert terminal.public()["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
    assert db.fetch_one("SELECT quota_status FROM async_solution_generation_runs")["quota_status"] == "RELEASED"


@pytest.mark.parametrize("doc_type,headings", [("prd", PRD_HEADINGS), ("techdoc", TECHDOC_HEADINGS)])
def test_heading_only_document_is_typed_failure_without_a_saved_version(db, doc_type, headings):
    content = "待验证\n" + "\n".join(headings)
    generator = SimpleNamespace(generate=lambda *args, **kwargs: {"content": content, "citations": [], "claims": []}, repair=lambda content, *args: content)
    with pytest.raises(StructuredOutputContractError):
        DocumentLoop(db, generator=generator).run("project_insightforge_demo", doc_type)
    assert db.fetch_one("SELECT COUNT(*) AS n FROM document_versions")["n"] == 0


def _snapshot_project(client):
    quick = client.post("/api/projects/quick-start", json={"idea": "帮小型便利店减少缺货"})
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]
    assert client.post(f"/api/projects/{project_id}/idea-brief/confirm", json={"human_confirmed": True}).status_code == 200
    result = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert result.status_code == 201, result.text
    selected = client.post(f"/api/projects/{project_id}/solutions/select", json={"strategy": "single", "candidate_ids": [result.json()["candidates"][0]["id"]], "rationale": "test", "human_confirmed": True})
    assert selected.status_code == 201, selected.text
    return project_id


def test_document_rejects_snapshot_owned_by_another_project(client):
    project_id = _snapshot_project(client)
    db = client.app.state.db
    foreign = db.fetch_one("SELECT current_snapshot_id FROM projects WHERE id=?", (project_id,))["current_snapshot_id"]
    db.execute("UPDATE projects SET current_snapshot_id=? WHERE id='project_insightforge_demo'", (foreign,))
    with pytest.raises(StructuredOutputContractError):
        client.app.state.document_loop.run("project_insightforge_demo", "prd", require_snapshot=True, use_competitor_snapshot=False)
    assert db.fetch_one("SELECT COUNT(*) AS n FROM document_versions")["n"] == 0


def test_document_rejects_snapshot_change_during_generation(client):
    project_id = _snapshot_project(client)
    db = client.app.state.db
    local = LocalDocumentGenerator()
    class ChangingGenerator:
        def generate(self, *args, **kwargs):
            result = local.generate(*args, **kwargs)
            db.execute("UPDATE projects SET current_snapshot_id=NULL WHERE id=?", (project_id,))
            return result
        repair = local.repair
    with pytest.raises(StructuredOutputContractError):
        DocumentLoop(db, generator=ChangingGenerator()).run(project_id, "prd", require_snapshot=True, use_competitor_snapshot=False)
    assert db.fetch_one("SELECT COUNT(*) AS n FROM document_versions")["n"] == 0


@pytest.mark.parametrize("asynchronous", [False, True])
def test_solution_service_converts_schema_exceptions_and_releases_reservation(db, asynchronous):
    runtime = DeterministicDemoRuntime(fixture_path=Path(__file__).parent / "fixtures" / "v3_golden_cases.json")
    brief = runtime.interpret_idea(QuickStartRequest(idea="帮小型便利店减少缺货"))
    released = []
    def broken(*args, **kwargs):
        AIReferenceDraft.model_validate({"mvp_thoughts": {"raw_response": "PRIVATE_SENTINEL"}})
    async def async_broken(*args, **kwargs):
        return broken()
    runtime.design_solutions = broken
    runtime.async_design_solutions = async_broken
    runtime.release_current_reservation = lambda: released.append(True)
    service = SolutionDesignService(db, runtime)
    service._confirmed_brief_row = lambda project: {"id": "brief"}
    service._brief_for_project = lambda *args, **kwargs: brief
    result = asyncio.run(service.generate_async("project_insightforge_demo", actor="test")) if asynchronous else service.generate("project_insightforge_demo", actor="test")
    assert result["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    assert released == [True]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM solution_candidates")["n"] == 0


@pytest.mark.parametrize("replay", [False, True])
def test_solution_route_projects_service_and_durable_replay_payload(client, monkeypatch, replay):
    project_id = _snapshot_project(client)
    payload = {"candidates": [{**c.model_dump(), "id": f"c{i}", "provider_payload": "PRIVATE_SENTINEL"} for i, c in enumerate(_complete_solutions())],
               "run": {"id": "r", "status": "completed", "raw_response": "PRIVATE_SENTINEL"}, "system_prompt": "PRIVATE_SENTINEL"}
    if replay:
        monkeypatch.setattr(client.app.state.solution_generation_guard, "begin", lambda *a, **kw: SimpleNamespace(owner=False, error_code="SOLUTION_GENERATION_ALREADY_COMPLETED", status_code=201, payload=payload))
    else:
        monkeypatch.setattr(client.app.state.solution_design, "generate", lambda *a, **kw: payload)
    response = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert response.status_code == 201, response.text
    assert len(response.json()["candidates"]) == 3
    assert "PRIVATE_SENTINEL" not in response.text


def test_solution_route_rejects_incomplete_service_success(client, monkeypatch):
    project_id = _snapshot_project(client)
    monkeypatch.setattr(client.app.state.solution_design, "generate", lambda *a, **kw: {"candidates": [{"id": "x", "mechanism": "rule_based"}]})
    response = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert response.status_code == 503, response.text
    assert response.json()["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"


def test_public_allowlist_does_not_forward_objects_in_scalar_fields(db):
    repository = AsyncGenerationRepository(db)
    run = repository.create_or_replay("test", "project_insightforge_demo", "nested")
    public = replace(run, status="FAILED", response={"error_code": "MODEL_OUTPUT_CONTRACT_FAILED", "message": {"raw_response": "PRIVATE_SENTINEL"}, "recovery_actions": [{"authorization": "PRIVATE_SENTINEL"}]}).public()
    assert "PRIVATE_SENTINEL" not in json.dumps(public)
    assert isinstance(public["message"], str)


def test_document_replay_rejects_missing_snapshot_dependency(client):
    project_id = _snapshot_project(client)
    loop = client.app.state.document_loop
    result = loop.run(project_id, "prd", require_snapshot=True, use_competitor_snapshot=False, idempotency_key="bound")
    db = client.app.state.db
    db.execute("DELETE FROM artifact_dependencies WHERE artifact_id=? AND dependency_type='project_snapshot'", (result["version_id"],))
    with pytest.raises(StructuredOutputContractError):
        loop.run(project_id, "prd", require_snapshot=True, use_competitor_snapshot=False, idempotency_key="bound")


def test_public_success_fields_cannot_contain_diagnostic_objects():
    from app.services.generation_contracts import reference_public, guidance_public, solution_public
    private = {"raw_response": "PRIVATE_SENTINEL"}
    # Reference/card public reads now reject incomplete historical rows instead
    # of projecting them into empty, apparently usable results.
    for project, value in [(reference_public, {"mvp_thoughts": [private]}),
                           (guidance_public, {"cards": [{**_card(), "title": private}]})]:
        with pytest.raises(StructuredOutputContractError) as caught:
            project(value)
        assert "PRIVATE_SENTINEL" not in json.dumps(caught.value.as_payload())
    projected = solution_public({"run": {"id": private}, "candidates": [{"title": private}], "fixture_origin": private})
    assert "PRIVATE_SENTINEL" not in json.dumps(projected)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage_b_provider_outputs.json"
ACCEPTED_STRUCTURED_CASES = (
    "STRUCTURED_GOOD",
    "FENCED_JSON",
    "ESCAPED_UNICODE",
    "MARKDOWN_WRAPPED_JSON",
)
REJECTED_STRUCTURED_CASES = (
    ("LEADING_TRAILING_EXPLANATORY_TEXT", "invalid_json"),
    ("MALFORMED_JSON", "invalid_json"),
    ("EMPTY_OUTPUT", "empty_output"),
    ("PROVIDER_ERROR_JSON", "provider_error"),
    ("NESTED_JSON_STRING", "non_object"),
    ("MULTIPLE_OBJECTS", "invalid_json"),
    ("MISSING_FIELDS", "schema_mismatch"),
    ("WRONG_TYPES", "schema_mismatch"),
    ("WRONG_SCHEMA", "schema_mismatch"),
)


class OutputContractDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str
    items: list[str]


@pytest.fixture(scope="module")
def provider_outputs() -> dict[str, dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _provider_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


def _generate_sync(content: str | httpx.Response, provider: str = "openai") -> OutputContractDraft:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return content if isinstance(content, httpx.Response) else _provider_response(content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = ModelAdapter(
            provider=provider,
            protocol="anthropic_messages" if provider == "custom" else None,
            base_url="https://anthropic.example/v1" if provider == "custom" else None,
            model="stage-b-test-model",
            api_key="stage-b-fake-key",
            client=client,
        )
        try:
            return adapter._generate(
                output_model=OutputContractDraft,
                system="Return the requested JSON object only.",
                user="stage-b fixture",
            )
        finally:
            assert len(requests) == 1


def _generate_async(content: str | httpx.Response, provider: str = "openai") -> OutputContractDraft:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return content if isinstance(content, httpx.Response) else _provider_response(content)

    async def exercise() -> OutputContractDraft:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = AsyncModelAdapter(
                provider=provider,
                protocol="anthropic_messages" if provider == "custom" else None,
                base_url="https://anthropic.example/v1" if provider == "custom" else None,
                model="stage-b-test-model",
                api_key="stage-b-fake-key",
                client=client,
            )
            try:
                return await adapter._generate_async(
                    output_model=OutputContractDraft,
                    system="Return the requested JSON object only.",
                    user="stage-b fixture",
                )
            finally:
                assert len(requests) == 1

    return asyncio.run(exercise())


def _generate(kind: Literal["sync", "async"], content: str | httpx.Response, provider: str = "openai") -> OutputContractDraft:
    if kind == "sync":
        return _generate_sync(content, provider)
    return _generate_async(content, provider)


def _assert_diagnostic_identity(error, raw: bytes, classification: str):
    assert error.safe_diagnostic == {
        "output_sha256": hashlib.sha256(raw).hexdigest(),
        "output_byte_count": len(raw),
        "output_classification": classification,
    }


def _exception_chain_text(error: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.extend((str(current), repr(current), repr(vars(current))))
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


def test_plain_text_fixture_stays_on_the_non_json_contract(provider_outputs):
    content = str(provider_outputs["PLAIN_TEXT_GOOD"]["content"])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _provider_response(content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ModelAdapter(
            provider="openai",
            model="stage-b-test-model",
            api_key="stage-b-fake-key",
            client=client,
        ).live_check()

    assert len(requests) == 1
    assert result.status == "PASS"
    assert result.content_received is True
    assert content not in json.dumps(result.as_dict(), ensure_ascii=False)


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("case_name", ACCEPTED_STRUCTURED_CASES)
def test_structured_output_accepts_one_supported_payload(
    provider_outputs, case_name: str, kind: Literal["sync", "async"]
):
    case = provider_outputs[case_name]

    result = _generate(kind, str(case["content"]))

    assert result.model_dump() == case["expected"]


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("case_name,classification", REJECTED_STRUCTURED_CASES)
def test_structured_output_rejects_invalid_or_ambiguous_payload(
    provider_outputs, case_name: str, classification: str, kind: Literal["sync", "async"]
):
    content = str(provider_outputs[case_name]["content"])

    with pytest.raises(ProviderCallError) as caught:
        _generate(kind, content)

    error = caught.value
    assert error.retryable is False
    assert content not in str(error)
    assert "STAGE_B_RAW_SENTINEL" not in _exception_chain_text(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "格式" in error.safe_message
    _assert_diagnostic_identity(error, content.encode("utf-8"), classification)


@pytest.mark.parametrize("kind", ("sync", "async"))
def test_bom_and_whitespace_are_removed_before_parsing(kind):
    result = _generate(kind, ' \t\ufeff {"message":"你好","items":[]} \r\n')
    assert result.model_dump() == {"message": "你好", "items": []}


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("content,classification", (
    ("", "empty_output"), ('\ufeff  ', "empty_output"),
    ('```json\n{"message":"ok","items":[]}\n```\nSTAGE_B_RAW_SENTINEL', "invalid_json"),
    ('```python\n{"message":"ok","items":[]}\n```', "invalid_json"),
    ('```json\n{"message":"ok","items":[]}\n```\n```json\n{}\n```', "invalid_json"),
    ('{"message":"ok","items":[],"error":{"message":"STAGE_B_RAW_SENTINEL"}}', "provider_error"),
))
def test_unsupported_or_ambiguous_wrappers_and_embedded_errors_fail_closed(kind, content, classification):
    with pytest.raises(ProviderCallError) as caught:
        _generate(kind, content)
    assert caught.value.retryable is False
    assert "STAGE_B_RAW_SENTINEL" not in _exception_chain_text(caught.value)
    _assert_diagnostic_identity(caught.value, content.encode("utf-8"), classification)


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("raw,classification,provider", (
    pytest.param(b"STAGE_B_RAW_SENTINEL-not-json", "invalid_envelope", "openai", id="invalid-json"),
    pytest.param(b' [null, 123] \r\n', "invalid_envelope", "openai", id="non-object"),
    pytest.param(
        b' {\n "error" : {"message":"STAGE_B_RAW_SENTINEL \\u4f60\\u597d"}\n}\r\n',
        "provider_error", "openai", id="escaped-error",
    ),
    pytest.param(
        ' {"choices" : [{"message":{"content":null}}], "note":"原始字节"}\n'.encode("utf-8"),
        "invalid_envelope", "openai", id="null-content-utf8",
    ),
    pytest.param(b'{ "choices": [] }\n', "invalid_envelope", "openai", id="missing-choice"),
    pytest.param(
        b'{"choices":[{"message":{"content":"{}"}}], "error":{"message":"STAGE_B_RAW_SENTINEL"}}',
        "provider_error", "openai", id="error-with-content",
    ),
))
def test_invalid_transport_envelopes_are_safe_typed_failures(kind, raw, classification, provider):
    _assert_safe_envelope_failure(kind, raw, classification, provider)


@pytest.mark.parametrize("raw,classification", (
    pytest.param(
        b'{ "type":"error", "error":{"message":"STAGE_B_RAW_SENTINEL"} }\n',
        "provider_error", id="anthropic-error",
    ),
    pytest.param(b'{ "content": [{"type":"text", "text":null}] }\n',
                 "invalid_envelope", id="anthropic-null-text"),
))
def test_anthropic_sync_envelope_failures_preserve_diagnostic_identity(raw, classification):
    # Anthropic is supported only by the synchronous adapter.
    _assert_safe_envelope_failure("sync", raw, classification, "custom")


def _assert_safe_envelope_failure(kind, raw, classification, provider):
    with pytest.raises(ProviderCallError) as caught:
        _generate(kind, httpx.Response(200, content=raw), provider)
    error = caught.value
    assert "格式" in error.safe_message
    assert error.retryable is False
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "STAGE_B_RAW_SENTINEL" not in _exception_chain_text(error)
    _assert_diagnostic_identity(error, raw, classification)


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("content,classification", (
    ('{"message":"STAGE_B_RAW_SENTINEL"', "invalid_json"),
    ('{"unexpected":"STAGE_B_RAW_SENTINEL"}', "schema_mismatch"),
))
def test_managed_runtime_exposes_actionable_output_failure_without_diagnostics(kind, content, classification):
    from app.errors import StructuredRuntimeRecoveryError
    from app.schemas import QuickStartRequest
    from app.services.ai_runtime import ManagedQwenStructuredRuntime

    request = QuickStartRequest(idea="需要工业预警")
    transport = httpx.MockTransport(lambda _request: _provider_response(content))

    async def exercise_async():
        async with httpx.AsyncClient(transport=transport) as client:
            runtime = ManagedQwenStructuredRuntime(
                model="stage-b-test-model", api_key="stage-b-fake-key",
                async_adapter_factory=lambda **kwargs: AsyncModelAdapter(client=client, **kwargs),
            )
            return await runtime.async_interpret_idea(request)

    with pytest.raises(StructuredRuntimeRecoveryError) as caught:
        if kind == "async":
            asyncio.run(exercise_async())
        else:
            with httpx.Client(transport=transport) as client:
                runtime = ManagedQwenStructuredRuntime(
                    model="stage-b-test-model", api_key="stage-b-fake-key",
                    adapter_factory=lambda **kwargs: ModelAdapter(client=client, **kwargs),
                )
                runtime.interpret_idea(request)

    error = caught.value
    assert error.error_code == "MODEL_OUTPUT_CONTRACT_FAILED"
    assert "格式" in error.message
    assert "未生成" in error.message
    assert "重试" in error.message
    assert error.as_payload()["preserved_input"] == request.model_dump(mode="json")
    assert error.as_payload()["recovery_actions"]
    assert "safe_diagnostic" not in error.as_payload()
    assert "STAGE_B_RAW_SENTINEL" not in _exception_chain_text(error)
    _assert_diagnostic_identity(error, content.encode("utf-8"), classification)
