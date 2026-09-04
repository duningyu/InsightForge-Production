"""Durable, pollable solution-generation jobs.

The worker deliberately uses the existing domain service boundary.  HTTP
requests never wait on provider I/O; SQLite owns identity and terminal replay.
"""

from __future__ import annotations

import json
import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from app.db import Database
from app.services.dispatch_control import DispatchControlContext


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class AsyncRun:
    generation_run_id: str
    generation_intent_id: str
    participant_id: str
    project_id: str
    status: str
    response: dict[str, Any] | None
    status_code: int | None
    requested_model_preference: str | None
    resolved_model_family: str | None
    resolved_model_id: str | None
    request_count: int
    replay_count: int
    provider_call_count: int
    dispatch_control: DispatchControlContext | None = None

    def public(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "generation_run_id": self.generation_run_id,
            "generation_intent_id": self.generation_intent_id,
            "status": self.status,
            "poll_after_ms": 2000,
            "request_count": self.request_count,
            "replay_count": self.replay_count,
            "provider_call_count": self.provider_call_count,
        }
        if self.requested_model_preference:
            payload["requested_model_preference"] = self.requested_model_preference
        if self.resolved_model_family:
            payload["resolved_model_family"] = self.resolved_model_family
        if self.resolved_model_id:
            payload["resolved_model_id"] = self.resolved_model_id
        if self.status in {"SUCCEEDED", "FAILED"}:
            payload["status_code"] = self.status_code
            if self.response is not None:
                payload.update(self.response)
        return payload


class AsyncGenerationRepository:
    def __init__(self, database: Database):
        self.db = database

    @staticmethod
    def _row(row: Any) -> AsyncRun:
        return AsyncRun(
            generation_run_id=row["generation_run_id"],
            generation_intent_id=row["generation_intent_id"],
            participant_id=row["participant_id"], project_id=row["project_id"],
            status=row["status"],
            response=json.loads(row["response_json"]) if row["response_json"] else None,
            status_code=row["status_code"],
            requested_model_preference=row["requested_model_preference"],
            resolved_model_family=row["resolved_model_family"],
            resolved_model_id=row["resolved_model_id"],
            request_count=row["request_count"], replay_count=row["replay_count"],
            provider_call_count=row["provider_call_count"],
            dispatch_control=(DispatchControlContext(
                acceptance_execution_id=row["acceptance_execution_id"],
                forward_ledger_epoch_id=row["forward_ledger_epoch_id"],
                beta_instance=row["dispatch_beta_instance"],
                expected_provider=row["dispatch_expected_provider"],
                expected_model=row["dispatch_expected_model"],
                dispatch_ordinal=row["dispatch_ordinal"] or 1,
                strict_at_most_once=bool(row["strict_at_most_once"]),
            ) if row["acceptance_execution_id"] else None),
        )

    def create_or_replay(
        self, participant_id: str, project_id: str, idempotency_key: str,
        *, requested_model_preference: str | None = None,
        resolved_model_family: str | None = None, resolved_model_id: str | None = None,
        dispatch_control: DispatchControlContext | None = None,
    ) -> AsyncRun:
        participant = participant_id or "default"
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM async_solution_generation_runs WHERE participant_id=? AND project_id=? AND operation_type=? AND idempotency_key=?",
                (participant, project_id, "solution_generation", idempotency_key),
            ).fetchone()
            if row is None:
                run_id, intent_id = str(uuid4()), str(uuid4())
                connection.execute(
                    """INSERT INTO solution_generation_intents(
                        id,participant_id,project_id,operation_type,idempotency_key,status,
                        quota_reservation_id,request_count,replay_count,provider_call_count,
                        requested_model_preference,resolved_model_family,resolved_model_id,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (intent_id, participant, project_id, "solution_generation", idempotency_key,
                     "IN_PROGRESS", intent_id, 1, 0, 0, requested_model_preference,
                     resolved_model_family, resolved_model_id, _now()),
                )
                connection.execute(
                    """INSERT INTO async_solution_generation_runs(
                        generation_run_id,generation_intent_id,participant_id,project_id,
                        operation_type,idempotency_key,status,requested_model_preference,
                        resolved_model_family,resolved_model_id,quota_reservation_id,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, intent_id, participant, project_id, "solution_generation",
                     idempotency_key, "PENDING", requested_model_preference,
                     resolved_model_family, resolved_model_id, intent_id, _now()),
                )
                if dispatch_control is not None:
                    connection.execute(
                        """UPDATE async_solution_generation_runs SET
                        acceptance_execution_id=?, forward_ledger_epoch_id=?, dispatch_beta_instance=?,
                        dispatch_expected_provider=?, dispatch_expected_model=?, dispatch_ordinal=?, strict_at_most_once=?
                        WHERE generation_run_id=?""",
                        (dispatch_control.acceptance_execution_id, dispatch_control.forward_ledger_epoch_id,
                         dispatch_control.beta_instance, dispatch_control.expected_provider,
                         dispatch_control.expected_model, dispatch_control.dispatch_ordinal,
                         int(dispatch_control.strict_at_most_once), run_id),
                    )
                connection.execute(
                    "UPDATE solution_generation_intents SET generation_run_id=? WHERE id=?",
                    (run_id, intent_id),
                )
                row = connection.execute(
                    "SELECT * FROM async_solution_generation_runs WHERE generation_run_id=?", (run_id,)
                ).fetchone()
            else:
                existing_context = self._row(row).dispatch_control
                if dispatch_control is not None and existing_context != dispatch_control:
                    raise ValueError("IDEMPOTENCY_DISPATCH_CONTROL_MISMATCH")
                if row["resolved_model_id"] and resolved_model_id and row["resolved_model_id"] != resolved_model_id:
                    raise ValueError("IDEMPOTENCY_MODEL_MISMATCH")
                connection.execute(
                    "UPDATE async_solution_generation_runs SET request_count=request_count+1,replay_count=replay_count+1 WHERE generation_run_id=?",
                    (row["generation_run_id"],),
                )
                connection.execute(
                    "UPDATE solution_generation_intents SET request_count=request_count+1,replay_count=replay_count+1 WHERE id=?",
                    (row["generation_intent_id"],),
                )
                row = connection.execute(
                    "SELECT * FROM async_solution_generation_runs WHERE generation_run_id=?", (row["generation_run_id"],)
                ).fetchone()
            return self._row(row)

    def get(self, participant_id: str, project_id: str, run_id: str) -> AsyncRun | None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM async_solution_generation_runs WHERE generation_run_id=? AND participant_id=? AND project_id=?",
                (run_id, participant_id or "default", project_id),
            ).fetchone()
        return self._row(row) if row else None

    def claim_next(self) -> AsyncRun | None:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT generation_run_id FROM async_solution_generation_runs WHERE status='PENDING' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            changed = connection.execute(
                "UPDATE async_solution_generation_runs SET status='RUNNING',started_at=?,worker_heartbeat_at=? WHERE generation_run_id=? AND status='PENDING'",
                (_now(), _now(), row["generation_run_id"]),
            ).rowcount
            if not changed:
                return None
            claimed = connection.execute(
                "SELECT * FROM async_solution_generation_runs WHERE generation_run_id=?", (row["generation_run_id"],)
            ).fetchone()
        return self._row(claimed)

    def mark_provider_call(self, run_id: str) -> None:
        with self.db.connect() as connection:
            connection.execute("UPDATE async_solution_generation_runs SET provider_call_count=1,worker_heartbeat_at=? WHERE generation_run_id=? AND status='RUNNING'", (_now(), run_id))
            connection.execute("UPDATE solution_generation_intents SET provider_call_count=1 WHERE generation_run_id=?", (run_id,))

    def finish(self, run_id: str, payload: dict[str, Any], *, status_code: int, solution_run_id: str | None = None) -> None:
        safe = {k: v for k, v in payload.items() if k not in {"preserved_input"}}
        status = "SUCCEEDED" if status_code < 400 else "FAILED"
        quota_status = "CHARGED" if status == "SUCCEEDED" else "RELEASED"
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE async_solution_generation_runs SET status=?,response_json=?,status_code=?,solution_run_id=?,quota_status=?,completed_at=?,worker_heartbeat_at=? WHERE generation_run_id=? AND status='RUNNING'",
                (status, json.dumps(safe, ensure_ascii=False, separators=(",", ":")), status_code, solution_run_id, quota_status, _now(), _now(), run_id),
            )
            connection.execute(
                """UPDATE solution_generation_intents SET status=?,response_json=?,status_code=?,
                    solution_run_id=?,completed_at=? WHERE generation_run_id=?""",
                (status, json.dumps(safe, ensure_ascii=False, separators=(",", ":")), status_code,
                 solution_run_id, _now(), run_id),
            )


class AsyncGenerationWorker:
    def __init__(self, repository: AsyncGenerationRepository, executor: Callable[[AsyncRun], dict[str, Any]] | None = None, *, async_executor: Callable[[AsyncRun], Any] | None = None, poll_seconds: float = 0.05):
        self.repository, self.executor, self.async_executor, self.poll_seconds = repository, executor, async_executor, poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_loop: asyncio.AbstractEventLoop | None = None
        self._active_task: asyncio.Task[Any] | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="insightforge-async-generation", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            run = self.repository.claim_next()
            if run is None:
                self._stop.wait(self.poll_seconds)
                continue
            asyncio.run(self._execute_run(run))

    async def _execute_run(self, run: AsyncRun) -> None:
        self._active_loop = asyncio.get_running_loop()
        self._active_task = asyncio.current_task()
        self.repository.mark_provider_call(run.generation_run_id)
        try:
            if self.async_executor is not None:
                payload = await self.async_executor(run)
            elif self.executor is not None:
                # Compatibility for existing synchronous unit-test executors;
                # production startup uses async_executor exclusively.
                payload = self.executor(run)
            else:
                raise RuntimeError("async generation executor is not configured")
            solution_run_id = payload.pop("_solution_run_id", None)
            status_code = 503 if payload.get("error_code") or not (payload.get("candidates") or []) else 201
            self.repository.finish(run.generation_run_id, payload, status_code=status_code, solution_run_id=solution_run_id)
        except asyncio.CancelledError:
            self.repository.finish(run.generation_run_id, {
                "error_code": "ASYNC_GENERATION_CANCELLED",
                "message": "生成已停止，你的项目内容已经保留，请重新生成。",
                "recovery_actions": ["重新生成"], "retryable": True,
            }, status_code=503)
        except Exception:
            self.repository.finish(run.generation_run_id, {
                "error_code": "ASYNC_GENERATION_FAILED",
                "message": "这次生成未能完成，你的项目内容已经保留，请稍后重试。",
                "recovery_actions": ["重新生成"], "retryable": True,
            }, status_code=503)
        finally:
            self._active_task = None
            self._active_loop = None

    def stop(self) -> None:
        self._stop.set()
        if self._active_loop and self._active_task:
            self._active_loop.call_soon_threadsafe(self._active_task.cancel)
        if self._thread:
            self._thread.join(timeout=2)
