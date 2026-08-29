from __future__ import annotations

import sqlite3
from typing import Any

from app.db import Database, utc_now

HEALTH_VALUES = {"current", "needs_review", "stale_evidence", "superseded"}


class ArtifactHealthService:
    def __init__(self, db: Database):
        self.db = db

    def set_tx(
        self,
        connection: sqlite3.Connection,
        *,
        artifact_type: str,
        artifact_id: str,
        health_status: str,
        reason: str,
        trigger_source_id: str | None = None,
    ) -> dict[str, Any]:
        if health_status not in HEALTH_VALUES:
            raise ValueError(f"invalid artifact health: {health_status}")
        now = utc_now()
        connection.execute(
            """
            INSERT INTO artifact_health(
                artifact_type, artifact_id, health_status, reason, trigger_source_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(artifact_type, artifact_id) DO UPDATE SET
                health_status=excluded.health_status,
                reason=excluded.reason,
                trigger_source_id=excluded.trigger_source_id,
                updated_at=excluded.updated_at
            """,
            (artifact_type, artifact_id, health_status, reason, trigger_source_id, now),
        )
        row = connection.execute(
            "SELECT * FROM artifact_health WHERE artifact_type=? AND artifact_id=?",
            (artifact_type, artifact_id),
        ).fetchone()
        return dict(row)

    def set(self, **kwargs: Any) -> dict[str, Any]:
        with self.db.connect() as connection:
            return self.set_tx(connection, **kwargs)

    def get(self, artifact_type: str, artifact_id: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type=? AND artifact_id=?",
            (artifact_type, artifact_id),
        )
        if row is None:
            raise KeyError("artifact health not found")
        return row

    def recompute(self, artifact_type: str, artifact_id: str) -> dict[str, Any]:
        # P0 health is event-driven. Recompute is intentionally conservative and only
        # returns the persisted health rather than inferring from artifact content.
        return self.get(artifact_type, artifact_id)
