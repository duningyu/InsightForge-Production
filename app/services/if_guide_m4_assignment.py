"""Frozen, auditable condition assignment for the M4 local evaluation workflow."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from typing import Any

from app.db import utc_now
from app.errors import ConflictError
from app.services.if_guide_m4 import M4EvaluationService


_CONDITIONS: tuple[str, ...] = (
    "STATIC_TEMPLATE",
    "GENERAL_AI",
    "INSIGHTFORGE_STATEFUL",
)
_PURPOSES = {"LEARNING", "PERSONAL_USE", "FOR_OTHERS"}
_ASSIGNABLE_PARTICIPANT_STATES = {"CREATED"}
_WITHDRAWABLE_SESSION_STATES = {"ASSIGNED", "READY", "IN_PROGRESS"}


def _required_text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConflictError(code)
    return value.strip()


def _condition_choice(*, key: str, candidates: Iterable[str]) -> str:
    """Choose deterministically among the least-used condition candidates."""

    return min(candidates, key=lambda condition: hashlib.sha256(
        f"{key}:{condition}".encode("utf-8")
    ).hexdigest())


class M4AssignmentService:
    """Owns the one-way, purpose-stratified M4 assignment mutation."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._evaluation = M4EvaluationService(db)

    def _experiment(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        account_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM m4_experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row is None:
            raise KeyError("M4_EXPERIMENT_NOT_FOUND")
        if row["account_id"] != account_id:
            raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
        if row["state"] != "FROZEN":
            raise ConflictError("EXPERIMENT_NOT_FROZEN")
        return row

    @staticmethod
    def _participant(
        connection: sqlite3.Connection,
        participant_id: str,
        experiment_id: str,
        account_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM m4_participants WHERE participant_id = ?",
            (participant_id,),
        ).fetchone()
        if row is None:
            raise KeyError("M4_PARTICIPANT_NOT_FOUND")
        if row["account_id"] != account_id:
            raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
        if row["experiment_id"] != experiment_id:
            raise ConflictError("PARTICIPANT_EXPERIMENT_MISMATCH")
        if row["purpose"] not in _PURPOSES:
            raise ConflictError("PARTICIPANT_PURPOSE_INVALID")
        return row

    @staticmethod
    def _condition_versions(experiment: sqlite3.Row) -> dict[str, Any]:
        definitions = json.loads(experiment["condition_definitions_json"])
        if set(definitions) != set(_CONDITIONS):
            raise ConflictError("EXPERIMENT_CONDITIONS_INVALID")
        return definitions

    def assign_session(
        self,
        *,
        session_id: str,
        experiment_id: str,
        participant_id: str,
        account_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        """Assign one participant once using the frozen balanced-by-purpose rule."""

        session_id = _required_text(session_id, "SESSION_ID_REQUIRED")
        with self.db.connect() as connection:
            experiment = self._experiment(connection, experiment_id, account_id)
            participant = self._participant(
                connection, participant_id, experiment_id, account_id
            )
            existing = connection.execute(
                """
                SELECT session_id FROM m4_sessions
                WHERE experiment_id = ? AND participant_id = ?
                """,
                (experiment_id, participant_id),
            ).fetchone()
            if existing is not None:
                raise ConflictError("SESSION_ALREADY_ASSIGNED")
            if participant["state"] not in _ASSIGNABLE_PARTICIPANT_STATES:
                raise ConflictError("PARTICIPANT_NOT_ASSIGNABLE")
            if self._evaluation._project_owner(connection, project_id) != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")

            counts = {
                condition: 0 for condition in _CONDITIONS
            }
            rows = connection.execute(
                """
                SELECT s.condition, COUNT(*) AS count
                FROM m4_sessions AS s
                JOIN m4_participants AS p ON p.participant_id = s.participant_id
                WHERE s.experiment_id = ? AND p.purpose = ?
                GROUP BY s.condition
                """,
                (experiment_id, participant["purpose"]),
            ).fetchall()
            for row in rows:
                if row["condition"] in counts:
                    counts[row["condition"]] = int(row["count"])
            lowest = min(counts.values())
            candidates = [
                condition for condition, count in counts.items() if count == lowest
            ]
            condition = _condition_choice(
                key=(
                    f"{experiment_id}:{participant['purpose']}:{participant_id}:"
                    f"{experiment['assignment_rule']}"
                ),
                candidates=candidates,
            )
            versions = self._condition_versions(experiment)
            condition_definition = versions[condition]
            if not isinstance(condition_definition, dict):
                raise ConflictError("EXPERIMENT_CONDITIONS_INVALID")
            condition_version = _required_text(
                str(condition_definition.get("version", "")),
                "CONDITION_VERSION_REQUIRED",
            )
            now = utc_now()
            try:
                connection.execute(
                    """
                    INSERT INTO m4_sessions (
                        session_id, experiment_id, participant_id, account_id,
                        project_id, condition, assignment_rule_version,
                        condition_version, source_commit, deployment_id,
                        state, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ASSIGNED', 1, ?, ?)
                    """,
                    (
                        session_id,
                        experiment_id,
                        participant_id,
                        account_id,
                        project_id,
                        condition,
                        _required_text(
                            experiment["assignment_rule"],
                            "ASSIGNMENT_RULE_VERSION_REQUIRED",
                        ),
                        condition_version,
                        _required_text(
                            experiment["source_commit"], "SOURCE_COMMIT_REQUIRED"
                        ),
                        _required_text(
                            experiment["deployment_id"], "DEPLOYMENT_ID_REQUIRED"
                        ),
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE m4_participants
                    SET state = 'ASSIGNED', updated_at = ?
                    WHERE participant_id = ?
                    """,
                    (now, participant_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("SESSION_ALREADY_ASSIGNED") from exc
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            result = dict(row)
            result.update(
                {
                    "purpose": participant["purpose"],
                    "deviation_reason": None,
                    "assigned_at": row["created_at"],
                }
            )
            return result

    def withdraw_session(
        self,
        *,
        session_id: str,
        account_id: str,
        expected_revision: int,
        reason: str,
    ) -> dict[str, Any]:
        reason = _required_text(reason, "WITHDRAWAL_REASON_REQUIRED")
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            if row["account_id"] != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
            if row["revision"] != expected_revision:
                raise ConflictError("SESSION_REVISION_CONFLICT")
            if row["state"] not in _WITHDRAWABLE_SESSION_STATES:
                raise ConflictError("INVALID_SESSION_TRANSITION")
            now = utc_now()
            connection.execute(
                """
                UPDATE m4_sessions
                SET state = 'WITHDRAWN', revision = revision + 1, updated_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            connection.execute(
                """
                UPDATE m4_participants
                SET state = 'WITHDRAWN', withdrawal_reason = ?, updated_at = ?
                WHERE participant_id = ? AND experiment_id = ?
                """,
                (reason, now, row["participant_id"], row["experiment_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            result = dict(updated)
            result["withdrawal_reason"] = reason
            return result

    def get_assignment(self, *, session_id: str, account_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                """
                SELECT s.*, p.purpose
                FROM m4_sessions AS s
                JOIN m4_participants AS p ON p.participant_id = s.participant_id
                WHERE s.session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            if row["account_id"] != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
            result = dict(row)
            result["deviation_reason"] = None
            result["assigned_at"] = row["created_at"]
            return result
