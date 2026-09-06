from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import Database, utc_now
from app.errors import DraftConflictError


class UnifiedDraftService:
    """Small project-scoped working-copy store with optimistic concurrency."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _validate_scope(scope_type: str, scope_key: str) -> None:
        if not scope_type or len(scope_type) > 80 or not scope_type.replace("_", "").isalnum():
            raise ValueError("invalid draft scope")
        if not scope_key or len(scope_key) > 200 or "/" in scope_key:
            raise ValueError("invalid draft scope key")

    def _project(self, project_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise KeyError("project not found")
        return row

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "scope_type": row["scope_type"],
            "scope_key": row["scope_key"],
            "entity_id": row.get("entity_id"),
            "version_id": row.get("version_id"),
            "revision": int(row["revision"]),
            "payload": json.loads(row["payload_json"]),
            "updated_at": row["updated_at"],
        }

    def get(self, project_id: str, scope_type: str, scope_key: str) -> dict[str, Any]:
        self._project(project_id)
        self._validate_scope(scope_type, scope_key)
        row = self.db.fetch_one(
            "SELECT * FROM unified_drafts WHERE project_id=? AND scope_type=? AND scope_key=?",
            (project_id, scope_type, scope_key),
        )
        if row is None:
            raise KeyError("draft not found")
        return self._public(row)

    def save(
        self,
        project_id: str,
        scope_type: str,
        scope_key: str,
        *,
        payload: dict[str, Any],
        base_revision: int | None,
        entity_id: str | None,
        version_id: str | None,
        actor: str,
    ) -> dict[str, Any]:
        self._project(project_id)
        self._validate_scope(scope_type, scope_key)
        current = self.db.fetch_one(
            "SELECT * FROM unified_drafts WHERE project_id=? AND scope_type=? AND scope_key=?",
            (project_id, scope_type, scope_key),
        )
        if current is not None:
            current_revision = int(current["revision"])
            if base_revision is not None and base_revision != current_revision:
                raise DraftConflictError(self._public(current))
            revision = current_revision + 1
            draft_id = current["id"]
        else:
            if base_revision not in (None, 0):
                raise DraftConflictError({})
            revision = 1
            draft_id = f"draft_{uuid.uuid4().hex}"
        now = utc_now()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if current is None:
            self.db.execute(
                """INSERT INTO unified_drafts(
                    id,project_id,scope_type,scope_key,entity_id,version_id,revision,
                    payload_json,updated_by,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (draft_id, project_id, scope_type, scope_key, entity_id, version_id, revision,
                 encoded, actor.strip() or "web_user", now),
            )
        else:
            changed = self.db.execute(
                """UPDATE unified_drafts SET entity_id=?,version_id=?,revision=?,
                    payload_json=?,updated_by=?,updated_at=?
                   WHERE id=? AND revision=?""",
                (entity_id, version_id, revision, encoded, actor.strip() or "web_user", now,
                 draft_id, current_revision),
            )
            if changed != 1:
                raise DraftConflictError(self.get(project_id, scope_type, scope_key))
        return self.get(project_id, scope_type, scope_key)
