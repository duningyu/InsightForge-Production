"""Provider-free recovery actions for IF Guide R1.1 M3.

Recovery reuses the existing ``first_action_cards`` storage.  A recovery is a
new, revisioned action card linked to the exact failed submission and review;
it never replaces the original first action and it never performs external
work on the owner's behalf.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import utc_now
from app.errors import ConflictError


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> Any:
    return json.loads(value)


class RecoveryService:
    """Create and revise one minimal recovery action for a failed review."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _project(connection: sqlite3.Connection, project_id: str) -> None:
        row = connection.execute(
            "SELECT status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError("project not found")
        if row["status"] != "active":
            raise ValueError("project is not active")

    @staticmethod
    def _owner(connection: sqlite3.Connection, project_id: str) -> str:
        row = connection.execute(
            """SELECT owner_actor FROM project_intents
               WHERE project_id = ? ORDER BY revision DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        if row is None:
            raise ConflictError("INTENT_REQUIRED")
        return str(row["owner_actor"])

    @staticmethod
    def _validate_content(
        goal: str, inputs: list[Any], steps: list[Any], checks: list[Any]
    ) -> None:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("RECOVERY_GOAL_REQUIRED")
        if not isinstance(inputs, list) or not isinstance(steps, list) or not isinstance(checks, list):
            raise ValueError("RECOVERY_COLLECTIONS_REQUIRED")
        if not steps or not checks:
            raise ValueError("RECOVERY_ACTION_AND_CHECK_REQUIRED")

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "project_id": row["project_id"],
            "kind": row["kind"],
            "parent_task_id": row["parent_task_id"],
            "source_submission_id": row["source_submission_id"],
            "source_review_id": row["source_review_id"],
            "intent_revision": int(row["intent_revision"]),
            "template_version": row["template_version"],
            "status": row["status"],
            "goal": row["goal"],
            "why_now": row["why_now"],
            "inputs": _decode(row["inputs_json"]),
            "steps": _decode(row["steps_json"]),
            "expected_artifact": row["expected_artifact"],
            "checks": _decode(row["checks_json"]),
            "branches": _decode(row["branches_json"]),
            "stop_condition": row["stop_condition"],
            "prohibited_actions": _decode(row["prohibited_actions_json"]),
            "revision": int(row["card_revision"]),
            "confirmed": bool(row["confirmed"]),
            "confirmed_at": row["confirmed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "execution_state": row["execution_state"],
            "execution_revision": int(row["execution_revision"]),
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }

    @staticmethod
    def _row(connection: sqlite3.Connection, task_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM first_action_cards WHERE task_id = ? AND kind = 'RECOVERY'",
            (task_id,),
        ).fetchone()
        if row is None:
            raise KeyError("recovery action not found")
        return row

    def create_from_review(
        self,
        *,
        actor: str,
        project_id: str,
        task_id: str,
        submission_id: str,
        review_id: str,
        review_revision: int,
        goal: str,
        inputs: list[Any],
        steps: list[Any],
        checks: list[Any],
    ) -> dict[str, Any]:
        self._validate_content(goal, inputs, steps, checks)
        if not isinstance(review_revision, int) or review_revision < 1:
            raise ValueError("INVALID_REVIEW_REVISION")

        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            parent = connection.execute(
                """SELECT * FROM first_action_cards
                   WHERE project_id = ? AND task_id = ? AND kind = 'FIRST_ACTION'""",
                (project_id, task_id),
            ).fetchone()
            if parent is None:
                raise KeyError("first action not found")
            submission = connection.execute(
                """SELECT * FROM action_submissions
                   WHERE submission_id = ? AND project_id = ? AND task_id = ?""",
                (submission_id, project_id, task_id),
            ).fetchone()
            if submission is None:
                raise KeyError("action submission not found")
            review = connection.execute(
                """SELECT * FROM action_reviews
                   WHERE review_id = ? AND project_id = ? AND submission_id = ?
                     AND task_id = ?""",
                (review_id, project_id, submission_id, task_id),
            ).fetchone()
            if review is None:
                raise KeyError("action review not found")
            if int(review["revision"]) != review_revision:
                raise ConflictError("RECOVERY_REVIEW_REVISION_CONFLICT")
            if review["overall_status"] == "PASS":
                raise ConflictError("RECOVERY_NOT_REQUIRED")

            existing = connection.execute(
                """SELECT * FROM first_action_cards
                   WHERE project_id = ? AND kind = 'RECOVERY'
                     AND source_review_id = ?""",
                (project_id, review_id),
            ).fetchone()
            if existing is not None:
                return self._public(existing)
            other = connection.execute(
                """SELECT task_id FROM first_action_cards
                   WHERE project_id = ? AND kind = 'RECOVERY'
                     AND parent_task_id = ? AND execution_state != 'CLOSED'""",
                (project_id, task_id),
            ).fetchone()
            if other is not None:
                raise ConflictError("RECOVERY_ALREADY_EXISTS")

            intent = connection.execute(
                """SELECT revision FROM project_intents
                   WHERE project_id = ? ORDER BY revision DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
            now = utc_now()
            recovery_id = f"recovery_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO first_action_cards(
                    task_id, project_id, kind, parent_task_id,
                    source_submission_id, source_review_id, intent_revision,
                    template_version, status, goal, why_now, inputs_json,
                    steps_json, expected_artifact, checks_json, branches_json,
                    stop_condition, prohibited_actions_json, card_revision,
                    confirmed, confirmed_at, created_at, updated_at,
                    execution_state, execution_revision
                ) VALUES (?, ?, 'RECOVERY', ?, ?, ?, ?, ?, 'READY', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, NULL, ?, ?, 'READY', 1)""",
                (
                    recovery_id,
                    project_id,
                    task_id,
                    submission_id,
                    review_id,
                    int(intent["revision"]),
                    f"m3-recovery-v1:{review_id}",
                    goal.strip(),
                    f"由评审 {review_id} 指出的阻塞仍需处理。",
                    _encode(inputs),
                    _encode(steps),
                    "完成恢复动作并重新提交结果",
                    _encode(checks),
                    _encode(["如果仍无法完成，提交 BLOCKED 并保留证据"]),
                    "检查通过后重新提交原任务结果。",
                    _encode(["不得覆盖原始任务", "不得声称已获得系统验证"]),
                    now,
                    now,
                ),
            )
            row = self._row(connection, recovery_id)
            return self._public(row)

    def get_current(self, project_id: str, *, actor: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            row = connection.execute(
                """SELECT * FROM first_action_cards
                   WHERE project_id = ? AND kind = 'RECOVERY'
                   ORDER BY updated_at DESC, created_at DESC, task_id DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
            return self._public(row) if row is not None else None

    def update(
        self,
        *,
        actor: str,
        project_id: str,
        recovery_task_id: str,
        expected_revision: int,
        goal: str,
        inputs: list[Any],
        steps: list[Any],
        checks: list[Any],
    ) -> dict[str, Any]:
        self._validate_content(goal, inputs, steps, checks)
        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            row = self._row(connection, recovery_task_id)
            if row["project_id"] != project_id:
                raise PermissionError("recovery action belongs to another project")
            if int(row["card_revision"]) != int(expected_revision):
                raise ConflictError("RECOVERY_REVISION_CONFLICT")
            now = utc_now()
            connection.execute(
                """UPDATE first_action_cards SET
                    goal=?, why_now=?, inputs_json=?, steps_json=?, checks_json=?,
                    card_revision=?, confirmed=0, confirmed_at=NULL, status='READY',
                    execution_state='READY', execution_revision=execution_revision+1,
                    updated_at=?
                   WHERE task_id=? AND project_id=? AND kind='RECOVERY'""",
                (
                    goal.strip(),
                    row["why_now"],
                    _encode(inputs),
                    _encode(steps),
                    _encode(checks),
                    int(expected_revision) + 1,
                    now,
                    recovery_task_id,
                    project_id,
                ),
            )
            return self._public(self._row(connection, recovery_task_id))

    def confirm(
        self,
        *,
        actor: str,
        project_id: str,
        recovery_task_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            row = self._row(connection, recovery_task_id)
            if row["project_id"] != project_id:
                raise PermissionError("recovery action belongs to another project")
            if int(row["card_revision"]) != int(expected_revision):
                raise ConflictError("RECOVERY_REVISION_CONFLICT")
            if row["status"] != "READY":
                raise ConflictError("RECOVERY_NOT_READY")
            now = utc_now()
            connection.execute(
                """UPDATE first_action_cards
                   SET confirmed=1, confirmed_at=?, updated_at=?
                   WHERE task_id=? AND project_id=? AND kind='RECOVERY'""",
                (now, now, recovery_task_id, project_id),
            )
            return self._public(self._row(connection, recovery_task_id))


__all__ = ["RecoveryService"]
