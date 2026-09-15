"""Rule-first, provider-free Prototype Task projection for IF Guide R1.1 M2."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import utc_now
from app.errors import ConflictError
from app.services.build_slice import BuildSliceService


_JSON_COLUMNS = {
    "scope": "scope_json",
    "inputs": "inputs_json",
    "outputs": "outputs_json",
    "existing_behaviors_to_preserve": "existing_behaviors_json",
    "explicit_non_goals": "non_goals_json",
    "known_technical_context": "known_context_json",
    "unknown_dependencies": "unknown_dependencies_json",
    "implementation_tasks": "implementation_tasks_json",
    "acceptance_steps": "acceptance_steps_json",
    "failure_recovery_notes": "failure_recovery_json",
    "required_return_evidence": "required_evidence_json",
    "permission_risk_notes": "permission_risk_json",
}


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> Any:
    return json.loads(value)


class PrototypeTaskService:
    """Persist the inspectable implementation description without execution."""

    def __init__(self, db):
        self.db = db
        self.build_slices = BuildSliceService(db)

    def _project(self, connection: sqlite3.Connection, project_id: str) -> Any:
        row = connection.execute(
            "SELECT id, status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError("project not found")
        if row["status"] != "active":
            raise ValueError("project is not active")
        return row

    def _row(self, connection: sqlite3.Connection, task_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM prototype_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise KeyError("prototype task not found")
        return row

    def _latest(self, connection: sqlite3.Connection, project_id: str) -> Any:
        return connection.execute(
            """SELECT * FROM prototype_tasks
               WHERE project_id = ? ORDER BY revision DESC, updated_at DESC, task_id DESC LIMIT 1""",
            (project_id,),
        ).fetchone()

    def _public(self, row: Any) -> dict[str, Any]:
        payload = {
            "task_id": row["task_id"],
            "project_id": row["project_id"],
            "owner_actor": row["owner_actor"],
            "slice_id": row["slice_id"],
            "slice_revision": row["slice_revision"],
            "snapshot_id": row["snapshot_id"],
            "snapshot_version": row["snapshot_version"],
            "purpose": row["purpose"],
            "revision": row["revision"],
            "status": row["status"],
            "confirmed_at": row["confirmed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for field, column in _JSON_COLUMNS.items():
            payload[field] = _decode(row[column])
        return payload

    def _assert_slice(self, project_id: str, slice_id: str, actor: str, expected_revision: int) -> dict[str, Any]:
        current = self.build_slices.get_current(project_id, actor=actor)
        if current is None or current["slice_id"] != slice_id:
            raise ConflictError("BUILD_SLICE_NOT_FOUND")
        if int(current["revision"]) != int(expected_revision):
            raise ConflictError("BUILD_SLICE_REVISION_CONFLICT")
        if current["status"] != "CONFIRMED":
            raise ConflictError("BUILD_SLICE_NOT_CONFIRMED")
        p0 = self.build_slices.evaluate_p0(project_id, slice_id, actor=actor)
        if p0["status"] != "PASS":
            raise ConflictError(p0["codes"][0])
        return current

    def get_current(self, project_id: str, *, actor: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            row = self._latest(connection, project_id)
            if row is None:
                return None
            if row["owner_actor"] != actor:
                raise PermissionError("prototype task belongs to another actor")
            return self._public(row)

    def generate_rule_first(
        self,
        project_id: str,
        *,
        actor: str,
        slice_id: str,
        expected_slice_revision: int,
    ) -> dict[str, Any]:
        build_slice = self._assert_slice(project_id, slice_id, actor, expected_slice_revision)
        with self.db.connect() as connection:
            existing = connection.execute(
                """SELECT * FROM prototype_tasks
                   WHERE project_id=? AND slice_id=? AND slice_revision=?""",
                (project_id, slice_id, expected_slice_revision),
            ).fetchone()
            if existing is not None:
                if existing["owner_actor"] != actor:
                    raise PermissionError("prototype task belongs to another actor")
                return self._public(existing)

            now = utc_now()
            task_id = f"prototype_task_{uuid.uuid4().hex}"
            payload = {
                "scope": build_slice["in_scope"],
                "inputs": build_slice["inputs"],
                "outputs": build_slice["expected_outputs"],
                "existing_behaviors_to_preserve": [
                    "现有项目目的与已确认的首个行动不因本轮原型任务而改变。",
                ],
                "explicit_non_goals": build_slice["out_of_scope"],
                "known_technical_context": [
                    "CONFIRMED: 任务来源于当前项目已确认的 Build Slice。",
                    "CONFIRMED: 本任务只描述实现，不声明实现、测试或部署已经发生。",
                ],
                # Keep this as an explicit unknown-dependency collection.  Do
                # not promote the source text into a verified technical fact.
                "unknown_dependencies": build_slice["unknowns"],
                "implementation_tasks": build_slice["minimal_flow"],
                "acceptance_steps": build_slice["acceptance_criteria"],
                "failure_recovery_notes": build_slice["error_handling"],
                "required_return_evidence": build_slice["expected_outputs"],
                "permission_risk_notes": build_slice["confirmed_constraints"]
                + ["M2 不执行外部动作、代码写入、部署或正式 Handoff 导出。"],
            }
            connection.execute(
                """INSERT INTO prototype_tasks(
                    task_id, project_id, owner_actor, slice_id, slice_revision,
                    snapshot_id, snapshot_version, purpose,
                    scope_json, inputs_json, outputs_json, existing_behaviors_json,
                    non_goals_json, known_context_json, unknown_dependencies_json,
                    implementation_tasks_json, acceptance_steps_json, failure_recovery_json,
                    required_evidence_json, permission_risk_json,
                    revision, status, confirmed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'DRAFT', NULL, ?, ?)""",
                (
                    task_id, project_id, actor, slice_id, expected_slice_revision,
                    build_slice["snapshot_id"], build_slice["snapshot_version"], build_slice["purpose"],
                    *(_encode(payload[field]) for field in (
                        "scope", "inputs", "outputs", "existing_behaviors_to_preserve",
                        "explicit_non_goals", "known_technical_context", "unknown_dependencies",
                        "implementation_tasks", "acceptance_steps", "failure_recovery_notes",
                        "required_return_evidence", "permission_risk_notes",
                    )),
                    now, now,
                ),
            )
            return self._public(self._row(connection, task_id))
