"""User ActionSubmission persistence for IF Guide R1.1 M3.

Submissions record what an owner reports about the current first action.  They
are deliberately not execution or verification records: this service never
invokes a provider, search client, or external tool.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import utc_now
from app.errors import ConflictError


SUBMISSION_KINDS = {"DONE", "BLOCKED"}
SOURCE_IDENTITIES = {
    "USER_INPUT",
    "MODEL_HYPOTHESIS",
    "REAL_OBSERVATION",
    "SIMULATION",
    "IMPLEMENTATION_EVIDENCE",
}
_EXECUTION_CLAIM_KEYS = {
    "executed",
    "tested",
    "deployed",
    "verified",
    "system_verified",
    "authorized_run",
}


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> Any:
    return json.loads(value)


class ActionSubmissionService:
    """Persist owner-submitted M3 results against an exact action revision."""

    def __init__(self, db):
        self.db = db

    def _project(self, connection, project_id: str) -> Any:
        row = connection.execute(
            "SELECT id, status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError("project not found")
        if row["status"] != "active":
            raise ValueError("project is not active")
        return row

    def _current_owner(self, connection, project_id: str) -> str:
        row = connection.execute(
            """SELECT owner_actor FROM project_intents
               WHERE project_id = ? ORDER BY revision DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        if row is None:
            raise ConflictError("INTENT_REQUIRED")
        return str(row["owner_actor"])

    def _task(self, connection, project_id: str, task_id: str) -> Any:
        row = connection.execute(
            """SELECT * FROM first_action_cards
               WHERE project_id = ? AND task_id = ? AND kind = 'FIRST_ACTION'""",
            (project_id, task_id),
        ).fetchone()
        if row is None:
            raise KeyError("first action not found")
        return row

    @staticmethod
    def _validate_execution_claim(execution_claim: dict[str, Any]) -> None:
        if not isinstance(execution_claim, dict):
            raise ValueError("execution_claim must be an object")
        for key, value in execution_claim.items():
            if str(key).casefold() in _EXECUTION_CLAIM_KEYS and bool(value):
                raise ValueError("EXECUTION_CLAIM_NOT_VERIFIED")
            if (
                str(key).casefold() == "evidence_level"
                and str(value).upper() == "AUTHORIZED_RUN"
            ):
                raise ValueError("AUTHORIZED_RUN_NOT_ALLOWED")

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        return {
            "submission_id": row["submission_id"],
            "project_id": row["project_id"],
            "task_id": row["task_id"],
            "task_revision": int(row["task_revision"]),
            "submission_kind": row["submission_kind"],
            "description": row["description"],
            "attachment_refs": _decode(row["attachment_refs_json"]),
            "check_results": _decode(row["check_results_json"]),
            "execution_claim": _decode(row["execution_claim_json"]),
            "source_identity": row["source_identity"],
            "revision": int(row["revision"]),
            "submitted_by": row["submitted_by"],
            "created_at": row["created_at"],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }

    def submit(
        self,
        *,
        project_id: str,
        task_id: str,
        task_revision: int,
        submission_kind: str,
        description: str,
        attachment_refs: list[Any],
        check_results: list[Any],
        execution_claim: dict[str, Any],
        source_identity: str,
        actor: str,
    ) -> dict[str, Any]:
        if submission_kind not in SUBMISSION_KINDS:
            raise ValueError("INVALID_SUBMISSION_KIND")
        if source_identity not in SOURCE_IDENTITIES:
            raise ValueError("INVALID_SOURCE_IDENTITY")
        if not isinstance(task_revision, int) or task_revision < 1:
            raise ValueError("INVALID_TASK_REVISION")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("DESCRIPTION_REQUIRED")
        if not isinstance(attachment_refs, list) or not isinstance(check_results, list):
            raise ValueError("SUBMISSION_COLLECTIONS_REQUIRED")
        self._validate_execution_claim(execution_claim)

        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._current_owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            task = self._task(connection, project_id, task_id)
            if int(task["card_revision"]) != task_revision:
                raise ConflictError("ACTION_SUBMISSION_REVISION_CONFLICT")
            if not bool(task["confirmed"]):
                raise ConflictError("ACTION_NOT_CONFIRMED")
            if task["status"] != "READY":
                raise ConflictError("ACTION_NOT_READY")
            current = connection.execute(
                """SELECT COALESCE(MAX(revision), 0) AS revision
                   FROM action_submissions
                   WHERE project_id = ? AND task_id = ? AND task_revision = ?""",
                (project_id, task_id, task_revision),
            ).fetchone()
            revision = int(current["revision"]) + 1
            now = utc_now()
            submission_id = f"submission_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO action_submissions(
                    submission_id, project_id, task_id, task_revision,
                    submission_kind, description, attachment_refs_json,
                    check_results_json, execution_claim_json, source_identity,
                    revision, submitted_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    submission_id,
                    project_id,
                    task_id,
                    task_revision,
                    submission_kind,
                    description.strip(),
                    _encode(attachment_refs),
                    _encode(check_results),
                    _encode(execution_claim),
                    source_identity,
                    revision,
                    actor,
                    now,
                ),
            )
            connection.execute(
                """UPDATE first_action_cards
                   SET execution_state = 'SUBMITTED',
                       execution_revision = execution_revision + 1,
                       updated_at = ?
                   WHERE task_id = ? AND project_id = ?""",
                (now, task_id, project_id),
            )
            return self._public(
                connection.execute(
                    "SELECT * FROM action_submissions WHERE submission_id = ?",
                    (submission_id,),
                ).fetchone()
            )
