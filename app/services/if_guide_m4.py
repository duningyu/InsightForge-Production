"""M4 controlled-evaluation experiment and session lifecycle services."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.db import utc_now
from app.errors import ConflictError


_ALLOWED_CONDITIONS = {
    "STATIC_TEMPLATE",
    "GENERAL_AI",
    "INSIGHTFORGE_STATEFUL",
}
_ALLOWED_PURPOSES = {"LEARNING", "PERSONAL_USE", "FOR_OTHERS"}
_EXPERIMENT_STATES = {"DRAFT", "FROZEN", "VERSION_SPLIT", "CLOSED"}
_SESSION_STATES = {
    "CREATED",
    "ASSIGNED",
    "READY",
    "IN_PROGRESS",
    "COMPLETED",
    "WITHDRAWN",
    "OPERATIONAL_INCOMPLETE",
    "QUALITY_INCOMPLETE",
    "FINALIZED",
}
_SESSION_TRANSITIONS = {
    "ASSIGNED": {"READY", "WITHDRAWN", "OPERATIONAL_INCOMPLETE"},
    "READY": {"IN_PROGRESS", "WITHDRAWN", "OPERATIONAL_INCOMPLETE"},
    "IN_PROGRESS": {
        "COMPLETED",
        "WITHDRAWN",
        "OPERATIONAL_INCOMPLETE",
        "QUALITY_INCOMPLETE",
    },
    "COMPLETED": {"FINALIZED"},
    "QUALITY_INCOMPLETE": {"FINALIZED"},
    "OPERATIONAL_INCOMPLETE": {"FINALIZED"},
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _from_json(value: str | None) -> Any:
    return json.loads(value) if value else None


def _required_text(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConflictError(code)
    return value.strip()


class M4EvaluationService:
    """Persistence boundary for frozen M4 definitions and owned sessions."""

    def __init__(self, db: Any) -> None:
        self.db = db

    @staticmethod
    def _check_revision(row: sqlite3.Row, expected_revision: int, code: str) -> None:
        if row["revision"] != expected_revision:
            raise ConflictError(code)

    @staticmethod
    def _check_account(row: sqlite3.Row, account_id: str) -> None:
        if row["account_id"] != account_id:
            raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")

    def _experiment(
        self,
        connection: sqlite3.Connection,
        experiment_id: str,
        account_id: str | None = None,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM m4_experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row is None:
            raise KeyError("M4_EXPERIMENT_NOT_FOUND")
        if account_id is not None:
            self._check_account(row, account_id)
        return row

    @staticmethod
    def _experiment_public(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field in (
            "condition_definitions_json",
            "metric_versions_json",
            "rubric_versions_json",
            "threshold_policy_json",
            "operator_assistance_policy_json",
        ):
            result[field.removesuffix("_json")] = _from_json(result.pop(field))
        return result

    def create_experiment(
        self,
        *,
        experiment_id: str,
        account_id: str,
        spec_version: str,
        source_commit: str,
        deployment_id: str,
        condition_definitions: dict[str, Any],
        assignment_rule: str,
        metric_versions: dict[str, Any],
        rubric_versions: dict[str, Any],
        threshold_policy: dict[str, Any],
        operator_assistance_policy: dict[str, Any],
    ) -> dict[str, Any]:
        experiment_id = _required_text(experiment_id, "EXPERIMENT_ID_REQUIRED")
        account_id = _required_text(account_id, "ACCOUNT_ID_REQUIRED")
        if set(condition_definitions) != _ALLOWED_CONDITIONS:
            raise ConflictError("EXPERIMENT_CONDITIONS_INVALID")
        now = utc_now()
        with self.db.connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO m4_experiments (
                        experiment_id, account_id, spec_version, source_commit,
                        deployment_id, condition_definitions_json, assignment_rule,
                        metric_versions_json, rubric_versions_json,
                        threshold_policy_json, operator_assistance_policy_json,
                        state, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', 1, ?, ?)
                    """,
                    (
                        experiment_id,
                        account_id,
                        _required_text(spec_version, "SPEC_VERSION_REQUIRED"),
                        _required_text(source_commit, "SOURCE_COMMIT_REQUIRED"),
                        _required_text(deployment_id, "DEPLOYMENT_ID_REQUIRED"),
                        _json(condition_definitions),
                        _required_text(assignment_rule, "ASSIGNMENT_RULE_REQUIRED"),
                        _json(metric_versions),
                        _json(rubric_versions),
                        _json(threshold_policy),
                        _json(operator_assistance_policy),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("EXPERIMENT_EXISTS") from exc
            return self._experiment_public(
                self._experiment(connection, experiment_id, account_id)
            )

    def update_experiment_metadata(
        self,
        *,
        experiment_id: str,
        account_id: str,
        expected_revision: int,
        condition_definitions: dict[str, Any] | None = None,
        assignment_rule: str | None = None,
        metric_versions: dict[str, Any] | None = None,
        rubric_versions: dict[str, Any] | None = None,
        threshold_policy: dict[str, Any] | None = None,
        operator_assistance_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fields: list[tuple[str, Any]] = []
        if condition_definitions is not None:
            if set(condition_definitions) != _ALLOWED_CONDITIONS:
                raise ConflictError("EXPERIMENT_CONDITIONS_INVALID")
            fields.append(("condition_definitions_json", _json(condition_definitions)))
        if assignment_rule is not None:
            fields.append(("assignment_rule", _required_text(assignment_rule, "ASSIGNMENT_RULE_REQUIRED")))
        for name, value in (
            ("metric_versions_json", metric_versions),
            ("rubric_versions_json", rubric_versions),
            ("threshold_policy_json", threshold_policy),
            ("operator_assistance_policy_json", operator_assistance_policy),
        ):
            if value is not None:
                fields.append((name, _json(value)))
        with self.db.connect() as connection:
            row = self._experiment(connection, experiment_id, account_id)
            self._check_revision(row, expected_revision, "EXPERIMENT_REVISION_CONFLICT")
            if row["state"] != "DRAFT":
                raise ConflictError("EXPERIMENT_FROZEN")
            if fields:
                assignments = ", ".join(f"{name} = ?" for name, _ in fields)
                values = [value for _, value in fields]
                now = utc_now()
                connection.execute(
                    f"UPDATE m4_experiments SET {assignments}, revision = revision + 1, updated_at = ? WHERE experiment_id = ?",
                    (*values, now, experiment_id),
                )
            return self._experiment_public(
                self._experiment(connection, experiment_id, account_id)
            )

    def freeze_experiment(
        self, *, experiment_id: str, account_id: str, expected_revision: int
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = self._experiment(connection, experiment_id, account_id)
            self._check_revision(row, expected_revision, "EXPERIMENT_REVISION_CONFLICT")
            if row["state"] != "DRAFT":
                raise ConflictError("EXPERIMENT_NOT_DRAFT")
            now = utc_now()
            connection.execute(
                """
                UPDATE m4_experiments
                SET state = 'FROZEN', revision = revision + 1,
                    frozen_at = ?, updated_at = ?
                WHERE experiment_id = ?
                """,
                (now, now, experiment_id),
            )
            return self._experiment_public(
                self._experiment(connection, experiment_id, account_id)
            )

    def create_participant(
        self,
        *,
        experiment_id: str,
        participant_id: str,
        account_id: str,
        purpose: str,
        prior_ai_familiarity: str,
        prior_product_experience: str,
        task_category: str,
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            experiment = self._experiment(connection, experiment_id, account_id)
            if experiment["state"] != "FROZEN":
                raise ConflictError("EXPERIMENT_NOT_FROZEN")
            if purpose not in _ALLOWED_PURPOSES:
                raise ConflictError("PARTICIPANT_PURPOSE_INVALID")
            participant_id = _required_text(participant_id, "PARTICIPANT_ID_REQUIRED")
            values = (
                participant_id,
                experiment_id,
                account_id,
                purpose,
                _required_text(prior_ai_familiarity, "AI_FAMILIARITY_REQUIRED"),
                _required_text(prior_product_experience, "PRODUCT_EXPERIENCE_REQUIRED"),
                _required_text(task_category, "TASK_CATEGORY_REQUIRED"),
                utc_now(),
            )
            try:
                connection.execute(
                    """
                    INSERT INTO m4_participants (
                        participant_id, experiment_id, account_id, purpose,
                        prior_ai_familiarity, prior_product_experience,
                        task_category, state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'CREATED', ?, ?)
                    """,
                    (*values, values[-1]),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("PARTICIPANT_EXISTS") from exc
            row = connection.execute(
                "SELECT * FROM m4_participants WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()
            return dict(row)

    def _project_owner(self, connection: sqlite3.Connection, project_id: str) -> str:
        project = connection.execute(
            "SELECT status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None or project["status"] != "active":
            raise ConflictError("PROJECT_NOT_ACTIVE")
        row = connection.execute(
            """
            SELECT owner_actor FROM project_intents
            WHERE project_id = ? ORDER BY revision DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None or not row["owner_actor"]:
            raise ConflictError("PROJECT_OWNER_REQUIRED")
        return row["owner_actor"]

    def create_session(
        self,
        *,
        session_id: str,
        experiment_id: str,
        participant_id: str,
        account_id: str,
        project_id: str,
        condition: str,
        assignment_rule_version: str,
        condition_version: str,
        source_commit: str,
        deployment_id: str,
    ) -> dict[str, Any]:
        if condition not in _ALLOWED_CONDITIONS:
            raise ConflictError("SESSION_CONDITION_INVALID")
        with self.db.connect() as connection:
            experiment = self._experiment(connection, experiment_id, account_id)
            if experiment["state"] != "FROZEN":
                raise ConflictError("EXPERIMENT_NOT_FROZEN")
            participant = connection.execute(
                "SELECT * FROM m4_participants WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()
            if participant is None:
                raise KeyError("M4_PARTICIPANT_NOT_FOUND")
            if participant["account_id"] != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
            if participant["experiment_id"] != experiment_id:
                raise ConflictError("PARTICIPANT_EXPERIMENT_MISMATCH")
            if self._project_owner(connection, project_id) != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
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
                        _required_text(session_id, "SESSION_ID_REQUIRED"),
                        experiment_id,
                        participant_id,
                        account_id,
                        project_id,
                        condition,
                        _required_text(assignment_rule_version, "ASSIGNMENT_RULE_VERSION_REQUIRED"),
                        _required_text(condition_version, "CONDITION_VERSION_REQUIRED"),
                        _required_text(source_commit, "SOURCE_COMMIT_REQUIRED"),
                        _required_text(deployment_id, "DEPLOYMENT_ID_REQUIRED"),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConflictError("SESSION_EXISTS") from exc
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return self._session_public(row)

    @staticmethod
    def _session_public(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def get_session(self, *, session_id: str, account_id: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            self._check_account(row, account_id)
            return self._session_public(row)

    def transition_session(
        self,
        *,
        session_id: str,
        account_id: str,
        target_state: str,
        expected_revision: int,
        withdrawal_reason: str | None = None,
    ) -> dict[str, Any]:
        if target_state not in _SESSION_STATES:
            raise ConflictError("INVALID_SESSION_STATE")
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            self._check_account(row, account_id)
            self._check_revision(row, expected_revision, "SESSION_REVISION_CONFLICT")
            if target_state not in _SESSION_TRANSITIONS.get(row["state"], set()):
                raise ConflictError("INVALID_SESSION_TRANSITION")
            if target_state == "WITHDRAWN":
                withdrawal_reason = _required_text(
                    withdrawal_reason or "", "WITHDRAWAL_REASON_REQUIRED"
                )
            now = utc_now()
            connection.execute(
                """
                UPDATE m4_sessions
                SET state = ?, revision = revision + 1,
                    updated_at = ?
                WHERE session_id = ?
                """,
                (target_state, now, session_id),
            )
            return self._session_public(
                connection.execute(
                    "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
            )
