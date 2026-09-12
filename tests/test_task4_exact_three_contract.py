from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.schemas import IdeaBriefDraft, QuickStartRequest, SolutionSetDraft


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"


def _brief() -> IdeaBriefDraft:
    return IdeaBriefDraft(
        original_idea="Predict failures",
        target_user="operators",
        problem="Unplanned downtime",
        desired_outcome="Earlier action",
        provenance={
            "original_idea": "user_input",
            "target_user": "user_input",
            "problem": "model_hypothesis",
            "desired_outcome": "model_hypothesis",
        },
    )


def test_solution_set_schema_requires_exactly_three_complete_candidates():
    from app.services.ai_runtime import DeterministicDemoRuntime

    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    candidates = runtime.design_solutions(
        runtime.interpret_idea(QuickStartRequest(idea="帮小型便利店减少缺货"))
    ).candidates

    with pytest.raises(ValidationError):
        SolutionSetDraft(candidates=list(candidates[:2]))

    incomplete_candidates = [candidate.model_dump(mode="json") for candidate in candidates]
    incomplete_candidates[0]["summary"] = ""
    with pytest.raises(ValidationError):
        SolutionSetDraft(candidates=incomplete_candidates)


def test_provider_adapters_request_exactly_three_solutions(monkeypatch):
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
        sync_adapter.design_solutions(_brief())
    finally:
        sync_client.close()

    async def exercise_async() -> None:
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
        async_adapter = AsyncModelAdapter(provider="openai", model="test", api_key="test", client=async_client)
        try:
            await async_adapter.design_solutions_async(_brief())
        finally:
            await async_client.aclose()

    asyncio.run(exercise_async())

    assert len(sync_prompts) == len(async_prompts) == 1
    for prompt in (*sync_prompts, *async_prompts):
        assert "exactly 3" in prompt.casefold()
        assert "2-3" not in prompt
        assert "2–3" not in prompt


def test_deterministic_domain_rejects_a_non_three_solution_case(monkeypatch):
    from app.services.ai_runtime import DeterministicDemoRuntime, StructuredRuntimeUnavailableError

    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    brief = runtime.interpret_idea(QuickStartRequest(idea="帮小型便利店减少缺货"))
    _, original_case = runtime._case_for_text(brief.original_idea)
    two_solution_case = {**original_case, "solutions": original_case["solutions"][:2]}
    monkeypatch.setattr(runtime, "_case_for_text", lambda _text: ("two", two_solution_case))

    with pytest.raises(StructuredRuntimeUnavailableError, match="exactly three"):
        runtime.design_solutions(brief)
