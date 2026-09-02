from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class GenerationClaim:
    owner: bool
    error_code: str | None = None
    payload: dict[str, Any] | None = None
    status_code: int | None = None


@dataclass(slots=True)
class _GenerationEntry:
    active: bool = True
    payload: dict[str, Any] | None = None
    status_code: int | None = None


class SolutionGenerationGuard:
    """Durable idempotency authority with a process-local legacy fallback."""

    _operation_type = "solution_generation"

    def __init__(self, database: Any | None = None) -> None:
        self._database = database
        self._lock = Lock()
        self._entries: dict[str, _GenerationEntry] = {}

    @staticmethod
    def key(participant_id: str | None, project_id: str, attempt_id: str) -> str:
        return f"{participant_id or 'default'}:{project_id}:{attempt_id}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if payload is None:
            return None
        if "error_code" in payload:
            allowed = ("error_code", "message", "recovery_actions", "retryable", "preserved_input")
            safe = {key: payload[key] for key in allowed if key in payload}
            # The project record already preserves user input. Do not
            # duplicate business content in the idempotency ledger.
            if "preserved_input" in safe:
                safe["preserved_input"] = None
            return safe
        return payload

    def begin(
        self,
        participant_id: str | None,
        project_id: str,
        attempt_id: str,
        *,
        requested_model_preference: str | None = None,
        resolved_model_family: str | None = None,
        resolved_model_id: str | None = None,
    ) -> GenerationClaim:
        if self._database is None:
            return self._begin_process_local(participant_id, project_id, attempt_id)

        participant = participant_id or "default"
        intent_id = str(uuid4())
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, response_json, status_code, requested_model_preference,
                       resolved_model_family, resolved_model_id
                FROM solution_generation_intents
                WHERE participant_id = ? AND project_id = ?
                  AND operation_type = ? AND idempotency_key = ?
                """,
                (participant, project_id, self._operation_type, attempt_id),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO solution_generation_intents(
                        id, participant_id, project_id, operation_type,
                        idempotency_key, status, quota_reservation_id,
                        requested_model_preference, resolved_model_family,
                        resolved_model_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', ?, ?, ?, ?, ?)
                    """,
                    (
                        intent_id, participant, project_id, self._operation_type, attempt_id,
                        intent_id, requested_model_preference, resolved_model_family,
                        resolved_model_id, self._now(),
                    ),
                )
                return GenerationClaim(owner=True)

            connection.execute(
                """
                UPDATE solution_generation_intents
                SET request_count = request_count + 1, replay_count = replay_count + 1
                WHERE participant_id = ? AND project_id = ?
                  AND operation_type = ? AND idempotency_key = ?
                """,
                (participant, project_id, self._operation_type, attempt_id),
            )
            stored_model_id = row[5]
            if stored_model_id and resolved_model_id and stored_model_id != resolved_model_id:
                return GenerationClaim(
                    owner=False,
                    error_code="IDEMPOTENCY_MODEL_MISMATCH",
                    payload={
                        "error_code": "IDEMPOTENCY_MODEL_MISMATCH",
                        "message": "同一生成操作不能切换模型，请点击重新生成。",
                        "retryable": False,
                    },
                    status_code=409,
                )
            if row[0] == "IN_PROGRESS":
                return GenerationClaim(
                    owner=False,
                    error_code="SOLUTION_GENERATION_IN_PROGRESS",
                    payload={
                        "error_code": "SOLUTION_GENERATION_IN_PROGRESS",
                        "message": "正在生成方案，请稍候。",
                        "retryable": False,
                    },
                    status_code=409,
                )
            return GenerationClaim(
                owner=False,
                error_code="SOLUTION_GENERATION_ALREADY_COMPLETED",
                payload=json.loads(row[1]) if row[1] else None,
                status_code=row[2],
            )

    def _begin_process_local(self, participant_id: str | None, project_id: str, attempt_id: str) -> GenerationClaim:
        key = self.key(participant_id, project_id, attempt_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = _GenerationEntry()
                return GenerationClaim(owner=True)
            if entry.active:
                return GenerationClaim(
                    owner=False,
                    error_code="SOLUTION_GENERATION_IN_PROGRESS",
                    payload={
                        "error_code": "SOLUTION_GENERATION_IN_PROGRESS",
                        "message": "正在生成方案，请稍候。",
                        "retryable": False,
                    },
                    status_code=409,
                )
            return GenerationClaim(
                owner=False,
                error_code="SOLUTION_GENERATION_ALREADY_COMPLETED",
                payload=entry.payload,
                status_code=entry.status_code,
            )

    def mark_provider_call(self, participant_id: str | None, project_id: str, attempt_id: str) -> None:
        if self._database is None:
            return
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE solution_generation_intents SET provider_call_count = provider_call_count + 1
                WHERE participant_id = ? AND project_id = ?
                  AND operation_type = ? AND idempotency_key = ?
                """,
                (participant_id or "default", project_id, self._operation_type, attempt_id),
            )

    def complete(
        self,
        participant_id: str | None,
        project_id: str,
        attempt_id: str,
        payload: dict[str, Any],
        *,
        status_code: int = 201,
    ) -> None:
        safe_payload = self._safe_payload(payload)
        if self._database is None:
            key = self.key(participant_id, project_id, attempt_id)
            with self._lock:
                self._entries[key] = _GenerationEntry(active=False, payload=safe_payload, status_code=status_code)
            return
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE solution_generation_intents
                SET status = ?, response_json = ?, status_code = ?, completed_at = ?
                WHERE participant_id = ? AND project_id = ?
                  AND operation_type = ? AND idempotency_key = ?
                """,
                (
                    "FAILED" if status_code >= 400 else "SUCCEEDED",
                    json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":")),
                    status_code,
                    self._now(),
                    participant_id or "default", project_id, self._operation_type, attempt_id,
                ),
            )

    def fail(self, participant_id: str | None, project_id: str, attempt_id: str) -> None:
        self.complete(
            participant_id,
            project_id,
            attempt_id,
            {
                "error_code": "SOLUTION_GENERATION_FAILED",
                "message": "这次生成未能完成，你的项目内容已经保留，请稍后重试。",
                "recovery_actions": ["重新生成"],
                "retryable": True,
            },
            status_code=503,
        )
