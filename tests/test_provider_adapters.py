from __future__ import annotations

import json

import httpx
import pytest

from app.schemas import IdeaBriefDraft, QuickStartRequest, SolutionSetDraft


@pytest.mark.parametrize(
    ("provider", "protocol", "base_url"),
    [
        ("qwen", "openai_chat_completions", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("kimi", "openai_chat_completions", "https://api.moonshot.cn/v1"),
        ("deepseek", "openai_chat_completions", "https://api.deepseek.com"),
        ("glm", "openai_chat_completions", "https://open.bigmodel.cn/api/paas/v4"),
        ("openai", "openai_chat_completions", "https://api.openai.com/v1"),
        ("custom", "custom", None),
    ],
)
def test_registry_presets_keep_provider_identity_and_official_urls(provider, protocol, base_url):
    from app.services.model_providers import ProviderRegistry

    preset = ProviderRegistry.get(provider)
    assert (preset.provider, preset.protocol, preset.default_base_url) == (provider, protocol, base_url)


def test_custom_provider_requires_protocol_and_base_url():
    from app.services.model_providers import ProviderConfigurationError, ProviderRegistry

    with pytest.raises(ProviderConfigurationError):
        ProviderRegistry.resolve("custom")
    with pytest.raises(ProviderConfigurationError):
        ProviderRegistry.resolve("custom", protocol="openai_chat_completions")
    resolved = ProviderRegistry.resolve(
        "custom", protocol="openai_chat_completions", base_url="https://gateway.example/v1"
    )
    assert resolved.provider == "custom"


@pytest.mark.parametrize("provider", ["qwen", "kimi", "deepseek", "glm", "openai"])
def test_provider_presets_reject_arbitrary_protocol_and_endpoint_overrides(provider):
    from app.services.model_providers import ProviderConfigurationError, ProviderRegistry

    with pytest.raises(ProviderConfigurationError):
        ProviderRegistry.resolve(
            provider,
            protocol="anthropic_messages",
        )
    with pytest.raises(ProviderConfigurationError):
        ProviderRegistry.resolve(
            provider,
            base_url="https://attacker-controlled.invalid/v1",
        )


@pytest.mark.parametrize("provider", ["deepseek", "glm"])
def test_bailian_shared_endpoint_is_allowed_for_openai_compatible_presets(provider):
    from app.services.model_providers import ProviderRegistry

    resolved = ProviderRegistry.resolve(
        provider,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    assert resolved.provider == provider
    assert resolved.default_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


@pytest.mark.parametrize(("provider", "model"), [("deepseek", "deepseek-v4-flash-0731"), ("glm", "glm-5.2")])
def test_bailian_live_check_disables_thinking_with_sufficient_budget(provider, model):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": "OK"}}]})

    result = _provider_adapter(provider=provider, model=model, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", handler=handler).live_check()
    assert result.status == "PASS"
    assert len(seen) == 1
    assert seen[0]["stream"] is False
    assert seen[0]["max_tokens"] >= 16
    assert seen[0]["enable_thinking"] is False
    assert "extra_body" not in seen[0]


def _brief_payload() -> dict[str, object]:
    return {
        "original_idea": "Predict failures",
        "target_user": "operators",
        "problem": "Unplanned downtime",
        "desired_outcome": "Earlier action",
        "known_resources": [],
        "constraints": [],
        "unknowns": [],
        "provenance": {"target_user": "model_hypothesis"},
        "clarification_required": False,
        "clarification_question": None,
    }


def _solution_payload() -> dict[str, object]:
    item = {
        "mechanism": "rule_based", "summary": "summary", "why_fit": "fit",
        "user_flow": ["step"], "mvp_pages": ["page"], "features": ["feature"],
        "inputs": ["input"], "outputs": ["output"], "decision_logic": ["logic"],
        "data_requirements": ["data"], "technical_components": ["component"],
        "implementation_plan": ["plan"], "acceptance_cases": ["case"], "risks": ["risk"],
        "unknowns": ["unknown"], "complexity": "low", "provenance": "model_hypothesis",
        "required_data_class": "internal", "automation_level": "low", "human_role": "reviews",
        "core_decision_logic": "logic", "major_dependency": "none",
        "requires_llm_runtime": False, "requires_rag_runtime": False, "requires_agent_runtime": False,
    }
    return {
        "candidates": [
            {**item, "title": "Rules"},
            {**item, "title": "Workflow"},
            {**item, "title": "Prediction"},
        ],
        "llm_core_required": False,
    }


def _evidence_payload() -> dict[str, object]:
    return {
        "relations": [
            {
                "source_id": "source-1",
                "chunk_id": "chunk-1",
                "relation": "supports",
                "directness": "direct",
                "scope_fit": "fit",
                "recency_state": "current",
                "evidence_span": "可核对的原文",
                "reason": "原文直接支持判断",
            }
        ]
    }


def _adapter(handler, *, api_key="secret-value"):
    from app.services.provider_adapters import ModelAdapter

    return ModelAdapter(
        provider="openai", model="test-model", api_key=api_key,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _provider_adapter(handler, *, provider, model, base_url, api_key="secret-value"):
    from app.services.provider_adapters import ModelAdapter

    return ModelAdapter(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_kimi_live_check_disables_thinking_and_uses_single_plain_request():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        assert body["max_completion_tokens"] == 16
        assert body["stream"] is False
        assert "tools" not in body
        assert "response_format" not in body
        return httpx.Response(200, json={"model": "kimi-k2.6", "choices": [{"message": {"content": "OK"}}]})

    result = _provider_adapter(
        handler,
        provider="kimi",
        model="kimi-k2.6",
        base_url="https://api.moonshot.cn/v1",
    ).live_check()
    assert result.status == "PASS"
    assert len(requests) == 1


def test_glm_live_check_disables_thinking_and_uses_single_plain_request():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert body["enable_thinking"] is False
        assert body["max_tokens"] == 32
        assert body["stream"] is False
        assert "tools" not in body
        assert "response_format" not in body
        return httpx.Response(200, json={"model": "glm-5.2", "choices": [{"message": {"content": "OK"}}]})

    result = _provider_adapter(
        handler,
        provider="glm",
        model="glm-5.2",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    ).live_check()
    assert result.status == "PASS"
    assert len(requests) == 1


def _anthropic_adapter(handler):
    from app.services.provider_adapters import ModelAdapter

    return ModelAdapter(
        provider="custom", protocol="anthropic_messages", base_url="https://anthropic.example/v1",
        model="test-model", api_key="secret-value",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _chat_response(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def _anthropic_response(payload: object) -> httpx.Response:
    return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(payload)}]})


def test_interpret_idea_translates_openai_wire_protocol_and_parses_schema():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-value"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        return _chat_response(_brief_payload())

    actual = _adapter(handler).interpret_idea(QuickStartRequest(idea="Predict failures"))
    assert isinstance(actual, IdeaBriefDraft)


def test_qwen_structured_generation_uses_strict_json_schema():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["enable_thinking"] is False
        response_format = body["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        assert response_format["json_schema"]["name"] == "IdeaBriefDraft"
        assert response_format["json_schema"]["schema"]["type"] == "object"
        return _chat_response(_brief_payload())

    actual = _provider_adapter(
        provider="qwen",
        model="qwen3.7-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        handler=handler,
    ).interpret_idea(QuickStartRequest(idea="Predict failures"))
    assert isinstance(actual, IdeaBriefDraft)


def test_qwen_live_check_disables_thinking():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["enable_thinking"] is False
        assert body["max_tokens"] == 8
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(200, json={"model": "qwen3.7-flash", "choices": [{"message": {"content": "OK"}}]})

    result = _provider_adapter(
        provider="qwen",
        model="qwen3.7-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        handler=handler,
    ).live_check()
    assert result.status == "PASS"


def test_design_solutions_parses_schema():
    actual = _adapter(lambda request: _chat_response(_solution_payload())).design_solutions(
        IdeaBriefDraft.model_validate(_brief_payload())
    )
    assert isinstance(actual, SolutionSetDraft)


def test_anthropic_messages_adapter_translates_wire_protocol_and_parses_schema():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://anthropic.example/v1/messages"
        assert request.headers["x-api-key"] == "secret-value"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["max_tokens"] == 1024
        assert "response_format" not in body
        return _anthropic_response(_brief_payload())

    actual = _anthropic_adapter(handler).interpret_idea(QuickStartRequest(idea="Predict failures"))
    assert isinstance(actual, IdeaBriefDraft)


def test_openai_adapter_analyzes_evidence_through_strict_structured_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        supplied = json.loads(body["messages"][1]["content"])
        assert supplied["claim"]["id"] == "claim-1"
        assert supplied["chunks"][0]["chunk_id"] == "chunk-1"
        return _chat_response(_evidence_payload())

    result = _adapter(handler).analyze_evidence(
        claim={"id": "claim-1", "statement": "需要预警"},
        chunks=[
            {
                "source_id": "source-1",
                "chunk_id": "chunk-1",
                "source_type": "real_user_research",
                "content": "可核对的原文",
            }
        ],
    )

    assert result == _evidence_payload()["relations"]


def test_anthropic_adapter_analyzes_evidence_and_rejects_schema_invalid_content():
    from app.services.provider_adapters import ProviderCallError

    valid = _anthropic_adapter(lambda request: _anthropic_response(_evidence_payload()))
    result = valid.analyze_evidence(
        claim={"id": "claim-1", "statement": "需要预警"},
        chunks=[
            {
                "source_id": "source-1",
                "chunk_id": "chunk-1",
                "source_type": "real_user_research",
                "content": "可核对的原文",
            }
        ],
    )
    assert result == _evidence_payload()["relations"]

    invalid = _anthropic_adapter(
        lambda request: _anthropic_response({"relations": [{"provider_body": "secret"}]})
    )
    with pytest.raises(ProviderCallError) as caught:
        invalid.analyze_evidence(
            claim={"id": "claim-1", "statement": "需要预警"}, chunks=[]
        )
    assert caught.value.code == "invalid_content"
    assert "provider_body" not in str(caught.value)
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("status_code", "code", "retryable"),
    [(401, "unauthorized", False), (402, "quota_exhausted", False), (404, "model_not_found", False), (429, "rate_limited", True)],
)
def test_http_errors_are_safely_classified_without_response_body_leakage(status_code, code, retryable):
    from app.services.provider_adapters import ProviderCallError

    adapter = _adapter(lambda request: httpx.Response(status_code, text="secret token and provider body"))
    with pytest.raises(ProviderCallError) as caught:
        adapter.interpret_idea(QuickStartRequest(idea="Predict failures"))
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert "secret" not in str(caught.value).lower()
    assert "provider body" not in caught.value.safe_message.lower()


def test_upstream_503_preserves_safe_failure_source_metadata_without_body():
    from app.services.provider_adapters import ProviderCallError

    response = httpx.Response(
        503,
        headers={"content-type": "application/json", "retry-after": "7"},
        json={"error": {"code": "upstream_busy", "message": "do not persist this body"}},
    )
    with pytest.raises(ProviderCallError) as caught:
        _adapter(lambda _request: response).interpret_idea(
            QuickStartRequest(idea="Predict failures")
        )

    error = caught.value
    assert error.code == "provider_error"
    assert error.retryable is True
    assert error.safe_diagnostic == {
        "provider_error_source": "UPSTREAM_HTTP_503",
        "provider_error_code": "upstream_busy",
        "provider_http_status": 503,
        "provider_exception_class": None,
        "provider_failure_stage": "provider_http_response",
        "provider_retryable": True,
        "provider_retry_after_seconds_if_present": 7,
        "response_content_type": "application/json",
        "response_body_length": response.content.__len__(),
    }
    assert "do not persist" not in repr(error)


def test_missing_upstream_error_code_is_explicit_and_safe():
    from app.services.provider_adapters import ProviderCallError

    with pytest.raises(ProviderCallError) as caught:
        _adapter(lambda _request: httpx.Response(503, text="opaque provider body")).interpret_idea(
            QuickStartRequest(idea="Predict failures")
        )

    assert caught.value.safe_diagnostic["provider_error_source"] == "UPSTREAM_HTTP_503"
    assert caught.value.safe_diagnostic["provider_error_code"] == "NO_UPSTREAM_ERROR_CODE"
    assert "opaque provider body" not in repr(caught.value)


def test_timeout_is_retryable_and_safe():
    from app.services.provider_adapters import ProviderCallError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret endpoint", request=request)

    with pytest.raises(ProviderCallError) as caught:
        _adapter(handler).interpret_idea(QuickStartRequest(idea="Predict failures"))
    assert (caught.value.code, caught.value.retryable) == ("timeout", True)
    assert "secret" not in str(caught.value).lower()


def test_transport_failure_does_not_retain_authorization_header_in_exception_chain():
    sentinel = "sk-SENTINEL-AUTHORIZATION-CONTEXT"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {sentinel}"
        raise httpx.ReadTimeout("transport failed", request=request)

    with pytest.raises(Exception) as caught:
        _adapter(handler, api_key=sentinel).interpret_idea(
            QuickStartRequest(idea="Predict failures")
        )

    error = caught.value
    assert type(error).__name__ == "ProviderCallError"
    assert type(error.__cause__).__name__ == "ReadTimeout"
    assert error.__context__ is None
    assert sentinel not in repr(error)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"sk-SENTINEL-PROVIDER-BODY-not-json"),
        _chat_response({"unexpected": "sk-SENTINEL-PROVIDER-BODY"}),
    ],
)
def test_sanitized_provider_errors_do_not_retain_response_content_in_exception_chain(
    response,
):
    from app.services.provider_adapters import ProviderCallError

    with pytest.raises(ProviderCallError) as caught:
        _adapter(lambda _request: response).interpret_idea(
            QuickStartRequest(idea="Predict failures")
        )

    error = caught.value
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "sk-SENTINEL-PROVIDER-BODY" not in repr(error)


