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


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stage_b_provider_outputs.json"
ACCEPTED_STRUCTURED_CASES = (
    "STRUCTURED_GOOD",
    "FENCED_JSON",
    "ESCAPED_UNICODE",
    "MARKDOWN_WRAPPED_JSON",
)
REJECTED_STRUCTURED_CASES = (
    "LEADING_TRAILING_EXPLANATORY_TEXT",
    "MALFORMED_JSON",
    "EMPTY_OUTPUT",
    "PROVIDER_ERROR_JSON",
    "NESTED_JSON_STRING",
    "MULTIPLE_OBJECTS",
    "MISSING_FIELDS",
    "WRONG_TYPES",
    "WRONG_SCHEMA",
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


def _generate_sync(content: str | httpx.Response) -> OutputContractDraft:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return content if isinstance(content, httpx.Response) else _provider_response(content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = ModelAdapter(
            provider="openai",
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


def _generate_async(content: str | httpx.Response) -> OutputContractDraft:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return content if isinstance(content, httpx.Response) else _provider_response(content)

    async def exercise() -> OutputContractDraft:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = AsyncModelAdapter(
                provider="openai",
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


def _generate(kind: Literal["sync", "async"], content: str | httpx.Response) -> OutputContractDraft:
    if kind == "sync":
        return _generate_sync(content)
    return _generate_async(content)


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
@pytest.mark.parametrize("case_name", REJECTED_STRUCTURED_CASES)
def test_structured_output_rejects_invalid_or_ambiguous_payload(
    provider_outputs, case_name: str, kind: Literal["sync", "async"]
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
    assert set(error.safe_diagnostic) == {
        "output_sha256", "output_byte_count", "output_classification"
    }
    assert error.safe_diagnostic["output_sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert error.safe_diagnostic["output_byte_count"] == len(content.encode("utf-8"))


@pytest.mark.parametrize("kind", ("sync", "async"))
def test_bom_and_whitespace_are_removed_before_parsing(kind):
    result = _generate(kind, ' \t\ufeff {"message":"你好","items":[]} \r\n')
    assert result.model_dump() == {"message": "你好", "items": []}


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("content", (
    "", '\ufeff  ',
    '```json\n{"message":"ok","items":[]}\n```\nSTAGE_B_RAW_SENTINEL',
    '```python\n{"message":"ok","items":[]}\n```',
    '```json\n{"message":"ok","items":[]}\n```\n```json\n{}\n```',
    '{"message":"ok","items":[],"error":{"message":"STAGE_B_RAW_SENTINEL"}}',
))
def test_unsupported_or_ambiguous_wrappers_and_embedded_errors_fail_closed(kind, content):
    with pytest.raises(ProviderCallError) as caught:
        _generate(kind, content)
    assert caught.value.retryable is False
    assert "STAGE_B_RAW_SENTINEL" not in _exception_chain_text(caught.value)


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("response", (
    lambda: httpx.Response(200, content=b"STAGE_B_RAW_SENTINEL-not-json"),
    lambda: httpx.Response(200, json={"error": {"message": "STAGE_B_RAW_SENTINEL"}}),
    lambda: httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
))
def test_invalid_transport_envelopes_are_safe_typed_failures(kind, response):
    with pytest.raises(ProviderCallError) as caught:
        _generate(kind, response())
    error = caught.value
    assert "格式" in error.safe_message
    assert error.retryable is False
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "STAGE_B_RAW_SENTINEL" not in _exception_chain_text(error)
    assert set(error.safe_diagnostic) == {
        "output_sha256", "output_byte_count", "output_classification"
    }


@pytest.mark.parametrize("kind", ("sync", "async"))
@pytest.mark.parametrize("content", (
    '{"message":"STAGE_B_RAW_SENTINEL"',
    '{"unexpected":"STAGE_B_RAW_SENTINEL"}',
))
def test_managed_runtime_exposes_actionable_output_failure_without_diagnostics(kind, content):
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
