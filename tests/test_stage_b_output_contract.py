from __future__ import annotations

import asyncio
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


def _generate_sync(content: str) -> OutputContractDraft:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _provider_response(content)

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


def _generate_async(content: str) -> OutputContractDraft:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _provider_response(content)

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


def _generate(kind: Literal["sync", "async"], content: str) -> OutputContractDraft:
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
