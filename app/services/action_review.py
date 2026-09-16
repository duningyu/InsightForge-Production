"""Owner-visible, provider-free review of an IF Guide M3 submission."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from app.db import utc_now
from app.errors import ConflictError
from app.services.if_guide_m3_guards import validate_evidence_level


REVIEW_STATUSES = {"PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"}
EVIDENCE_LEVELS = {"USER_REPORTED", "ARTIFACT_CHECKED", "AUTHORIZED_RUN"}
CHECK_OUTCOMES = REVIEW_STATUSES


def _encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode(value: str) -> Any:
    return json.loads(value)


def _evidence_hash(
    *,
    project_id: str,
    submission_id: str,
    submission_revision: int,
    task_id: str,
    task_revision: int,
    check_items: list[Any],
    overall_status: str,
    known_unknowns: list[Any],
    evidence_level: str,
) -> str:
    payload = {
        "project_id": project_id,
        "submission_id": submission_id,
        "submission_revision": submission_revision,
        "task_id": task_id,
        "task_revision": task_revision,
        "check_items": check_items,
        "overall_status": overall_status,
        "known_unknowns": known_unknowns,
        "evidence_level": evidence_level,
    }
    return hashlib.sha256(_encode(payload).encode("utf-8")).hexdigest()


class ActionReviewService:
    """Persist honest review results without upgrading user evidence."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _project(connection, project_id: str) -> None:
        row = connection.execute(
            "SELECT status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise KeyError("project not found")
        if row["status"] != "active":
            raise ValueError("project is not active")

    @staticmethod
    def _owner(connection, project_id: str) -> str:
        row = connection.execute(
            """SELECT owner_actor FROM project_intents
               WHERE project_id = ? ORDER BY revision DESC LIMIT 1""",
            (project_id,),
        ).fetchone()
        if row is None:
            raise ConflictError("INTENT_REQUIRED")
        return str(row["owner_actor"])

    @staticmethod
    def _validate_check_items(check_items: list[Any], overall_status: str) -> None:
        if not isinstance(check_items, list):
            raise ValueError("CHECK_ITEMS_REQUIRED")
        for item in check_items:
            if not isinstance(item, dict):
                raise ValueError("INVALID_CHECK_ITEM")
            check_id = item.get("check_id")
            outcome = item.get("outcome")
            if not isinstance(check_id, str) or not check_id.strip():
                raise ValueError("CHECK_ID_REQUIRED")
            if outcome not in CHECK_OUTCOMES:
                raise ValueError("INVALID_CHECK_OUTCOME")
        if overall_status == "PASS":
            if not check_items:
                raise ValueError("PASS_EVIDENCE_REQUIRED")
            for item in check_items:
                refs = item.get("evidence_refs")
                if item.get("outcome") != "PASS" or not isinstance(refs, list) or not refs:
                    raise ValueError("PASS_EVIDENCE_REQUIRED")

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        return {
            "review_id": row["review_id"],
            "project_id": row["project_id"],
            "submission_id": row["submission_id"],
            "submission_revision": int(row["submission_revision"]),
            "task_id": row["task_id"],
            "task_revision": int(row["task_revision"]),
            "check_items": _decode(row["check_items_json"]),
            "overall_status": row["overall_status"],
            "known_unknowns": _decode(row["known_unknowns_json"]),
            "evidence_level": row["evidence_level"],
            "recommendation": row["recommendation"],
            "reviewer_role": row["reviewer_role"],
            "revision": int(row["revision"]),
            "evidence_hash": row["evidence_hash"],
            "created_at": row["created_at"],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }

    def review(
        self,
        *,
        project_id: str,
        submission_id: str,
        submission_revision: int,
        task_id: str,
        task_revision: int,
        check_items: list[Any],
        overall_status: str,
        known_unknowns: list[Any],
        evidence_level: str,
        recommendation: str,
        reviewer_role: str,
        actor: str,
    ) -> dict[str, Any]:
        if overall_status not in REVIEW_STATUSES:
            raise ValueError("INVALID_REVIEW_STATUS")
        evidence_refs = [
            ref
            for item in check_items
            if isinstance(item, dict)
            for ref in (item.get("evidence_refs") or [])
        ]
        validate_evidence_level(evidence_level, evidence_refs)
        if not isinstance(submission_revision, int) or submission_revision < 1:
            raise ValueError("INVALID_SUBMISSION_REVISION")
        if not isinstance(task_revision, int) or task_revision < 1:
            raise ValueError("INVALID_TASK_REVISION")
        if not isinstance(known_unknowns, list):
            raise ValueError("KNOWN_UNKNOWNS_REQUIRED")
        if not isinstance(recommendation, str):
            raise ValueError("RECOMMENDATION_REQUIRED")
        if overall_status == "NOT_APPLICABLE" and not recommendation.strip():
            raise ValueError("NOT_APPLICABLE_JUSTIFICATION_REQUIRED")
        self._validate_check_items(check_items, overall_status)

        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            task = connection.execute(
                """SELECT * FROM first_action_cards
                   WHERE project_id = ? AND task_id = ? AND kind = 'FIRST_ACTION'""",
                (project_id, task_id),
            ).fetchone()
            if task is None:
                raise KeyError("first action not found")
            if int(task["card_revision"]) != task_revision:
                raise ConflictError("ACTION_REVIEW_TASK_REVISION_CONFLICT")
            submission = connection.execute(
                """SELECT * FROM action_submissions
                   WHERE submission_id = ? AND project_id = ? AND task_id = ?""",
                (submission_id, project_id, task_id),
            ).fetchone()
            if submission is None:
                raise KeyError("action submission not found")
            if int(submission["revision"]) != submission_revision:
                raise ConflictError("ACTION_REVIEW_SUBMISSION_REVISION_CONFLICT")
            if int(submission["task_revision"]) != task_revision:
                raise ConflictError("ACTION_REVIEW_TASK_REVISION_CONFLICT")

            current = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM action_reviews WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
            revision = int(current["revision"]) + 1
            now = utc_now()
            review_id = f"review_{uuid.uuid4().hex}"
            evidence_hash = _evidence_hash(
                project_id=project_id,
                submission_id=submission_id,
                submission_revision=submission_revision,
                task_id=task_id,
                task_revision=task_revision,
                check_items=check_items,
                overall_status=overall_status,
                known_unknowns=known_unknowns,
                evidence_level=evidence_level,
            )
            connection.execute(
                """INSERT INTO action_reviews(
                    review_id, project_id, submission_id, submission_revision,
                    task_id, task_revision, check_items_json, overall_status,
                    known_unknowns_json, evidence_level, recommendation,
                    reviewer_role, revision, evidence_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    project_id,
                    submission_id,
                    submission_revision,
                    task_id,
                    task_revision,
                    _encode(check_items),
                    overall_status,
                    _encode(known_unknowns),
                    evidence_level,
                    recommendation.strip(),
                    reviewer_role.strip() or "system_review",
                    revision,
                    evidence_hash,
                    now,
                ),
            )
            next_state = "CLOSED" if overall_status == "PASS" else "NEEDS_REVISION"
            connection.execute(
                """UPDATE first_action_cards
                   SET source_review_id = ?, execution_state = ?, updated_at = ?
                   WHERE project_id = ? AND task_id = ? AND kind = 'FIRST_ACTION'""",
                (review_id, next_state, now, project_id, task_id),
            )
            return self._public(
                connection.execute(
                    "SELECT * FROM action_reviews WHERE review_id = ?", (review_id,)
                ).fetchone()
            )

    def list_for_submission(
        self, project_id: str, submission_id: str, *, actor: str
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            if self._owner(connection, project_id) != actor:
                raise PermissionError("project belongs to another actor")
            rows = connection.execute(
                """SELECT * FROM action_reviews
                   WHERE project_id = ? AND submission_id = ?
                   ORDER BY revision ASC, created_at ASC""",
                (project_id, submission_id),
            ).fetchall()
            return {
                "project_id": project_id,
                "submission_id": submission_id,
                "reviews": [self._public(row) for row in rows],
                "provider_dispatches": 0,
                "provider_transports": 0,
                "search_requests": 0,
            }
