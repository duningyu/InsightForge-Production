"""Human-confirmed Requirement Gold Set and annotation boundaries for M4.

This module deliberately stores only structured evaluation metadata.  It never
persists the participant's raw idea, transcript, or other private body text.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any, Mapping

from app.db import utc_now
from app.errors import ConflictError
from app.services.if_guide_m4 import M4EvaluationService


_IMPORTANCE = {"CRITICAL", "SECONDARY"}
_SOURCES = {"RAW_IDEA", "USER_CONFIRMED_BRIEF", "USER_EDIT"}
_ROLES = {"PARTICIPANT", "INDEPENDENT_REVIEWER", "LLM_ASSIST", "SYSTEM"}
_ADJUDICATION = {"PENDING", "ADJUDICATED", "NOT_REQUIRED"}
_SOURCE_IDENTITIES = {
    "USER_INPUT",
    "MODEL_HYPOTHESIS",
    "REAL_OBSERVATION",
    "SIMULATION",
    "IMPLEMENTATION_EVIDENCE",
}
_UNSAFE_KEYS = {
    "body",
    "content",
    "raw_idea",
    "provider_payload",
    "response_body",
    "full_text",
    "acknowledgement_text",
    "transcript",
    "email",
    "phone",
    "name",
    "private_text",
    "raw_text",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConflictError(code)
    return value.strip()


def _safe_metadata(value: Any, path: str = "metadata") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _UNSAFE_KEYS:
                raise ValueError(f"unsafe annotation evidence field: {path}.{key}")
            _safe_metadata(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _safe_metadata(child, f"{path}[{index}]")


def _string_list(value: Any, code: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ConflictError(code)
    result = [_text(item, code) for item in value]
    _safe_metadata(result, code)
    return result


class M4GoldSetService:
    """Persistence boundary for participant-confirmed M4 ground truth."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._evaluation = M4EvaluationService(db)

    def _session(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        account_id: str,
        participant_id: str | None = None,
        project_id: str | None = None,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError("M4_SESSION_NOT_FOUND")
        self._evaluation._check_account(row, account_id)
        if participant_id is not None and row["participant_id"] != participant_id:
            raise ConflictError("GOLD_SET_PARTICIPANT_MISMATCH")
        if project_id is not None and row["project_id"] != project_id:
            raise ConflictError("GOLD_SET_PROJECT_MISMATCH")
        if self._evaluation._project_owner(connection, row["project_id"]) != account_id:
            raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
        return row

    @staticmethod
    def _validate_requirements(requirements: Any) -> list[dict[str, str]]:
        if not isinstance(requirements, (list, tuple)) or not requirements:
            raise ConflictError("GOLD_SET_REQUIREMENTS_REQUIRED")
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in requirements:
            if not isinstance(item, Mapping):
                raise ConflictError("GOLD_SET_REQUIREMENT_INVALID")
            requirement_id = _text(item.get("requirement_id"), "GOLD_SET_REQUIREMENT_ID_REQUIRED")
            if requirement_id in seen:
                raise ConflictError("GOLD_SET_REQUIREMENT_DUPLICATE")
            seen.add(requirement_id)
            importance = item.get("importance")
            source = item.get("source")
            if importance not in _IMPORTANCE:
                raise ConflictError("GOLD_SET_IMPORTANCE_INVALID")
            if source not in _SOURCES:
                raise ConflictError("GOLD_SET_SOURCE_INVALID")
            canonical_text = _text(
                item.get("canonical_text"), "GOLD_SET_CANONICAL_TEXT_REQUIRED"
            )
            normalized.append(
                {
                    "requirement_id": requirement_id,
                    "canonical_text": canonical_text,
                    "importance": importance,
                    "source": source,
                }
            )
        return normalized

    def finalize_gold_set(
        self,
        *,
        session_id: str,
        account_id: str,
        participant_id: str,
        project_id: str,
        purpose: str,
        constraints: list[str],
        explicit_non_goals: list[str],
        requirements: list[dict[str, str]],
        participant_confirmed: bool,
        expected_session_revision: int,
        confirmed_by: str = "idea_provider",
    ) -> dict[str, Any]:
        if not participant_confirmed:
            raise ConflictError("GOLD_SET_PARTICIPANT_CONFIRMATION_REQUIRED")
        if confirmed_by != "idea_provider":
            raise ConflictError("GOLD_SET_HUMAN_CONFIRMATION_REQUIRED")
        purpose = _text(purpose, "GOLD_SET_PURPOSE_REQUIRED")
        constraints = _string_list(constraints, "GOLD_SET_CONSTRAINTS_INVALID")
        explicit_non_goals = _string_list(
            explicit_non_goals, "GOLD_SET_NON_GOALS_INVALID"
        )
        normalized = self._validate_requirements(requirements)
        _safe_metadata({"purpose": purpose, "constraints": constraints, "non_goals": explicit_non_goals})

        with self.db.connect() as connection:
            session = self._session(
                connection, session_id, account_id, participant_id, project_id
            )
            if session["revision"] != expected_session_revision:
                raise ConflictError("M4_SESSION_REVISION_CONFLICT")
            latest = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision "
                "FROM m4_requirement_gold_items WHERE session_id = ?",
                (session_id,),
            ).fetchone()["revision"]
            revision = int(latest) + 1
            now = utc_now()
            for item in normalized:
                connection.execute(
                    """
                    INSERT INTO m4_requirement_gold_items (
                        gold_item_id, session_id, participant_id, project_id,
                        requirement_id, canonical_text, importance, source,
                        confirmed_by, participant_confirmed, revision, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        session_id,
                        participant_id,
                        project_id,
                        item["requirement_id"],
                        item["canonical_text"],
                        item["importance"],
                        item["source"],
                        confirmed_by,
                        revision,
                        now,
                    ),
                )
            context = {
                "purpose": purpose,
                "constraints": constraints,
                "explicit_non_goals": explicit_non_goals,
                "participant_confirmed": True,
                "confirmed_by": confirmed_by,
                "gold_set_revision": revision,
            }
            connection.execute(
                """
                INSERT INTO m4_quality_annotations (
                    annotation_id, session_id, project_id, artifact_ref,
                    annotation_type, target_id, label, evaluator_role,
                    adjudication_status, evidence_hash, evidence_ref_json,
                    revision, created_at
                ) VALUES (?, ?, ?, 'GOLD_SET', 'CONTEXT', ?, 'CONFIRMED',
                          'PARTICIPANT', 'NOT_REQUIRED', ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    session_id,
                    project_id,
                    f"context:r{revision}",
                    _hash(context),
                    _json(context),
                    revision,
                    now,
                ),
            )
            return {
                "session_id": session_id,
                "participant_id": participant_id,
                "project_id": project_id,
                "revision": revision,
                "finalized": True,
                "confirmed_by": confirmed_by,
                "purpose": purpose,
                "constraints": constraints,
                "explicit_non_goals": explicit_non_goals,
                "requirements": normalized,
            }

    def get_gold_set(self, session_id: str, account_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            session = self._session(connection, session_id, account_id)
            row = connection.execute(
                "SELECT MAX(revision) AS revision FROM m4_requirement_gold_items "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            revision = row["revision"]
            if revision is None:
                raise KeyError("GOLD_SET_NOT_FOUND")
            items = connection.execute(
                "SELECT requirement_id, canonical_text, importance, source "
                "FROM m4_requirement_gold_items WHERE session_id = ? AND revision = ? "
                "ORDER BY rowid",
                (session_id, revision),
            ).fetchall()
            context = connection.execute(
                "SELECT evidence_ref_json FROM m4_quality_annotations "
                "WHERE session_id = ? AND artifact_ref = 'GOLD_SET' "
                "AND annotation_type = 'CONTEXT' AND revision = ?",
                (session_id, revision),
            ).fetchone()
            if context is None:
                raise ConflictError("GOLD_SET_CONTEXT_MISSING")
            values = _from_json(context["evidence_ref_json"])
            return {
                "session_id": session_id,
                "participant_id": session["participant_id"],
                "project_id": session["project_id"],
                "revision": int(revision),
                "finalized": True,
                "confirmed_by": "idea_provider",
                "purpose": values["purpose"],
                "constraints": values["constraints"],
                "explicit_non_goals": values["explicit_non_goals"],
                "requirements": [dict(item) for item in items],
            }

    def create_annotation(
        self,
        *,
        session_id: str,
        account_id: str,
        project_id: str,
        artifact_ref: str,
        annotation_type: str,
        target_id: str,
        label: str,
        evaluator_role: str,
        evidence_ref: Mapping[str, Any] | str | None = None,
        disagreement: Mapping[str, Any] | None = None,
        source_identity: str | None = None,
        adjudication_status: str | None = None,
        expected_session_revision: int | None = None,
    ) -> dict[str, Any]:
        if evaluator_role not in _ROLES:
            raise ConflictError("ANNOTATION_EVALUATOR_ROLE_INVALID")
        if source_identity is not None and source_identity not in _SOURCE_IDENTITIES:
            raise ConflictError("ANNOTATION_SOURCE_IDENTITY_INVALID")
        status = adjudication_status or (
            "PENDING" if evaluator_role in {"LLM_ASSIST", "INDEPENDENT_REVIEWER"} else "NOT_REQUIRED"
        )
        if status not in _ADJUDICATION:
            raise ConflictError("ANNOTATION_ADJUDICATION_STATUS_INVALID")
        if evaluator_role == "LLM_ASSIST" and status == "ADJUDICATED":
            raise ConflictError("LLM_ASSIST_CANNOT_FINALIZE_GROUND_TRUTH")
        if evidence_ref is None:
            evidence: dict[str, Any] = {}
        elif isinstance(evidence_ref, Mapping):
            evidence = dict(evidence_ref)
        else:
            evidence = {"ref": _text(evidence_ref, "ANNOTATION_EVIDENCE_REF_INVALID")}
        if disagreement is not None:
            evidence["disagreement"] = dict(disagreement)
        if source_identity is not None:
            evidence["source_identity"] = source_identity
        _safe_metadata(evidence)
        artifact_ref = _text(artifact_ref, "ANNOTATION_ARTIFACT_REQUIRED")
        annotation_type = _text(annotation_type, "ANNOTATION_TYPE_REQUIRED")
        target_id = _text(target_id, "ANNOTATION_TARGET_REQUIRED")
        label = _text(label, "ANNOTATION_LABEL_REQUIRED")

        with self.db.connect() as connection:
            session = self._session(connection, session_id, account_id, project_id=project_id)
            if expected_session_revision is not None and session["revision"] != expected_session_revision:
                raise ConflictError("M4_SESSION_REVISION_CONFLICT")
            row = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) AS revision FROM m4_quality_annotations "
                "WHERE session_id = ? AND artifact_ref = ? AND target_id = ?",
                (session_id, artifact_ref, target_id),
            ).fetchone()
            revision = int(row["revision"]) + 1
            now = utc_now()
            annotation_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO m4_quality_annotations (
                    annotation_id, session_id, project_id, artifact_ref,
                    annotation_type, target_id, label, evaluator_role,
                    adjudication_status, evidence_hash, evidence_ref_json,
                    revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    annotation_id,
                    session_id,
                    project_id,
                    artifact_ref,
                    annotation_type,
                    target_id,
                    label,
                    evaluator_role,
                    status,
                    _hash(evidence),
                    _json(evidence),
                    revision,
                    now,
                ),
            )
            return {
                "annotation_id": annotation_id,
                "session_id": session_id,
                "project_id": project_id,
                "artifact_ref": artifact_ref,
                "annotation_type": annotation_type,
                "target_id": target_id,
                "label": label,
                "evaluator_role": evaluator_role,
                "adjudication_status": status,
                "evidence_hash": _hash(evidence),
                "evidence_ref": evidence,
                "revision": revision,
                "created_at": now,
            }


def _from_json(value: str) -> Any:
    return json.loads(value)
