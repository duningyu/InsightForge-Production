from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.db import Database
from app.schemas import IdeaBriefDraft
from app.services.ai_runtime import ManagedModelStructuredRuntime
from app.services.async_generation import AsyncGenerationRepository
from app.services.provider_adapters import AsyncModelAdapter
from app.services.provider_dispatch_ledger import DispatchClassification, ProviderDispatchLedger
from app.services.dispatch_control import DispatchControlContext


def _brief() -> IdeaBriefDraft:
    return IdeaBriefDraft(
        original_idea="Synthetic acceptance idea",
        target_user="synthetic users",
        problem="A synthetic problem",
        desired_outcome="A synthetic outcome",
        provenance={"target_user": "user_input"},
    )


def _solution_payload() -> dict[str, object]:
    item = {
        "mechanism": "rule_based", "summary": "synthetic summary", "why_fit": "synthetic fit",
        "user_flow": ["step"], "mvp_pages": ["page"], "features": ["feature"],
        "inputs": ["input"], "outputs": ["output"], "decision_logic": ["logic"],
        "data_requirements": ["data"], "technical_components": ["component"],
        "implementation_plan": ["plan"], "acceptance_cases": ["case"],
        "risks": ["risk"], "unknowns": ["unknown"], "complexity": "low",
        "provenance": "model_hypothesis", "required_data_class": "synthetic",
        "automation_level": "low", "human_role": "reviews", "core_decision_logic": "logic",
        "major_dependency": "none", "requires_llm_runtime": False,
        "requires_rag_runtime": False, "requires_agent_runtime": False,
    }
    return {"candidates": [{**item, "title": "Synthetic rules"}, {**item, "title": "Synthetic workflow"}]}


def _context(execution_id: str = "acceptance-integration-1") -> DispatchControlContext:
    return DispatchControlContext(
        acceptance_execution_id=execution_id,
        forward_ledger_epoch_id="epoch-test",
        beta_instance="beta001",
        expected_provider="bailian",
        expected_model="qwen3.7-flash",
    )


def _runtime(db: Database, handler, calls: list[httpx.Request]) -> ManagedModelStructuredRuntime:
    ledger = ProviderDispatchLedger(db)

    def factory(**kwargs):
        return AsyncModelAdapter(
            **kwargs,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    return ManagedModelStructuredRuntime(
        provider="qwen",
        model="qwen3.7-flash",
        api_key="synthetic-only",
        dispatch_ledger=ledger,
        async_adapter_factory=factory,
    )


def test_normal_async_managed_path_acquires_permit_and_records_dispatch(tmp_path):
    db = Database(tmp_path / "integration.sqlite3")
    db.init_schema()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_solution_payload())}}]})

    runtime = _runtime(db, handler, calls)
    result = asyncio.run(runtime.async_design_solutions(_brief(), dispatch_control=_context()))

    assert len(result.candidates) == 2
    assert len(calls) == 1
    ledger = ProviderDispatchLedger(db)
    assert ledger.classify("acceptance-integration-1") is DispatchClassification.CONFIRMED_PROVIDER_DISPATCH
    with db.connect() as cx:
        assert cx.execute("SELECT COUNT(*) FROM provider_dispatch_permits").fetchone()[0] == 1
        assert cx.execute("SELECT COUNT(*) FROM provider_dispatch_events WHERE event_type='CALL_BOUNDARY_ENTERED'").fetchone()[0] == 1
        assert cx.execute("SELECT COUNT(*) FROM provider_dispatch_events WHERE event_type='PROVIDER_RESPONSE_RECEIVED'").fetchone()[0] == 1


def test_same_acceptance_execution_replay_cannot_dispatch_twice(tmp_path):
    db = Database(tmp_path / "replay.sqlite3")
    db.init_schema()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_solution_payload())}}]})

    runtime = _runtime(db, handler, calls)
    control = _context("acceptance-replay-1")
    asyncio.run(runtime.async_design_solutions(_brief(), dispatch_control=control))
    with pytest.raises(Exception):
        asyncio.run(runtime.async_design_solutions(_brief(), dispatch_control=control))
    assert len(calls) == 1


def test_timeout_after_boundary_is_indeterminate_and_replay_is_blocked(tmp_path):
    db = Database(tmp_path / "timeout.sqlite3")
    db.init_schema()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    runtime = _runtime(db, handler, calls)
    control = _context("acceptance-timeout-1")
    with pytest.raises(Exception, match="MODEL_TIMEOUT"):
        asyncio.run(runtime.async_design_solutions(_brief(), dispatch_control=control))
    assert ProviderDispatchLedger(db).classify("acceptance-timeout-1") is DispatchClassification.POSSIBLY_DISPATCHED_INDETERMINATE
    with pytest.raises(Exception):
        asyncio.run(runtime.async_design_solutions(_brief(), dispatch_control=control))
    assert len(calls) == 1


def test_strict_adapter_without_permit_fails_before_fake_network(tmp_path):
    db = Database(tmp_path / "missing-permit.sqlite3")
    db.init_schema()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    adapter = AsyncModelAdapter(
        provider="qwen", model="qwen3.7-flash", api_key="synthetic-only",
        dispatch_ledger=ProviderDispatchLedger(db), dispatch_control=_context("missing-permit-1"),
        dispatch_permit_id="not-a-real-permit", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(Exception, match="dispatch_control_invalid"):
        asyncio.run(adapter.design_solutions_async(_brief()))
    asyncio.run(adapter.aclose())
    assert calls == []


def test_async_acceptance_context_survives_repository_reconstruction(tmp_path):
    db = Database(tmp_path / "durability.sqlite3")
    db.init_schema()
    first = AsyncGenerationRepository(db)
    control = _context("acceptance-durable-1")
    created = first.create_or_replay("participant", "project", "idempotency", dispatch_control=control)

    reconstructed = AsyncGenerationRepository(db)
    replay = reconstructed.create_or_replay("participant", "project", "idempotency", dispatch_control=control)
    assert replay.generation_run_id == created.generation_run_id
    assert replay.dispatch_control == control