@pytest.mark.parametrize(
    "response",
    [
        lambda: httpx.Response(200, content=b"not json"),
        lambda: _chat_response({"not": "an IdeaBriefDraft"}),
    ],
)
def test_malformed_or_schema_invalid_content_is_safe(response):
    from app.services.provider_adapters import ProviderCallError

    with pytest.raises(ProviderCallError) as caught:
        _adapter(lambda request: response()).interpret_idea(QuickStartRequest(idea="Predict failures"))
    assert caught.value.code in {"malformed_response", "invalid_content"}
    assert caught.value.retryable is False


@pytest.mark.parametrize("content", [["provider body secret"], [1], [None]])
def test_anthropic_non_object_content_items_are_safe_malformed_responses(content):
    from app.services.provider_adapters import ProviderCallError

    response = httpx.Response(200, json={"content": content})
    with pytest.raises(ProviderCallError) as caught:
        _anthropic_adapter(lambda request: response).interpret_idea(QuickStartRequest(idea="Predict failures"))
    assert (caught.value.code, caught.value.retryable) == ("malformed_response", False)
    assert "provider body" not in str(caught.value).lower()
    assert "secret" not in caught.value.safe_message.lower()


def test_probe_is_explicit_and_marks_unprobed_capabilities_unknown():
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][0]["content"])
        return _chat_response({"ok": True})

    adapter = _adapter(handler)
    report = adapter.probe()
    assert report.basic_chat == "supported"
    assert report.structured_json == "supported"
    assert report.function_calling == "unknown"
    assert report.streaming == "unknown"
    assert report.checked_at.tzinfo is not None
    assert 'Reply with a JSON object only: {"ok":true}.' in prompts


