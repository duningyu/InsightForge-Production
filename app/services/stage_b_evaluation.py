"""Guarded, provider-neutral helpers for the Stage B quality evaluation.

This module deliberately does not call a provider.  It supplies the safety
boundary, trace schema, budget, and direct-baseline prompt used by the later
operator-run evaluation.  Full request/response payloads are written only to
an explicitly supplied private artifact directory.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

STAGE_B_PROVIDER = "bailian"
STAGE_B_MODEL = "qwen3.7-flash"
STAGE_B_PARTICIPANT = "railway_stage_b"
DEFAULT_STAGE_B_TRANSPORT_BUDGET = 12
INSIGHTFORGE_PROMPT_VERSION = "stage-b-insightforge-v1"
DIRECT_BASELINE_PROMPT_VERSION = "stage-b-direct-baseline-v1"
CONTEXT_VERSION = "stage-b-context-v1"
_FAILURE_CLASSES = {
    "NETWORK",
    "AUTH",
    "RATE_LIMIT",
    "TIMEOUT",
    "PROVIDER_4XX",
    "PROVIDER_5XX",
    "INVALID_RESPONSE",
    "SCHEMA_VALIDATION",
    "APPLICATION_POSTPROCESS",
    "UNKNOWN",
}


class StageBGuardError(RuntimeError):
    """Raised when Stage B real-provider execution is not safely scoped."""


class StageBProviderError(RuntimeError):
    """A provider failure carrying a stable, non-secret classification."""

    def __init__(self, message: str, *, classification: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.classification = classification if classification in _FAILURE_CLASSES else "UNKNOWN"


@dataclass(frozen=True)
class StageBGuardDecision:
    allowed: bool
    reason: str


def evaluate_stage_b_guard(
    *,
    real_provider_stage_b: bool,
    safe_fixture_mode: bool,
    accounts_enabled: bool,
    participant_id: Optional[str],
) -> StageBGuardDecision:
    """Fail closed unless the explicit, isolated Stage B contract is met."""

    if not real_provider_stage_b:
        raise StageBGuardError("REAL_PROVIDER_STAGE_B_REQUIRED")
    if safe_fixture_mode:
        raise StageBGuardError("SAFE_FIXTURE_MUST_BE_OFF")
    if accounts_enabled:
        raise StageBGuardError("ACCOUNTS_MUST_BE_DISABLED")
    if participant_id != STAGE_B_PARTICIPANT:
        raise StageBGuardError("STAGE_B_PARTICIPANT_REQUIRED")
    return StageBGuardDecision(allowed=True, reason="STAGE_B_SCOPE_VALID")


def build_direct_baseline_prompt(raw_idea: str) -> str:
    """Build the frozen control prompt without InsightForge-added context."""

    return (
        "根据下面这段原始产品想法，分析用户问题，并提出3个可行产品方案。"
        "请明确每个方案的核心取舍、MVP范围、主要风险和适用条件。\n\n"
        f"原始产品想法：\n{raw_idea}"
    )


def classify_provider_failure(error: Exception) -> str:
    classification = getattr(error, "classification", None)
    if classification in _FAILURE_CLASSES:
        return str(classification)
    return "UNKNOWN"


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _usage_value(usage: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return None


class StageBExecutionHarness:
    """One-call-at-a-time evaluator with explicit manual retry semantics."""

    def __init__(
        self,
        *,
        max_transports: int = DEFAULT_STAGE_B_TRANSPORT_BUDGET,
        private_artifact_root: Optional[Path] = None,
    ) -> None:
        if max_transports <= 0:
            raise ValueError("max_transports must be positive")
        self.max_transports = max_transports
        self.transport_count = 0
        self.traces: list[dict[str, Any]] = []
        if private_artifact_root is not None:
            artifact_root = private_artifact_root.resolve()
            repo_root = Path(__file__).resolve().parents[2]
            if artifact_root == repo_root or repo_root in artifact_root.parents:
                raise StageBGuardError("PRIVATE_ARTIFACT_ROOT_MUST_BE_OUTSIDE_REPOSITORY")
            self.private_artifact_root = artifact_root
        else:
            self.private_artifact_root = None

    def execute(
        self,
        *,
        evaluation_id: str,
        idea_id: str,
        execution_mode: str,
        operation: str,
        provider: str,
        model: str,
        prompt_version: str,
        context_version: str,
        transport: Callable[[], Mapping[str, Any]],
        prompt: Optional[str] = None,
        retry_ordinal: int = 0,
    ) -> Mapping[str, Any]:
        if execution_mode not in {"INSIGHTFORGE", "DIRECT_BASELINE"}:
            raise ValueError("invalid execution_mode")
        if self.transport_count >= self.max_transports:
            raise StageBGuardError("TRANSPORT_BUDGET_EXHAUSTED")

        started = time.time()
        self.transport_count += 1
        trace: dict[str, Any] = {
            "evaluation_id": evaluation_id,
            "idea_id": idea_id,
            "execution_mode": execution_mode,
            "operation": operation,
            "provider": provider,
            "model": model,
            "prompt_template_version": prompt_version,
            "context_version": context_version,
            "request_timestamp": started,
            "response_timestamp": None,
            "latency_ms": None,
            "retry_ordinal": retry_ordinal,
            "generation_id": None,
            "schema_validation": "NOT_RECORDED",
            "status": "FAILED",
            "failure_classification": None,
            "failure_reason": None,
            "input_token_count": None,
            "output_token_count": None,
            "total_token_count": None,
            "estimated_cost": None,
            "prompt_sha256": _sha256(prompt) if prompt is not None else None,
            "response_sha256": None,
        }
        try:
            response = transport()
            if not isinstance(response, Mapping):
                raise StageBProviderError("invalid provider response", classification="INVALID_RESPONSE")
            usage = response.get("usage")
            usage_mapping = usage if isinstance(usage, Mapping) else {}
            trace["input_token_count"] = _usage_value(usage_mapping, "input", "prompt_tokens")
            trace["output_token_count"] = _usage_value(usage_mapping, "output", "completion_tokens")
            trace["total_token_count"] = _usage_value(usage_mapping, "total", "total_tokens")
            trace["response_sha256"] = _sha256(response)
            trace["schema_validation"] = "PASS"
            trace["status"] = "SUCCESS"
            if self.private_artifact_root is not None:
                self._write_private_artifact(evaluation_id, prompt, response)
            return response
        except Exception as error:
            trace["failure_classification"] = classify_provider_failure(error)
            trace["failure_reason"] = str(error)[:240]
            if self.private_artifact_root is not None:
                self._write_private_artifact(evaluation_id, prompt, {"error_classification": trace["failure_classification"]})
            raise
        finally:
            trace["response_timestamp"] = time.time()
            trace["latency_ms"] = round((trace["response_timestamp"] - started) * 1000, 3)
            self.traces.append(trace)

    def _write_private_artifact(
        self,
        evaluation_id: str,
        prompt: str | None,
        response: Mapping[str, Any],
    ) -> None:
        assert self.private_artifact_root is not None
        self.private_artifact_root.mkdir(parents=True, exist_ok=True)
        path = self.private_artifact_root / f"{evaluation_id}-{len(self.traces) + 1}.json"
        path.write_text(
            json.dumps({"prompt": prompt, "response": response}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
