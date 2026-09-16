"""Provider-free, user-confirmed M3 decisions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import utc_now
from app.errors import ConflictError


DECISIONS = {"CONTINUE", "NARROW", "CHANGE", "STOP", "FINISH"}


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> Any:
    return json.loads(value)


class M3DecisionService:
    """Persist a recommendation separately from the action lifecycle."""

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
    def _public(row: Any) -> dict[str, Any]:
        return {
            "decision_id": row["decision_id"],
            "project_id": row["project_id"],
            "source_submission_id": row["source_submission_id"],
            "source_review_id": row["source_review_id"],
            "decision": row["decision"],
            "rationale": row["rationale"],
            "recommendation": row["recommendation"],
            "remaining_unknowns": _decode(row["remaining_unknowns_json"]),
            "confirmed": bool(row["confirmed"]),
            "confirmed_by": row["confirmed_by"],
            "revision": int(row["revision"]),
            "created_at": row["created_at"],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }

    @staticmethod
    def _decision_row(connection: sqlite3.Connection, project_id: str, decision_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM decision_records WHERE project_id = ? AND decision_id = ?",
            (project_id, decision_id),
        ).fetchone()
        if row is None:
            raise KeyError("decision not found")
        return row

    def recommend(
        self,
        *,
        actor: str,
        project_id: str,
        submission_id: str,
        review_id: str,
        review_revision: int,
        decision: str,
        rationale: str,
        recommendation: str,
        remaining_unknowns: list[Any],
    ) -> dict[str, Any]:
        if decision not in DECISIONS:
            raise ValueError("INVALID_DECISION")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("DECISION_RATIONALE_REQUIRED")
        if not isinstance(recommendation, str) or not recommendation.strip():
            raise ValueError("DECISION_RECOMMENDATION_REQUIRED")
        if not isinstance(remaining_unknowns, list):
            raise ValueError("DECISION_UNKNOWN_LIST_REQUIRED")
        if not isinstance(review_revision, int) or review_revision < 1:
            raise ValueError("INVALID_REVIEW_REVISION")

        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            review = connection.execute(
                """SELECT * FROM action_reviews
                   WHERE review_id = ? AND project_id = ? AND submission_id = ?""",
                (review_id, project_id, submission_id),
            ).fetchone()
            if review is None:
                raise KeyError("action review not found")
            if int(review["revision"]) != review_revision:
                raise ConflictError("M3_DECISION_REVIEW_REVISION_CONFLICT")
            submission = connection.execute(
                """SELECT * FROM action_submissions
                   WHERE submission_id = ? AND project_id = ?""",
                (submission_id, project_id),
            ).fetchone()
            if submission is None:
                raise KeyError("action submission not found")
            if (
                review["task_id"] != submission["task_id"]
                or int(review["submission_revision"]) != int(submission["revision"])
                or int(review["task_revision"]) != int(submission["task_revision"])
            ):
                raise ConflictError("M3_DECISION_REVIEW_BINDING_CONFLICT")
            task = connection.execute(
                """SELECT * FROM first_action_cards
                   WHERE project_id = ? AND task_id = ? AND kind = 'FIRST_ACTION'""",
                (project_id, submission["task_id"]),
            ).fetchone()
            if task is None or task["source_review_id"] != review_id:
                raise ConflictError("M3_DECISION_TASK_REVIEW_CONFLICT")
            if int(task["card_revision"]) != int(review["task_revision"]):
                raise ConflictError("M3_DECISION_TASK_REVISION_CONFLICT")

            existing = connection.execute(
                """SELECT * FROM decision_records
                   WHERE project_id = ? AND source_review_id = ? AND decision = ?
                   ORDER BY revision DESC LIMIT 1""",
                (project_id, review_id, decision),
            ).fetchone()
            if existing is not None and not bool(existing["confirmed"]):
                return self._public(existing)

            latest = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM decision_records WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            now = utc_now()
            decision_id = f"decision_{uuid.uuid4().hex}"
            revision = int(latest["revision"]) + 1
            connection.execute(
                """INSERT INTO decision_records(
                    decision_id, project_id, source_submission_id, source_review_id,
                    decision, rationale, recommendation, remaining_unknowns_json,
                    confirmed, confirmed_by, revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)""",
                (
                    decision_id,
                    project_id,
                    submission_id,
                    review_id,
                    decision,
                    rationale.strip(),
                    recommendation.strip(),
                    _encode(remaining_unknowns),
                    revision,
                    now,
                ),
            )
            return self._public(self._decision_row(connection, project_id, decision_id))

    def confirm(
        self,
        *,
        actor: str,
        project_id: str,
        decision_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        if not isinstance(expected_revision, int) or expected_revision < 1:
            raise ValueError("INVALID_DECISION_REVISION")
        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            row = self._decision_row(connection, project_id, decision_id)
            if int(row["revision"]) != expected_revision:
                raise ConflictError("M3_DECISION_REVISION_CONFLICT")
            if not bool(row["confirmed"]):
                connection.execute(
                    "UPDATE decision_records SET confirmed=1, confirmed_by=? WHERE project_id=? AND decision_id=?",
                    (actor, project_id, decision_id),
                )
            return self._public(self._decision_row(connection, project_id, decision_id))

    def get_current(self, project_id: str, *, actor: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            row = connection.execute(
                """SELECT * FROM decision_records
                   WHERE project_id = ? ORDER BY revision DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
            return self._public(row) if row is not None else None


__all__ = ["M3DecisionService"]
