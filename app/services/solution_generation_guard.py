from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any


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
    """Process-local idempotency guard for one logical solution attempt."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[str, _GenerationEntry] = {}

    @staticmethod
    def key(participant_id: str | None, project_id: str, attempt_id: str) -> str:
        return f"{participant_id or 'default'}:{project_id}:{attempt_id}"

    def begin(self, participant_id: str | None, project_id: str, attempt_id: str) -> GenerationClaim:
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

    def complete(
        self,
        participant_id: str | None,
        project_id: str,
        attempt_id: str,
        payload: dict[str, Any],
        *,
        status_code: int = 201,
    ) -> None:
        key = self.key(participant_id, project_id, attempt_id)
        with self._lock:
            self._entries[key] = _GenerationEntry(
                active=False, payload=payload, status_code=status_code
            )

    def fail(self, participant_id: str | None, project_id: str, attempt_id: str) -> None:
        key = self.key(participant_id, project_id, attempt_id)
        with self._lock:
            self._entries.pop(key, None)
