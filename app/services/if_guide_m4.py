"""M4 controlled-evaluation experiment and session lifecycle services."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.db import utc_now
from app.errors import ConflictError
from app.services.if_guide_m4_conditions import (
    validate_condition_definition,
    validate_observed_accounting,
)


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
_OUTCOMES = {
    "WITHDRAWN",
    "OPERATIONAL_INCOMPLETE",
    "QUALITY_INCOMPLETE",
    "COMPLETED",
    "INTEGRITY_FAIL",
}
_VERSION_FIELDS = {
    "source_commit": "source_commit",
    "deployment_id": "deployment_id",
    "condition_definitions": "condition_definitions_json",
    "condition_definitions_json": "condition_definitions_json",
    "assignment_rule": "assignment_rule",
    "metric_versions": "metric_versions_json",
    "metric_versions_json": "metric_versions_json",
    "rubric_versions": "rubric_versions_json",
    "rubric_versions_json": "rubric_versions_json",
    "threshold_policy": "threshold_policy_json",
    "threshold_policy_json": "threshold_policy_json",
    "operator_assistance_policy": "operator_assistance_policy_json",
    "operator_assistance_policy_json": "operator_assistance_policy_json",
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
            definitions = _from_json(row["condition_definitions_json"])
            for condition, definition in definitions.items():
                try:
                    validate_condition_definition(
                        condition,
                        definition,
                        expected_source_commit=row["source_commit"]
                        if condition == "INSIGHTFORGE_STATEFUL" else None,
                        expected_deployment_id=row["deployment_id"]
                        if condition == "INSIGHTFORGE_STATEFUL" else None,
                        expected_rubric_versions=_from_json(row["rubric_versions_json"])
                        if condition == "INSIGHTFORGE_STATEFUL" else None,
                    )
                except ValueError as exc:
                    raise ConflictError(str(exc)) from exc
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
        result = dict(row)
        if "outcome_classification" in result:
            result["outcome"] = result["outcome_classification"]
        return result

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

    def record_operational_accounting(
        self,
        *,
        session_id: str,
        account_id: str,
        expected_revision: int,
        elapsed_ms: int = 0,
        time_to_first_valid_action_ms: int | None = None,
        time_to_first_usable_flow_ms: int | None = None,
        edit_count: int = 0,
        support_minutes: float = 0,
        provider_calls: int = 0,
        provider_cost: float = 0,
        retry_count: int = 0,
        timeout_count: int = 0,
        severe_error_count: int = 0,
        recovery_attempts: int = 0,
    ) -> dict[str, Any]:
        counters = {
            "elapsed_ms": elapsed_ms,
            "time_to_first_valid_action_ms": time_to_first_valid_action_ms,
            "time_to_first_usable_flow_ms": time_to_first_usable_flow_ms,
            "edit_count": edit_count,
            "support_minutes": support_minutes,
            "provider_calls": provider_calls,
            "provider_cost": provider_cost,
            "retry_count": retry_count,
            "timeout_count": timeout_count,
            "severe_error_count": severe_error_count,
            "recovery_attempts": recovery_attempts,
        }
        for name, value in counters.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                raise ConflictError(f"M4_ACCOUNTING_VALUE_INVALID:{name}")
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            self._check_account(row, account_id)
            self._check_revision(row, expected_revision, "SESSION_REVISION_CONFLICT")
            experiment = self._experiment(connection, row["experiment_id"], account_id)
            definitions = _from_json(experiment["condition_definitions_json"])
            definition = definitions[row["condition"]]
            try:
                validate_observed_accounting(
                    row["condition"], definition,
                    provider_calls=provider_calls, provider_cost=provider_cost,
                )
            except ValueError as exc:
                raise ConflictError(str(exc)) from exc
            now = utc_now()
            connection.execute(
                """
                UPDATE m4_sessions SET elapsed_ms = ?, time_to_first_valid_action_ms = ?,
                    time_to_first_usable_flow_ms = ?, edit_count = ?, support_minutes = ?,
                    provider_calls = ?, provider_cost = ?, retry_count = ?, timeout_count = ?,
                    severe_error_count = ?, recovery_attempts = ?, revision = revision + 1,
                    updated_at = ? WHERE session_id = ?
                """,
                (
                    elapsed_ms, time_to_first_valid_action_ms, time_to_first_usable_flow_ms,
                    edit_count, support_minutes, provider_calls, provider_cost, retry_count,
                    timeout_count, severe_error_count, recovery_attempts, now, session_id,
                ),
            )
            return self._session_public(
                connection.execute("SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)).fetchone()
            )

    def record_version_observation(
        self,
        *,
        experiment_id: str,
        account_id: str,
        observed_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare runtime metadata to the frozen experiment and split safely."""
        if not isinstance(observed_metadata, dict):
            raise ConflictError("VERSION_METADATA_INVALID")
        with self.db.connect() as connection:
            experiment = self._experiment(connection, experiment_id, account_id)
            if experiment["state"] not in {"FROZEN", "VERSION_SPLIT"}:
                raise ConflictError("EXPERIMENT_NOT_FROZEN")
            mismatches: list[str] = []
            for key, observed in observed_metadata.items():
                column = _VERSION_FIELDS.get(key)
                if column is None:
                    continue
                expected = experiment[column]
                if column.endswith("_json"):
                    observed_value = _json(observed)
                    expected_value = _json(_from_json(expected))
                else:
                    observed_value = str(observed)
                    expected_value = str(expected)
                if observed_value != expected_value:
                    mismatches.append(key)
            already_split = experiment["state"] == "VERSION_SPLIT"
            if mismatches and not already_split:
                reason = _json({"mismatches": sorted(mismatches)})
                now = utc_now()
                connection.execute(
                    """
                    UPDATE m4_experiments
                    SET state='VERSION_SPLIT', revision=revision+1, updated_at=?
                    WHERE experiment_id=?
                    """,
                    (now, experiment_id),
                )
                connection.execute(
                    """
                    UPDATE m4_sessions
                    SET version_split=1, version_split_reason=?, revision=revision+1,
                        updated_at=?
                    WHERE experiment_id=? AND version_split=0
                    """,
                    (reason, now, experiment_id),
                )
            return {
                "experiment_id": experiment_id,
                "version_split": bool(mismatches or already_split),
                "mismatches": sorted(mismatches),
                "state": "VERSION_SPLIT" if (mismatches or already_split) else experiment["state"],
            }

    def aggregateable_session(
        self, *, session_id: str, account_id: str
    ) -> dict[str, Any]:
        """Return a session only when it belongs to a non-split experiment."""
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            self._check_account(row, account_id)
            experiment = self._experiment(connection, row["experiment_id"], account_id)
            if row["version_split"] or experiment["state"] == "VERSION_SPLIT":
                raise ConflictError("EXPERIMENT_VERSION_SPLIT")
            return self._session_public(row)

    def finalize_session(
        self,
        *,
        session_id: str,
        account_id: str,
        expected_revision: int,
        outcome: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Classify and terminally finalize a session without fabricating quality."""
        if outcome not in _OUTCOMES:
            raise ConflictError("INVALID_OUTCOME_CLASSIFICATION")
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            self._check_account(row, account_id)
            self._check_revision(row, expected_revision, "SESSION_REVISION_CONFLICT")
            if row["state"] == "FINALIZED":
                raise ConflictError("SESSION_FINALIZED")
            if outcome != "COMPLETED":
                reason = _required_text(reason or "", "OUTCOME_REASON_REQUIRED")
            effective = outcome
            if outcome == "COMPLETED":
                quality = connection.execute(
                    """
                    SELECT status FROM real_idea_quality_evaluations
                    WHERE evaluation_scope='IF_GUIDE_M4' AND artifact_type='M4_SESSION'
                      AND artifact_id=? AND artifact_revision=? AND quality_layer='P1'
                    ORDER BY quality_revision DESC LIMIT 1
                    """,
                    (session_id, row["revision"]),
                ).fetchone()
                if quality is None or quality["status"] != "PASS":
                    effective = "QUALITY_INCOMPLETE"
                    reason = reason or "QUALITY_EVIDENCE_INCOMPLETE"
            now = utc_now()
            connection.execute(
                """
                UPDATE m4_sessions
                SET state='FINALIZED', outcome_classification=?,
                    withdrawal_reason=CASE WHEN ?='WITHDRAWN' THEN ? ELSE withdrawal_reason END,
                    version_split_reason=CASE WHEN ? IS NOT NULL THEN ? ELSE version_split_reason END,
                    revision=revision+1, updated_at=?
                WHERE session_id=?
                """,
                (effective, effective, reason, reason, reason, now, session_id),
            )
            return self._session_public(
                connection.execute(
                    "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
            )
