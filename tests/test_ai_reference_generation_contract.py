from __future__ import annotations

import asyncio

import httpx

from app.services.generation_contracts import REFERENCE_FIELDS


def test_ai_reference_generation_prompt_requires_substantive_reference_output(monkeypatch):
    from app.services.provider_adapters import AsyncModelAdapter, ModelAdapter

    sync_prompts: list[str] = []
    async_prompts: list[str] = []

    def capture_sync(_adapter, *, output_model, system, user):
        sync_prompts.append(system)
        return object()

    async def capture_async(_adapter, *, output_model, system, user):
        async_prompts.append(system)
        return object()

    monkeypatch.setattr(ModelAdapter, "_generate", capture_sync)
    monkeypatch.setattr(AsyncModelAdapter, "_generate_async", capture_async)

    sync_client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    sync_adapter = ModelAdapter(provider="openai", model="test", api_key="test", client=sync_client)
    try:
        sync_adapter.generate_ai_reference({"original_idea": "求职进度管理工具"})
    finally:
        sync_client.close()

    async def exercise_async() -> None:
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        async_adapter = AsyncModelAdapter(provider="openai", model="test", api_key="test", client=async_client)
        try:
            await async_adapter.generate_ai_reference_async({"original_idea": "求职进度管理工具"})
        finally:
            await async_client.aclose()

    asyncio.run(exercise_async())

    assert len(sync_prompts) == len(async_prompts) == 1
    for prompt in (*sync_prompts, *async_prompts):
        lowered = prompt.casefold()
        assert "at least one" in lowered
        assert "uncertainty_notice" in prompt
        assert "only non-empty" in lowered
        assert all(field in prompt for field in REFERENCE_FIELDS)
        assert "unverified hypothesis" in lowered
        assert "research findings" in lowered or "market facts" in lowered
