"""Guarded, provider-neutral helpers for the Stage B quality evaluation.

This module deliberately does not call a provider.  It supplies the safety
boundary, trace schema, budget, and direct-baseline prompt used by the later
operator-run evaluation.  Durable Stage B receipts write full request/response
payloads only below the derived private artifact root; sanitized metadata stays
in SQLite and the normal dispatch ledger.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from app.db import Database
from app.services.provider_dispatch_ledger import ProviderDispatchLedger

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class StageBEvaluationReceiptStore:
    """Durable, sanitized evidence for one Stage B provider evaluation.

    The store keeps request/response bodies out of SQLite and logs.  Full
    payloads are written only below the private artifact root; SQLite stores
    hashes, sizes, status transitions, and the linkage to the normal provider
    dispatch ledger.
    """

    def __init__(self, *, database: Database, artifact_root: Optional[Path] = None) -> None:
        self.database = database
        root = artifact_root or (database.path.parent / "private" / "stage_b_evaluation")
        self.artifact_root = root.resolve()
        repo_root = Path(__file__).resolve().parents[2]
        if self.artifact_root == repo_root or repo_root in self.artifact_root.parents:
            raise StageBGuardError("PRIVATE_ARTIFACT_ROOT_MUST_BE_OUTSIDE_REPOSITORY")

    def create(
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
        retry_ordinal: int,
        budget_before: int,
        participant: str = STAGE_B_PARTICIPANT,
        execution_id: str | None = None,
        evaluation_type: str = "PROVIDER_CONNECTIVITY_SMOKE",
        prompt: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO stage_b_evaluation_receipts(
                    evaluation_id, execution_id, idea_id, evaluation_type,
                    execution_mode, participant_id, provider, model, operation,
                    prompt_template_version, context_version, retry_ordinal,
                    status, created_at, budget_before, budget_after,
                    prompt_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CREATED', ?, ?, ?, ?)
                """,
                (
                    evaluation_id, execution_id, idea_id, evaluation_type,
                    execution_mode, participant, provider, model, operation,
                    prompt_version, context_version, retry_ordinal, _utc_now(),
                    budget_before, budget_before, _sha256(prompt) if prompt is not None else None,
                ),
            )

    def create_dry_check(
        self,
        *,
        evaluation_id: str,
        idea_id: str,
        participant: str = STAGE_B_PARTICIPANT,
        max_transports: int = DEFAULT_STAGE_B_TRANSPORT_BUDGET,
    ) -> dict[str, Any]:
        """Create a durable Stage-B observability receipt without a provider call.

        This is deliberately a store-level operator primitive rather than a
        provider execution path: it creates no dispatch permit/event, does not
        touch provider credentials, and never consumes transport budget.
        """
        evaluate_stage_b_guard(
            real_provider_stage_b=True,
            safe_fixture_mode=False,
            accounts_enabled=False,
            participant_id=participant,
        )
        if max_transports <= 0:
            raise ValueError("max_transports must be positive")
        budget_before = max_transports - self.consumed_count()
        if budget_before < 0:
            raise StageBGuardError("STAGE_B_TRANSPORT_BUDGET_EXHAUSTED")
        self.create(
            evaluation_id=evaluation_id,
            idea_id=idea_id,
            execution_mode="DRY_OBSERVABILITY",
            operation="observability_dry_check",
            provider=STAGE_B_PROVIDER,
            model=STAGE_B_MODEL,
            prompt_version="stage-b-observability-dry-v1",
            context_version=CONTEXT_VERSION,
            retry_ordinal=0,
            budget_before=budget_before,
            participant=participant,
            execution_id=evaluation_id,
            evaluation_type="OBSERVABILITY_CLOUD_DRY_CHECK",
            prompt=None,
        )
        self.mark_dry_success(evaluation_id)
        self.write_artifact(
            evaluation_id,
            prompt=None,
            response={
                "kind": "OBSERVABILITY_CLOUD_DRY_CHECK",
                "synthetic": True,
                "message": "stage-b durable observability verification",
            },
        )
        return self.inspect(evaluation_id)

    def mark_dry_success(self, evaluation_id: str) -> None:
        """Finalize a dry receipt without setting any transport fields."""
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE stage_b_evaluation_receipts
                SET status='DRY_SUCCEEDED', response_non_empty=1,
                    decode_status='NOT_APPLICABLE',
                    schema_validation='NOT_APPLICABLE',
                    application_postprocess='NOT_APPLICABLE',
                    failure_classification='NONE'
                WHERE evaluation_id=?
                """,
                (evaluation_id,),
            )

    def mark_dispatch_prepared(self, evaluation_id: str, *, permit_id: str | None = None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE stage_b_evaluation_receipts
                SET status='DISPATCH_PREPARED', dispatch_permit_id=?,
                    dispatch_ordinal=1, dispatch_count=1, dispatch_prepared_at=?
                WHERE evaluation_id=?
                """,
                (permit_id, _utc_now(), evaluation_id),
            )

    def mark_transport_started(self, evaluation_id: str) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT budget_before FROM stage_b_evaluation_receipts WHERE evaluation_id=?",
                (evaluation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(evaluation_id)
            transport_ordinal = connection.execute(
                "SELECT COALESCE(MAX(transport_ordinal), 0) + 1 FROM stage_b_evaluation_receipts "
                "WHERE transport_attempted=1"
            ).fetchone()[0]
            connection.execute(
                """
                UPDATE stage_b_evaluation_receipts
                SET status='TRANSPORT_ATTEMPTED', transport_attempted=1,
                    transport_ordinal=?, transport_count=1,
                    transport_started_at=?, budget_consumed=1,
                    budget_after=budget_before-1
                WHERE evaluation_id=?
                """,
                (transport_ordinal, _utc_now(), evaluation_id),
            )

    def mark_success(
        self,
        evaluation_id: str,
        *,
        response: Mapping[str, Any],
        started_at: float,
        response_timestamp: float,
        schema_validation: str = "PASS",
        application_postprocess: str = "PASS",
    ) -> None:
        usage = response.get("usage")
        usage_mapping = usage if isinstance(usage, Mapping) else {}
        content = response.get("content")
        self._update_result(
            evaluation_id,
            status="SUCCEEDED",
            response_non_empty=bool(content),
            decode_status="PASS",
            schema_validation=schema_validation,
            application_postprocess=application_postprocess,
            failure_classification=None,
            failure_reason=None,
            response_timestamp=response_timestamp,
            started_at=started_at,
            response_sha256=_sha256(response),
            input_token_count=_usage_value(usage_mapping, "input", "prompt_tokens"),
            output_token_count=_usage_value(usage_mapping, "output", "completion_tokens"),
            total_token_count=_usage_value(usage_mapping, "total", "total_tokens"),
        )

    def mark_failure(
        self,
        evaluation_id: str,
        *,
        error: Exception,
        started_at: float,
        response_timestamp: float,
    ) -> None:
        self._update_result(
            evaluation_id,
            status="FAILED",
            response_non_empty=False,
            decode_status="NOT_APPLICABLE",
            schema_validation="NOT_APPLICABLE",
            application_postprocess="NOT_APPLICABLE",
            failure_classification=classify_provider_failure(error),
            failure_reason=str(error)[:240],
            response_timestamp=response_timestamp,
            started_at=started_at,
            response_sha256=None,
            input_token_count=None,
            output_token_count=None,
            total_token_count=None,
        )

    def write_artifact(
        self,
        evaluation_id: str,
        *,
        prompt: str | None,
        response: Mapping[str, Any],
    ) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_name = hashlib.sha256(evaluation_id.encode("utf-8")).hexdigest() + ".json"
        path = self.artifact_root / artifact_name
        payload = json.dumps(
            {"prompt": prompt, "response": response},
            ensure_ascii=False,
            indent=2,
            default=str,
        ).encode("utf-8")
        path.write_bytes(payload)
        request_bytes = len(prompt.encode("utf-8")) if prompt is not None else 0
        response_bytes = len(json.dumps(response, ensure_ascii=False, default=str).encode("utf-8"))
        digest = hashlib.sha256(payload).hexdigest()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE stage_b_evaluation_receipts
                SET artifact_relative_path=?, artifact_sha256=?, request_bytes=?,
                    response_bytes=?, artifact_persistence_status='PASS'
                WHERE evaluation_id=?
                """,
                (path.relative_to(self.artifact_root).as_posix(), digest,
                 request_bytes, response_bytes, evaluation_id),
            )

    def mark_artifact_failure(self, evaluation_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE stage_b_evaluation_receipts SET artifact_persistence_status='FAIL' WHERE evaluation_id=?",
                (evaluation_id,),
            )

    def inspect(self, evaluation_id: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM stage_b_evaluation_receipts WHERE evaluation_id=?",
            (evaluation_id,),
        )
        if row is None:
            raise KeyError(evaluation_id)
        relative = row.get("artifact_relative_path")
        artifact = self.artifact_root / relative if relative else None
        row["artifact_exists"] = bool(artifact and artifact.is_file())
        row["artifact_hash_available"] = bool(row.get("artifact_sha256"))
        row["artifact_bytes"] = artifact.stat().st_size if artifact and artifact.is_file() else None
        return row

    def consumed_count(self) -> int:
        row = self.database.fetch_one(
            "SELECT COALESCE(SUM(budget_consumed), 0) AS consumed FROM stage_b_evaluation_receipts"
        )
        return int(row["consumed"] if row else 0)

    def _update_result(self, evaluation_id: str, *, status: str, response_non_empty: bool,
                       decode_status: str, schema_validation: str,
                       application_postprocess: str, failure_classification: str | None,
                       failure_reason: str | None, response_timestamp: float,
                       started_at: float, response_sha256: str | None,
                       input_token_count: int | None, output_token_count: int | None,
                       total_token_count: int | None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE stage_b_evaluation_receipts
                SET status=?, response_non_empty=?, decode_status=?, schema_validation=?,
                    application_postprocess=?, failure_classification=?, failure_reason=?,
                    transport_completed_at=?, latency_ms=?, response_sha256=?,
                    input_token_count=?, output_token_count=?, total_token_count=?
                WHERE evaluation_id=?
                """,
                (status, int(response_non_empty), decode_status, schema_validation,
                 application_postprocess, failure_classification, failure_reason,
                 datetime.fromtimestamp(response_timestamp, timezone.utc).isoformat(),
                 round((response_timestamp - started_at) * 1000, 3), response_sha256,
                 input_token_count, output_token_count, total_token_count, evaluation_id),
            )


