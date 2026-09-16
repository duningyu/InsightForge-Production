"""Safe, descriptive reporting for the local IF Guide R1.1 M4 pilot."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.db import Database
from app.services.if_guide_m4 import M4EvaluationService


_PRIMARY = (
    "first_valid_action",
    "first_usable_flow_completion",
    "independent_acceptance",
    "evidence_backed_decision",
    "recovery",
)
_SECONDARY = (
    "critical_requirement_recall",
    "overall_requirement_recall",
    "requirement_alignment_precision",
    "checkability_coverage",
    "acceptance_coverage",
    "acceptance_testability",
    "unsupported_claim_rate",
    "actionability",
    "result_decision_traceability",
)
_UNSAFE_KEYS = {
    "raw_idea",
    "raw_transcript",
    "transcript",
    "content",
    "body",
    "full_text",
    "private_artifact_body",
    "credentials",
    "api_key",
    "token",
}


def _json_object(raw: Any) -> Mapping[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _metric_summary(payload: Mapping[str, Any], group: str, names: tuple[str, ...]) -> dict[str, Any]:
    values = payload.get(group)
    if not isinstance(values, Mapping):
        return {}
    result: dict[str, Any] = {}
    for name in names:
        item = values.get(name)
        if not isinstance(item, Mapping):
            continue
        result[name] = {
            key: item[key]
            for key in ("numerator", "denominator", "value", "status")
            if key in item and isinstance(item[key], (int, float, str))
        }
    return result


class M4ReportingService:
    """Build owner-scoped reports without exposing artifact or participant bodies."""

    def __init__(self, database: Database):
        self.database = database

    @classmethod
    def reject_unsafe_fields(cls, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).lower() in _UNSAFE_KEYS:
                    raise ValueError(f"UNSAFE_REPORT_FIELD:{key}")
                cls.reject_unsafe_fields(child)
        elif isinstance(value, list):
            for child in value:
                cls.reject_unsafe_fields(child)

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for row in rows:
            value = row[key]
            bucket = result.setdefault(
                value,
                {
                    "session_count": 0,
                    "comparable_session_count": 0,
                    "completed_count": 0,
                    "withdrawn_count": 0,
                    "incomplete_count": 0,
                    "integrity_fail_count": 0,
                },
            )
            bucket["session_count"] += 1
            if not row["version_split"]:
                bucket["comparable_session_count"] += 1
            if row["outcome"] == "COMPLETED":
                bucket["completed_count"] += 1
            elif row["outcome"] == "WITHDRAWN":
                bucket["withdrawn_count"] += 1
            elif row["outcome"] in {"OPERATIONAL_INCOMPLETE", "QUALITY_INCOMPLETE"}:
                bucket["incomplete_count"] += 1
            elif row["outcome"] == "INTEGRITY_FAIL":
                bucket["integrity_fail_count"] += 1
        return result

    def build_report(self, *, experiment_id: str, account_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            experiment = connection.execute(
                "SELECT * FROM m4_experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if experiment is None:
                raise KeyError("M4_EXPERIMENT_NOT_FOUND")
            if experiment["account_id"] != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
            rows = connection.execute(
                """
                SELECT s.*, p.purpose
                FROM m4_sessions AS s
                JOIN m4_participants AS p ON p.participant_id = s.participant_id
                WHERE s.experiment_id = ? AND s.account_id = ?
                ORDER BY s.created_at, s.session_id
                """,
                (experiment_id, account_id),
            ).fetchall()
            session_reports: list[dict[str, Any]] = []
            for row in rows:
                quality = connection.execute(
                    """
                    SELECT quality_evaluation_id, quality_layer, quality_revision,
                           status, metric_payload
                    FROM real_idea_quality_evaluations
                    WHERE evaluation_scope = 'IF_GUIDE_M4'
                      AND artifact_type = 'M4_SESSION' AND artifact_id = ?
                    ORDER BY quality_revision DESC, created_at DESC
                    LIMIT 1
                    """,
                    (row["session_id"],),
                ).fetchone()
                quality_payload = _json_object(quality["metric_payload"]) if quality else {}
                outcome = row["outcome_classification"] or row["state"]
                session_reports.append(
                    {
                        "session_id": row["session_id"],
                        "participant_id": row["participant_id"],
                        "project_id": row["project_id"],
                        "purpose": row["purpose"],
                        "condition": row["condition"],
                        "condition_version": row["condition_version"],
                        "state": row["state"],
                        "outcome": outcome,
                        "version_split": bool(row["version_split"]),
                        "revision": row["revision"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "failure_classification": (
                            "VERSION_SPLIT" if row["version_split"] else None
                        ),
                        "primary_metrics": _metric_summary(
                            quality_payload, "primary_metrics", _PRIMARY
                        ),
                        "secondary_metrics": _metric_summary(
                            quality_payload, "secondary_metrics", _SECONDARY
                        ),
                        "quality_status": quality["status"] if quality else None,
                        "quality_evaluation_id": (
                            quality["quality_evaluation_id"] if quality else None
                        ),
                        "elapsed_ms": row["elapsed_ms"],
                        "time_to_first_valid_action_ms": row["time_to_first_valid_action_ms"],
                        "time_to_first_usable_flow_ms": row["time_to_first_usable_flow_ms"],
                        "edit_count": row["edit_count"],
                        "support_minutes": row["support_minutes"],
                        "provider_calls": row["provider_calls"],
                        "provider_cost": row["provider_cost"],
                        "retry_count": row["retry_count"],
                        "timeout_count": row["timeout_count"],
                        "severe_error_count": row["severe_error_count"],
                        "recovery_attempts": row["recovery_attempts"],
                    }
                )

        comparable = [row for row in session_reports if not row["version_split"]]
        report = {
            "safe_only": True,
            "report_version": "if-guide-m4-report-v1",
            "experiment_id": experiment_id,
            "experiment_state": experiment["state"],
            "spec_version": experiment["spec_version"],
            "source_commit": experiment["source_commit"],
            "deployment_id": experiment["deployment_id"],
            "sessions": session_reports,
            "aggregates": {
                "session_count": len(session_reports),
                "comparable_session_count": len(comparable),
                "by_condition": self._aggregate(session_reports, "condition"),
                "by_purpose": self._aggregate(session_reports, "purpose"),
            },
            "missing_or_incomplete": [
                row["session_id"]
                for row in session_reports
                if row["outcome"] in {"WITHDRAWN", "OPERATIONAL_INCOMPLETE", "QUALITY_INCOMPLETE"}
                or row["quality_status"] is None
            ],
            "version_splits": [
                row["session_id"] for row in session_reports if row["version_split"]
            ],
            "integrity_failures": [
                row["session_id"]
                for row in session_reports
                if row["outcome"] == "INTEGRITY_FAIL"
            ],
            "claim_boundary": {
                "aggregate_type": "DESCRIPTIVE_ONLY",
                "statistical_significance": "NOT_CLAIMED",
                "automatic_winner": "NOT_PROVIDED",
            },
        }
        self.reject_unsafe_fields(report)
        return report

    def export_json(self, *, experiment_id: str, account_id: str) -> str:
        return json.dumps(
            self.build_report(experiment_id=experiment_id, account_id=account_id),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def build_release_gate_report(self, *, experiment_id: str, account_id: str) -> dict[str, Any]:
        """Return a safe descriptive gate report; it never authorizes release."""
        report = self.build_report(experiment_id=experiment_id, account_id=account_id)
        report["release_gate"] = {
            "safe_only": True,
            "status": "RELEASE_NOT_AUTHORIZED",
            "hard_gate_violations": {
                "cross_account_project_leakage": [],
                "false_authorized_run": [],
                "unauthorized_external_action": [],
                "duplicate_paid_dispatch": [],
                "wrong_exact_version_binding": [],
                "severe_unsupported_verified_fact": [],
            },
            "integrity_failures": report["integrity_failures"],
            "quality_summary": report["aggregates"],
            "missing_or_incomplete": report["missing_or_incomplete"],
            "version_splits": report["version_splits"],
            "claim_boundary": {
                "aggregate_type": "DESCRIPTIVE_ONLY",
                "automatic_release": "NOT_PROVIDED",
                "statistical_significance": "NOT_CLAIMED",
            },
        }
        self.reject_unsafe_fields(report)
        return report
