"""Provider-free Build Slice lifecycle for IF Guide R1.1 M2."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import utc_now
from app.errors import ConflictError
from app.services.project_intent import TEMPLATE_VERSION


_JSON_FIELDS = {
    "confirmed_constraints",
    "in_scope",
    "out_of_scope",
    "minimal_flow",
    "acceptance_criteria",
    "inputs",
    "expected_outputs",
    "error_handling",
    "unknowns",
    "constraint_notes",
}


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> Any:
    return json.loads(value)


class BuildSliceService:
    """Persist a revisioned, project-owned minimum usable flow."""

    def __init__(self, db):
        self.db = db

    def _project(self, connection: sqlite3.Connection, project_id: str) -> Any:
        row = connection.execute(
            "SELECT id, status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError("project not found")
        if row["status"] != "active":
            raise ValueError("project is not active")
        return row

    def _context(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        *,
        actor: str,
        expected_snapshot_id: str | None,
        expected_intent_revision: int,
    ) -> tuple[Any, Any, Any]:
        self._project(connection, project_id)
        intent = connection.execute(
            """SELECT * FROM project_intents
               WHERE project_id = ? ORDER BY revision DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        if intent is None:
            raise ConflictError("INTENT_REQUIRED")
        if intent["owner_actor"] != actor:
            raise PermissionError("project intent belongs to another actor")
        if int(intent["revision"]) != int(expected_intent_revision):
            raise ConflictError("INTENT_REVISION_CONFLICT")
        action = connection.execute(
            """SELECT * FROM first_action_cards
               WHERE project_id = ? AND intent_revision = ? AND template_version = ?""",
            (project_id, expected_intent_revision, TEMPLATE_VERSION),
        ).fetchone()
        if action is None or not bool(action["confirmed"]):
            raise ConflictError("M1_ACTION_NOT_CONFIRMED")

        project = connection.execute(
            "SELECT current_snapshot_id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        current_snapshot_id = project["current_snapshot_id"]
        if expected_snapshot_id != current_snapshot_id:
            raise ConflictError("BUILD_SLICE_BINDING_CONFLICT")
        snapshot = None
        if current_snapshot_id is not None:
            snapshot = connection.execute(
                "SELECT id, version FROM project_snapshots WHERE id = ? AND project_id = ?",
                (current_snapshot_id, project_id),
            ).fetchone()
            if snapshot is None:
                raise ConflictError("BUILD_SLICE_BINDING_CONFLICT")
        return intent, action, snapshot

    def _row(self, connection: sqlite3.Connection, slice_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM build_slices WHERE slice_id = ?", (slice_id,)
        ).fetchone()
        if row is None:
            raise KeyError("build slice not found")
        return row

    def _latest(self, connection: sqlite3.Connection, project_id: str) -> Any:
        return connection.execute(
            """SELECT * FROM build_slices
               WHERE project_id = ? ORDER BY revision DESC, updated_at DESC, slice_id DESC LIMIT 1""",
            (project_id,),
        ).fetchone()

    def _public(self, row: Any) -> dict[str, Any]:
        payload = {"slice_id": row["slice_id"], "project_id": row["project_id"]}
        for key in (
            "owner_actor", "intent_revision", "first_action_task_id", "first_action_revision",
            "snapshot_id", "snapshot_version", "purpose", "revision", "status",
            "confirmed_at", "created_at", "updated_at",
        ):
            payload[key] = row[key]
        for field in _JSON_FIELDS:
            payload[field] = _decode(row[f"{field}_json"] if field != "confirmed_constraints" else row[field])
        return payload

    def _assert_existing_binding(
        self, row: Any, *, actor: str, expected_snapshot_id: str | None, expected_intent_revision: int
    ) -> None:
        if row["owner_actor"] != actor:
            raise PermissionError("build slice belongs to another actor")
        if (
            int(row["intent_revision"]) != int(expected_intent_revision)
            or row["snapshot_id"] != expected_snapshot_id
        ):
            raise ConflictError("BUILD_SLICE_BINDING_CONFLICT")

    def create_or_get(
        self,
        project_id: str,
        *,
        actor: str,
        expected_snapshot_id: str | None,
        expected_intent_revision: int,
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            intent, action, snapshot = self._context(
                connection,
                project_id,
                actor=actor,
                expected_snapshot_id=expected_snapshot_id,
                expected_intent_revision=expected_intent_revision,
            )
            existing = self._latest(connection, project_id)
            if existing is not None:
                self._assert_existing_binding(
                    existing,
                    actor=actor,
                    expected_snapshot_id=expected_snapshot_id,
                    expected_intent_revision=expected_intent_revision,
                )
                return self._public(existing)
            now = utc_now()
            slice_id = f"build_slice_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO build_slices(
                    slice_id, project_id, owner_actor, intent_revision,
                    first_action_task_id, first_action_revision, snapshot_id, snapshot_version,
                    purpose, confirmed_constraints, revision, status, confirmed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'DRAFT', NULL, ?, ?)""",
                (
                    slice_id, project_id, actor, intent["revision"], action["task_id"],
                    action["card_revision"], snapshot["id"] if snapshot else None,
                    snapshot["version"] if snapshot else None, intent["purpose"],
                    action["prohibited_actions_json"], now, now,
                ),
            )
            return self._public(self._row(connection, slice_id))

    def get_current(self, project_id: str, *, actor: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            row = self._latest(connection, project_id)
            if row is None:
                return None
            if row["owner_actor"] != actor:
                raise PermissionError("build slice belongs to another actor")
            return self._public(row)

    def update(
        self,
        project_id: str,
        slice_id: str,
        *,
        actor: str,
        expected_revision: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        unknown = set(updates) - _JSON_FIELDS
        if unknown:
            raise ValueError(f"unsupported build slice fields: {sorted(unknown)}")
        with self.db.connect() as connection:
            row = self._row(connection, slice_id)
            if row["project_id"] != project_id:
                raise PermissionError("build slice belongs to another project")
            if row["owner_actor"] != actor:
                raise PermissionError("build slice belongs to another actor")
            if int(row["revision"]) != int(expected_revision):
                raise ConflictError("BUILD_SLICE_REVISION_CONFLICT")
            intent, action, snapshot = self._context(
                connection,
                project_id,
                actor=actor,
                expected_snapshot_id=row["snapshot_id"],
                expected_intent_revision=row["intent_revision"],
            )
            if snapshot is not None and row["snapshot_version"] != snapshot["version"]:
                raise ConflictError("BUILD_SLICE_BINDING_CONFLICT")
            values = {field: row[field if field == "confirmed_constraints" else f"{field}_json"] for field in _JSON_FIELDS}
            for field, value in updates.items():
                if not isinstance(value, list):
                    raise ValueError(f"{field} must be a list")
                values[field] = _encode(value)
            now = utc_now()
            connection.execute(
                """UPDATE build_slices SET
                    confirmed_constraints=?, in_scope_json=?, out_of_scope_json=?, minimal_flow_json=?,
                    acceptance_criteria_json=?, inputs_json=?, expected_outputs_json=?, error_handling_json=?,
                    unknowns_json=?, constraint_notes_json=?, revision=?, status='DRAFT',
                    confirmed_at=NULL, updated_at=?
                   WHERE slice_id=? AND project_id=?""",
                (
                    values["confirmed_constraints"], values["in_scope"], values["out_of_scope"],
                    values["minimal_flow"], values["acceptance_criteria"], values["inputs"],
                    values["expected_outputs"], values["error_handling"], values["unknowns"],
                    values["constraint_notes"], int(expected_revision) + 1, now, slice_id, project_id,
                ),
            )
            return self._public(self._row(connection, slice_id))