class StageBExecutionHarness:
    """One-call-at-a-time evaluator with explicit manual retry semantics."""

    def __init__(
        self,
        *,
        max_transports: int = DEFAULT_STAGE_B_TRANSPORT_BUDGET,
        private_artifact_root: Optional[Path] = None,
        database: Database | None = None,
        dispatch_ledger: ProviderDispatchLedger | None = None,
    ) -> None:
        if max_transports <= 0:
            raise ValueError("max_transports must be positive")
        self.max_transports = max_transports
        self.database = database
        if database is not None:
            database.init_schema()
        self.receipt_store = (
            StageBEvaluationReceiptStore(database=database, artifact_root=private_artifact_root)
            if database is not None else None
        )
        self.dispatch_ledger = dispatch_ledger or (
            ProviderDispatchLedger(database) if database is not None else None
        )
        self.transport_count = self.receipt_store.consumed_count() if self.receipt_store else 0
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
        dispatch_permit_id: str | None = None,
    ) -> Mapping[str, Any]:
        if execution_mode not in {"INSIGHTFORGE", "DIRECT_BASELINE"}:
            raise ValueError("invalid execution_mode")
        if self.receipt_store is not None:
            self.transport_count = self.receipt_store.consumed_count()
        if self.transport_count >= self.max_transports:
            raise StageBGuardError("TRANSPORT_BUDGET_EXHAUSTED")

        started = time.time()
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
        if self.receipt_store is not None:
            self.receipt_store.create(
                evaluation_id=evaluation_id,
                execution_id=evaluation_id,
                idea_id=idea_id,
                execution_mode=execution_mode,
                operation=operation,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                context_version=context_version,
                retry_ordinal=retry_ordinal,
                budget_before=self.max_transports - self.transport_count,
                prompt=prompt,
            )
            self.receipt_store.mark_dispatch_prepared(
                evaluation_id, permit_id=dispatch_permit_id
            )
            if dispatch_permit_id and self.dispatch_ledger is not None:
                self.dispatch_ledger.record_event(
                    dispatch_permit_id,
                    "CALL_BOUNDARY_ENTERED",
                    {"evaluation_id": evaluation_id, "dispatch_ordinal": 1},
                )
            self.receipt_store.mark_transport_started(evaluation_id)
        self.transport_count += 1
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
            if self.receipt_store is not None:
                response_timestamp = time.time()
                self.receipt_store.mark_success(
                    evaluation_id,
                    response=response,
                    started_at=started,
                    response_timestamp=response_timestamp,
                )
                if dispatch_permit_id and self.dispatch_ledger is not None:
                    self.dispatch_ledger.record_event(
                        dispatch_permit_id,
                        "PROVIDER_RESPONSE_RECEIVED",
                        {"evaluation_id": evaluation_id, "status": "SUCCESS"},
                    )
                try:
                    self.receipt_store.write_artifact(
                        evaluation_id, prompt=prompt, response=response
                    )
                except Exception:
                    self.receipt_store.mark_artifact_failure(evaluation_id)
                if dispatch_permit_id and self.dispatch_ledger is not None:
                    self.dispatch_ledger.record_event(
                        dispatch_permit_id,
                        "COMPLETED",
                        {"evaluation_id": evaluation_id, "status": "SUCCESS"},
                    )
            elif self.private_artifact_root is not None:
                self._write_private_artifact(evaluation_id, prompt, response)
            return response
        except Exception as error:
            trace["failure_classification"] = classify_provider_failure(error)
            trace["failure_reason"] = str(error)[:240]
            if self.receipt_store is not None:
                response_timestamp = time.time()
                self.receipt_store.mark_failure(
                    evaluation_id,
                    error=error,
                    started_at=started,
                    response_timestamp=response_timestamp,
                )
                if dispatch_permit_id and self.dispatch_ledger is not None:
                    event_type = (
                        "TIMEOUT_AFTER_BOUNDARY"
                        if trace["failure_classification"] == "TIMEOUT"
                        else "PROVIDER_HTTP_ERROR_RECEIVED"
                        if trace["failure_classification"] in {"AUTH", "PROVIDER_4XX", "PROVIDER_5XX"}
                        else "TRANSPORT_ERROR_AFTER_BOUNDARY"
                    )
                    self.dispatch_ledger.record_event(
                        dispatch_permit_id,
                        event_type,
                        {
                            "evaluation_id": evaluation_id,
                            "failure_classification": trace["failure_classification"],
                        },
                    )
                try:
                    self.receipt_store.write_artifact(
                        evaluation_id,
                        prompt=prompt,
                        response={"error_classification": trace["failure_classification"]},
                    )
                except Exception:
                    self.receipt_store.mark_artifact_failure(evaluation_id)
                if dispatch_permit_id and self.dispatch_ledger is not None:
                    self.dispatch_ledger.record_event(
                        dispatch_permit_id,
                        "COMPLETED",
                        {"evaluation_id": evaluation_id, "status": "FAILED"},
                    )
            elif self.private_artifact_root is not None:
                self._write_private_artifact(evaluation_id, prompt, {"error_classification": trace["failure_classification"]})
            raise
        finally:
            trace["response_timestamp"] = time.time()
            trace["latency_ms"] = round((trace["response_timestamp"] - started) * 1000, 3)
            self.traces.append(trace)

    def inspect(self, evaluation_id: str) -> dict[str, Any]:
        if self.receipt_store is None:
            raise StageBGuardError("DURABLE_RECEIPT_STORE_REQUIRED")
        return self.receipt_store.inspect(evaluation_id)

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
