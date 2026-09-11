from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.main import create_app
from app.config import Settings
from app.services.stage_b_evaluation import (
    DIRECT_BASELINE_PROMPT_VERSION,
    INSIGHTFORGE_PROMPT_VERSION,
    StageBExecutionHarness,
    StageBGuardError,
    StageBProviderError,
    build_direct_baseline_prompt,
    classify_provider_failure,
    evaluate_stage_b_guard,
)


def test_stage_b_guard_is_default_deny_and_requires_stage_b_scope() -> None:
    with pytest.raises(StageBGuardError, match="REAL_PROVIDER_STAGE_B_REQUIRED"):
        evaluate_stage_b_guard(
            real_provider_stage_b=False,
            safe_fixture_mode=False,
            accounts_enabled=False,
            participant_id="railway_stage_b",
        )

    with pytest.raises(StageBGuardError, match="SAFE_FIXTURE_MUST_BE_OFF"):
        evaluate_stage_b_guard(
            real_provider_stage_b=True,
            safe_fixture_mode=True,
            accounts_enabled=False,
            participant_id="railway_stage_b",
        )

    with pytest.raises(StageBGuardError, match="STAGE_B_PARTICIPANT_REQUIRED"):
        evaluate_stage_b_guard(
            real_provider_stage_b=True,
            safe_fixture_mode=False,
            accounts_enabled=False,
            participant_id="beta_003",
        )

    assert evaluate_stage_b_guard(
        real_provider_stage_b=True,
        safe_fixture_mode=False,
        accounts_enabled=False,
        participant_id="railway_stage_b",
    ).allowed


def test_app_rejects_real_provider_stage_b_outside_scope(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="REAL_PROVIDER_STAGE_B_SCOPE_REJECTED"):
        create_app(
            database_path=tmp_path / "db.sqlite3",
            seed=False,
            settings_override=Settings(
                real_provider_stage_b=True,
                safe_fixture_mode=False,
                accounts_enabled=False,
                beta_participant_id="beta_003",
            ),
        )


def test_direct_baseline_is_frozen_and_receives_only_raw_idea() -> None:
    prompt = build_direct_baseline_prompt("帮我做一个面向小团队的会议决策工具")

    assert DIRECT_BASELINE_PROMPT_VERSION == "stage-b-direct-baseline-v1"
    assert "帮我做一个面向小团队的会议决策工具" in prompt
    assert "InsightForge" not in prompt
    assert "用户上下文" not in prompt
    assert "提出3个可行产品方案" in prompt


def test_harness_records_modes_latency_usage_and_never_auto_retries() -> None:
    calls: list[str] = []
    harness = StageBExecutionHarness(max_transports=2)

    response = harness.execute(
        evaluation_id="eval-1",
        idea_id="idea_A",
        execution_mode="INSIGHTFORGE",
        operation="ai_reference",
        provider="bailian",
        model="qwen3.7-flash",
        prompt_version=INSIGHTFORGE_PROMPT_VERSION,
        context_version="stage-b-context-v1",
        transport=lambda: (calls.append("one") or {"content": "ok", "usage": {"total": 7}}),
    )

    assert response["content"] == "ok"
    assert calls == ["one"]
    assert harness.transport_count == 1
    trace = harness.traces[0]
    assert trace["execution_mode"] == "INSIGHTFORGE"
    assert trace["input_token_count"] is None or trace["input_token_count"] >= 0
    assert trace["output_token_count"] is None or trace["output_token_count"] >= 0
    assert trace["total_token_count"] == 7
    assert trace["retry_ordinal"] == 0
    assert "prompt" not in trace
    assert "response" not in trace


def test_failure_is_classified_without_retry_and_explicit_retry_is_new_attempt() -> None:
    calls = 0
    harness = StageBExecutionHarness(max_transports=3)

    def fail_once_then_succeed() -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise StageBProviderError("timeout", classification="TIMEOUT")
        return {"content": "recovered"}

    with pytest.raises(StageBProviderError):
        harness.execute(
            evaluation_id="eval-1",
            idea_id="idea_A",
            execution_mode="INSIGHTFORGE",
            operation="solutions",
            provider="bailian",
            model="qwen3.7-flash",
            prompt_version="stage-b-solution-v1",
            context_version="stage-b-context-v1",
            transport=fail_once_then_succeed,
        )

    assert calls == 1
    assert harness.traces[-1]["failure_classification"] == "TIMEOUT"
    assert harness.traces[-1]["retry_ordinal"] == 0

    recovered = harness.execute(
        evaluation_id="eval-1",
        idea_id="idea_A",
        execution_mode="INSIGHTFORGE",
        operation="solutions",
        provider="bailian",
        model="qwen3.7-flash",
        prompt_version="stage-b-solution-v1",
        context_version="stage-b-context-v1",
        transport=fail_once_then_succeed,
        retry_ordinal=1,
    )

    assert recovered["content"] == "recovered"
    assert calls == 2
    assert harness.transport_count == 2
    assert harness.traces[-1]["retry_ordinal"] == 1


def test_budget_fails_closed_at_twelve_transports() -> None:
    harness = StageBExecutionHarness(max_transports=1)
    kwargs = dict(
        evaluation_id="eval-1",
        idea_id="idea_A",
        execution_mode="DIRECT_BASELINE",
        operation="solutions",
        provider="bailian",
        model="qwen3.7-flash",
        prompt_version=DIRECT_BASELINE_PROMPT_VERSION,
        context_version="stage-b-context-v1",
        transport=lambda: {"content": "ok"},
    )
    harness.execute(**kwargs)

    with pytest.raises(StageBGuardError, match="TRANSPORT_BUDGET_EXHAUSTED"):
        harness.execute(**kwargs, retry_ordinal=1)


def test_private_artifact_contains_full_payload_but_trace_does_not(tmp_path: Path) -> None:
    harness = StageBExecutionHarness(
        max_transports=1,
        private_artifact_root=tmp_path / "stage_b_evaluation",
    )
    response = {"content": "private response", "usage": {"total": 3}}
    prompt = "private prompt must not enter normal logs"

    harness.execute(
        evaluation_id="eval-1",
        idea_id="idea_A",
        execution_mode="INSIGHTFORGE",
        operation="ai_reference",
        provider="bailian",
        model="qwen3.7-flash",
        prompt_version=INSIGHTFORGE_PROMPT_VERSION,
        context_version="stage-b-context-v1",
        prompt=prompt,
        transport=lambda: response,
    )

    artifact = next((tmp_path / "stage_b_evaluation").glob("*.json"))
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["prompt"] == prompt
    assert payload["response"] == response
    assert prompt not in json.dumps(harness.traces)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (StageBProviderError("x", classification="AUTH"), "AUTH"),
        (StageBProviderError("x", classification="PROVIDER_5XX"), "PROVIDER_5XX"),
        (ValueError("invalid response"), "UNKNOWN"),
    ],
)
def test_provider_failure_classification(error: Exception, expected: str) -> None:
    assert classify_provider_failure(error) == expected
