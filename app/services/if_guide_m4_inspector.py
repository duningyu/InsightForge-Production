"""Owner-scoped M4 metadata inspection with an explicit no-body contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.db import Database


_METRICS = {
    "first_valid_action",
    "first_usable_flow_completion",
    "independent_acceptance",
    "evidence_backed_decision",
    "recovery",
    "critical_requirement_recall",
    "overall_requirement_recall",
    "requirement_alignment_precision",
    "checkability_coverage",
    "acceptance_coverage",
    "acceptance_testability",
    "unsupported_claim_rate",
    "actionability",
    "result_decision_traceability",
}


def _json_object(raw: Any) -> Mapping[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _safe_metrics(raw: Any) -> dict[str, Any]:
    payload = _json_object(raw)
    result: dict[str, Any] = {}
    for group in ("primary_metrics", "secondary_metrics"):
        values = payload.get(group)
        if not isinstance(values, Mapping):
            continue
        for name, item in values.items():
            if name not in _METRICS or not isinstance(item, Mapping):
                continue
            result[name] = {
                key: item[key]
                for key in ("numerator", "denominator", "value", "status")
                if key in item and isinstance(item[key], (int, float, str))
            }
    return result


class M4InspectorService:
    """Read M4 IDs, states, hashes, revisions and counts; never return bodies."""

    def __init__(self, database: Database):
        self.database = database

    def inspect_session(self, *, session_id: str, account_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT s.*, p.purpose, e.spec_version, e.source_commit AS experiment_source_commit,
                       e.deployment_id AS experiment_deployment_id, e.state AS experiment_state
                FROM m4_sessions AS s
                JOIN m4_participants AS p ON p.participant_id = s.participant_id
                JOIN m4_experiments AS e ON e.experiment_id = s.experiment_id
                WHERE s.session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError("M4_SESSION_NOT_FOUND")
            if row["account_id"] != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
            quality = connection.execute(
                """
                SELECT quality_evaluation_id, quality_layer, quality_revision,
                       status, input_manifest_sha256, evidence_manifest_sha256,
                       policy_version, metric_payload
                FROM real_idea_quality_evaluations
                WHERE evaluation_scope = 'IF_GUIDE_M4'
                  AND artifact_type = 'M4_SESSION' AND artifact_id = ?
                ORDER BY quality_revision DESC, created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            gold = connection.execute(
                """
                SELECT COUNT(*) AS item_count,
                       COALESCE(SUM(participant_confirmed), 0) AS confirmed_count,
                       MAX(revision) AS revision
                FROM m4_requirement_gold_items WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            annotation = connection.execute(
                "SELECT COUNT(*) AS annotation_count FROM m4_quality_annotations WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        result = {
            "safe_only": True,
            "session_id": row["session_id"],
            "experiment_id": row["experiment_id"],
            "participant_id": row["participant_id"],
            "participant_purpose": row["purpose"],
            "project_id": row["project_id"],
            "condition": row["condition"],
            "condition_version": row["condition_version"],
            "assignment_rule_version": row["assignment_rule_version"],
            "source_commit": row["source_commit"],
            "deployment_id": row["deployment_id"],
            "experiment_source_commit": row["experiment_source_commit"],
            "experiment_deployment_id": row["experiment_deployment_id"],
            "experiment_spec_version": row["spec_version"],
            "experiment_state": row["experiment_state"],
            "state": row["state"],
            "outcome": row["outcome_classification"],
            "version_split": bool(row["version_split"]),
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "operational": {
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
            },
            "quality": (
                {
                    "quality_evaluation_id": quality["quality_evaluation_id"],
                    "quality_layer": quality["quality_layer"],
                    "quality_revision": quality["quality_revision"],
                    "status": quality["status"],
                    "input_manifest_sha256": quality["input_manifest_sha256"],
                    "evidence_manifest_sha256": quality["evidence_manifest_sha256"],
                    "policy_version": quality["policy_version"],
                    "metrics": _safe_metrics(quality["metric_payload"]),
                }
                if quality
                else None
            ),
            "gold_set": {
                "item_count": gold["item_count"],
                "participant_confirmed_count": gold["confirmed_count"],
                "latest_revision": gold["revision"],
            },
            "annotation_count": annotation["annotation_count"],
            "provider_calls": row["provider_calls"],
            "provider_cost": row["provider_cost"],
            "retry_count": row["retry_count"],
            "timeout_count": row["timeout_count"],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }
        for forbidden in ("raw_idea", "content", "body", "private_artifact_body"):
            if forbidden in result:
                raise ValueError(f"UNSAFE_INSPECTOR_FIELD:{forbidden}")
        return result

    def inspect_experiment(self, *, experiment_id: str, account_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM m4_experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if row is None:
                raise KeyError("M4_EXPERIMENT_NOT_FOUND")
            if row["account_id"] != account_id:
                raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
            counts = connection.execute(
                "SELECT COUNT(*) AS session_count FROM m4_sessions WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return {
            "safe_only": True,
            "experiment_id": row["experiment_id"],
            "spec_version": row["spec_version"],
            "source_commit": row["source_commit"],
            "deployment_id": row["deployment_id"],
            "assignment_rule": row["assignment_rule"],
            "state": row["state"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "frozen_at": row["frozen_at"],
            "session_count": counts["session_count"],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }
