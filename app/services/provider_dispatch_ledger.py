"""Forward-only, acceptance-scoped evidence for Provider dispatch opportunities."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.db import Database


class DispatchClassification(StrEnum):
    PROVEN_NOT_DISPATCHED = "PROVEN_NOT_DISPATCHED"
    CONFIRMED_PROVIDER_DISPATCH = "CONFIRMED_PROVIDER_DISPATCH"
    POSSIBLY_DISPATCHED_INDETERMINATE = "POSSIBLY_DISPATCHED_INDETERMINATE"
    NOT_YET_ATTEMPTED = "NOT_YET_ATTEMPTED"


_BOUNDARY = {"CALL_BOUNDARY_ENTERED"}
_CONFIRMING = {"PROVIDER_RESPONSE_RECEIVED", "PROVIDER_HTTP_ERROR_RECEIVED"}
_AMBIGUOUS = {"TRANSPORT_ERROR_AFTER_BOUNDARY", "TIMEOUT_AFTER_BOUNDARY", "CANCELLED_AFTER_BOUNDARY"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProviderDispatchLedger:
    def __init__(self, database: Database):
        self.database = database

    def create_epoch(self, *, epoch_id: str, acceptance_window_id: str,
                     checkpoint_at: str, historical_authorized_dispatches: int,
                     historical_unresolved_intents: int) -> None:
        with self.database.connect() as cx:
            cx.execute(
                """INSERT OR IGNORE INTO provider_dispatch_epochs
                (epoch_id, acceptance_window_id, checkpoint_at,
                 historical_authorized_dispatches, historical_unresolved_intents, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (epoch_id, acceptance_window_id, checkpoint_at,
                 historical_authorized_dispatches, historical_unresolved_intents, _now()),
            )

    def acquire_permit(self, *, acceptance_execution_id: str, acceptance_window_id: str,
                       beta_instance: str, provider: str, model: str,
                       authorization_reference: str, quota_scope: str,
                       evaluation_id: str | None = None) -> str | None:
        permit_id = str(uuid.uuid4())
        try:
            with self.database.connect() as cx:
                cx.execute("BEGIN IMMEDIATE")
                cx.execute(
                    """INSERT INTO provider_dispatch_permits
                    (permit_id, acceptance_execution_id, evaluation_id, acceptance_window_id, beta_instance,
                     provider, model, dispatch_ordinal, authorization_reference, quota_scope, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                    (permit_id, acceptance_execution_id, evaluation_id, acceptance_window_id, beta_instance,
                     provider, model, authorization_reference, quota_scope, _now()),
                )
                self._insert_event(cx, permit_id, "PERMIT_ACQUIRED")
            return permit_id
        except sqlite3.IntegrityError:
            return None

    def link_permit_to_evaluation(self, permit_id: str, evaluation_id: str) -> None:
        """Attach one pre-created permit to its explicit Stage B evaluation."""
        with self.database.connect() as cx:
            row = cx.execute(
                "SELECT evaluation_id FROM provider_dispatch_permits WHERE permit_id=?",
                (permit_id,),
            ).fetchone()
            if row is None:
                raise KeyError(permit_id)
            if row[0] not in (None, evaluation_id):
                raise ValueError("DISPATCH_EVALUATION_MISMATCH")
            cx.execute(
                "UPDATE provider_dispatch_permits SET evaluation_id=? WHERE permit_id=?",
                (evaluation_id, permit_id),
            )

    def record_event(self, permit_id: str, event_type: str, metadata: dict[str, Any] | None = None) -> str:
        safe = metadata or {}
        if any(k.lower() in {"prompt", "completion", "api_key", "authorization", "secret"} for k in safe):
            raise ValueError("unsafe metadata key")
        with self.database.connect() as cx:
            return self._insert_event(cx, permit_id, event_type, safe)

    def permit_matches(self, permit_id: str, context: Any) -> bool:
        """Validate an existing permit without creating or changing ledger state."""
        with self.database.connect() as cx:
            row = cx.execute(
                """SELECT acceptance_execution_id, acceptance_window_id, beta_instance,
                   provider, model, dispatch_ordinal FROM provider_dispatch_permits
                   WHERE permit_id=?""", (permit_id,)
            ).fetchone()
        return bool(row and (row[0], row[1], row[2], row[3], row[4], row[5]) == (
            context.acceptance_execution_id, context.window_id, context.beta_instance,
            context.expected_provider, context.expected_model, context.dispatch_ordinal,
        ))

    def permit_for_execution(self, acceptance_execution_id: str) -> str | None:
        with self.database.connect() as cx:
            row = cx.execute(
                "SELECT permit_id FROM provider_dispatch_permits WHERE acceptance_execution_id=?",
                (acceptance_execution_id,),
            ).fetchone()
        return row[0] if row else None

    @staticmethod
    def _insert_event(cx: sqlite3.Connection, permit_id: str, event_type: str,
                      metadata: dict[str, Any] | None = None) -> str:
        event_id = str(uuid.uuid4())
        cx.execute(
            "INSERT INTO provider_dispatch_events(event_id, permit_id, event_type, observed_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
            (event_id, permit_id, event_type, _now(), json.dumps(metadata or {}, sort_keys=True)),
        )
        return event_id

    def classify(self, acceptance_execution_id: str) -> DispatchClassification:
        with self.database.connect() as cx:
            permit = cx.execute(
                "SELECT permit_id FROM provider_dispatch_permits WHERE acceptance_execution_id=?",
                (acceptance_execution_id,),
            ).fetchone()
            if permit is None:
                return DispatchClassification.NOT_YET_ATTEMPTED
            events = {row[0] for row in cx.execute(
                "SELECT event_type FROM provider_dispatch_events WHERE permit_id=?", (permit[0],)
            )}
        if events & _CONFIRMING:
            return DispatchClassification.CONFIRMED_PROVIDER_DISPATCH
        if events & _BOUNDARY or events & _AMBIGUOUS:
            return DispatchClassification.POSSIBLY_DISPATCHED_INDETERMINATE
        return DispatchClassification.PROVEN_NOT_DISPATCHED

    def scoped_guard(self, *, acceptance_execution_id: str, provider: str, model: str,
                     beta_instance: str, current_day_used: int, daily_limit: int,
                     active_reservations: int, dispatches_after_checkpoint: int = 0,
                     automatic_retry_enabled: bool = False,
                     fallback_provider: str | None = None) -> tuple[bool, str]:
        if (provider, model) != ("bailian", "qwen3.7-flash"):
            return False, "TARGET_MISMATCH"
        if beta_instance != "beta001":
            return False, "BETA_INSTANCE_MISMATCH"
        if automatic_retry_enabled or fallback_provider is not None:
            return False, "RETRY_OR_FALLBACK_ENABLED"
        if current_day_used < 0 or current_day_used >= daily_limit or active_reservations != 0:
            return False, "QUOTA_OR_RESERVATION_BLOCKED"
        if dispatches_after_checkpoint != 0:
            return False, "POST_CHECKPOINT_DISPATCH_PRESENT"
        if self.classify(acceptance_execution_id) is not DispatchClassification.NOT_YET_ATTEMPTED:
            return False, "EXECUTION_ALREADY_HAS_PERMIT_OR_EVIDENCE"
        return True, "SCOPED_GUARD_PASS"