def test_probe_distinguishes_a_rejected_structured_request_from_basic_chat():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if "response_format" in payload:
            return httpx.Response(400, text="do not expose this body")
        return _chat_response({"ok": True})

    report = _adapter(handler).probe()
    assert report.basic_chat == "supported"
    assert report.structured_json == "unsupported"


def test_close_releases_only_an_owned_http_client(monkeypatch):
    import app.services.provider_adapters as provider_adapters

    ModelAdapter = provider_adapters.ModelAdapter

    injected = httpx.Client(transport=httpx.MockTransport(lambda request: _chat_response({"ok": True})))
    injected_adapter = ModelAdapter(provider="openai", model="test-model", api_key="secret-value", client=injected)
    injected_adapter.close()
    assert not injected.is_closed

    owned = httpx.Client(transport=httpx.MockTransport(lambda request: _chat_response({"ok": True})))
    monkeypatch.setattr(provider_adapters.httpx, "Client", lambda **kwargs: owned)
    owned_adapter = ModelAdapter(provider="openai", model="test-model", api_key="secret-value")
    owned_adapter.close()
    assert owned_adapter.is_closed
    injected.close()



def test_live_check_sends_one_minimal_plain_chat_request_and_returns_only_safe_metadata():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-value"
        assert body["model"] == "test-model"
        assert body["max_tokens"] == 8
        assert "response_format" not in body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-live-1",
                "model": "test-model-2026-08-29",
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            },
        )

    result = _adapter(handler).live_check()

    assert len(requests) == 1
    assert result.status == "PASS"
    assert result.provider == "openai"
    assert result.model_requested == "test-model"
    assert result.model_returned == "test-model-2026-08-29"
    assert result.content_received is True
    assert result.usage_available is True
    assert result.error_code is None
    assert result.retryable is False
    assert result.secret_exposed is False
    dumped = json.dumps(result.as_dict(), ensure_ascii=False)
    assert "secret-value" not in dumped
    assert "OK" not in dumped


def test_live_check_classifies_provider_failure_without_body_or_secret_leakage():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, text="secret-value provider raw body")

    result = _adapter(handler).live_check()

    assert len(requests) == 1
    assert result.status == "FAIL"
    assert result.error_code == "unauthorized"
    assert result.retryable is False
    assert result.content_received is False
    assert result.secret_exposed is False
    dumped = json.dumps(result.as_dict(), ensure_ascii=False).lower()
    assert "secret-value" not in dumped
    assert "provider raw body" not in dumped
