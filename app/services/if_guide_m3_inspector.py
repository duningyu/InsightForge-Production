"""Read-only, owner-scoped safe metadata for the IF Guide R1.1 M3 flow."""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.db import Database
from app.errors import ConflictError


_M3_METRICS = {
    "evidence_sufficiency",
    "review_accuracy",
    "result_decision_traceability",
    "unsupported_conclusion_rate",
    "recovery_specificity",
}


def _json_list(raw: Any) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _json_object(raw: Any) -> Mapping[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _safe_submission(row: Mapping[str, Any]) -> dict[str, Any]:
    claim = _json_object(row["execution_claim_json"])
    return {
        "submission_id": row["submission_id"],
        "project_id": row["project_id"],
        "task_id": row["task_id"],
        "task_revision": int(row["task_revision"]),
        "submission_kind": row["submission_kind"],
        "source_identity": row["source_identity"],
        "revision": int(row["revision"]),
        "submitted_by": row["submitted_by"],
        "created_at": row["created_at"],
        "description_present": bool(str(row["description"]).strip()),
        "attachment_count": len(_json_list(row["attachment_refs_json"])),
        "check_result_count": len(_json_list(row["check_results_json"])),
        "execution_claim_keys": sorted(str(key) for key in claim),
        "provider_dispatches": 0,
        "provider_transports": 0,
        "search_requests": 0,
    }


def _safe_review(row: Mapping[str, Any]) -> dict[str, Any]:
    check_items = _json_list(row["check_items_json"])
    evidence_ref_count = sum(
        len(item.get("evidence_refs") or [])
        for item in check_items
        if isinstance(item, Mapping) and isinstance(item.get("evidence_refs"), list)
    )
    return {
        "review_id": row["review_id"],
        "project_id": row["project_id"],
        "submission_id": row["submission_id"],
        "submission_revision": int(row["submission_revision"]),
        "task_id": row["task_id"],
        "task_revision": int(row["task_revision"]),
        "overall_status": row["overall_status"],
        "evidence_level": row["evidence_level"],
        "reviewer_role": row["reviewer_role"],
        "revision": int(row["revision"]),
        "evidence_hash": row["evidence_hash"],
        "created_at": row["created_at"],
        "known_unknown_count": len(_json_list(row["known_unknowns_json"])),
        "check_item_count": len(check_items),
        "evidence_ref_count": evidence_ref_count,
        "recommendation_present": bool(str(row["recommendation"]).strip()),
        "provider_dispatches": 0,
        "provider_transports": 0,
        "search_requests": 0,
    }


def _safe_recovery(row: Mapping[str, Any]) -> dict[str, Any]:
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
        "confirmed": bool(row["confirmed"]),
        "revision": int(row["card_revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "execution_state": row["execution_state"],
        "execution_revision": int(row["execution_revision"]),
        "provider_dispatches": 0,
        "provider_transports": 0,
        "search_requests": 0,
    }


def _safe_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": row["decision_id"],
        "project_id": row["project_id"],
        "source_submission_id": row["source_submission_id"],
        "source_review_id": row["source_review_id"],
        "decision": row["decision"],
        "confirmed": bool(row["confirmed"]),
        "confirmed_by": row["confirmed_by"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "rationale_present": bool(str(row["rationale"]).strip()),
        "recommendation_present": bool(str(row["recommendation"]).strip()),
        "remaining_unknown_count": len(_json_list(row["remaining_unknowns_json"])),
        "provider_dispatches": 0,
        "provider_transports": 0,
        "search_requests": 0,
    }


def _safe_quality(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = _json_object(row["metric_payload"])
    metrics = {
        key: payload[key]
        for key in _M3_METRICS
        if key in payload and isinstance(payload[key], (int, float))
    }
    return {
        "quality_evaluation_id": row["quality_evaluation_id"],
        "artifact_type": row["artifact_type"],
        "artifact_id": row["artifact_id"],
        "artifact_revision": row["artifact_revision"],
        "quality_layer": row["quality_layer"],
        "quality_revision": row["quality_revision"],
        "status": row["status"],
        "metrics": metrics,
        "input_manifest_sha256": row["input_manifest_sha256"],
        "evidence_manifest_sha256": row["evidence_manifest_sha256"],
        "policy_version": row["policy_version"],
        "evaluation_scope": row["evaluation_scope"],
    }


class IFGuideM3Inspector:
    """Recover M3 history without exposing user-entered bodies or mutating state."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _authorize(connection: Any, project_id: str, actor: str) -> None:
        project = connection.execute(
            "SELECT status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            raise KeyError("project not found")
        if project["status"] != "active":
            raise ValueError("project is not active")
        intent = connection.execute(
            "SELECT owner_actor FROM project_intents WHERE project_id = "
            "? ORDER BY revision DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if intent is None:
            raise ConflictError("INTENT_REQUIRED")
        if str(intent["owner_actor"]) != actor:
            raise PermissionError("project belongs to another actor")

    def inspect_project(self, project_id: str, *, actor: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            self._authorize(connection, project_id, actor)
            submissions = connection.execute(
                "SELECT * FROM action_submissions WHERE project_id = ? "
                "ORDER BY created_at, revision, submission_id",
                (project_id,),
            ).fetchall()
            reviews = connection.execute(
                "SELECT * FROM action_reviews WHERE project_id = ? "
                "ORDER BY created_at, revision, review_id",
                (project_id,),
            ).fetchall()
            recoveries = connection.execute(
                "SELECT * FROM first_action_cards WHERE project_id = ? "
                "AND kind = 'RECOVERY' ORDER BY created_at, card_revision, task_id",
                (project_id,),
            ).fetchall()
            decisions = connection.execute(
                "SELECT * FROM decision_records WHERE project_id = ? "
                "ORDER BY created_at, revision, decision_id",
                (project_id,),
            ).fetchall()
            quality = connection.execute(
                "SELECT quality_evaluation_id, artifact_type, artifact_id, "
                "artifact_revision, quality_layer, quality_revision, status, "
                "metric_payload, input_manifest_sha256, evidence_manifest_sha256, "
                "policy_version, evaluation_scope FROM real_idea_quality_evaluations "
                "WHERE project_id = ? AND evaluation_scope = 'IF_GUIDE_M3' "
                "ORDER BY artifact_type, artifact_revision, quality_revision, created_at",
                (project_id,),
            ).fetchall()

        return {
            "safe_only": True,
            "project_id": project_id,
            "submissions": [_safe_submission(row) for row in submissions],
            "reviews": [_safe_review(row) for row in reviews],
            "recoveries": [_safe_recovery(row) for row in recoveries],
            "decisions": [_safe_decision(row) for row in decisions],
            "quality_evaluations": [_safe_quality(row) for row in quality],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }

    def reviews_for_submission(
        self, project_id: str, submission_id: str, *, actor: str
    ) -> dict[str, Any]:
        result = self.inspect_project(project_id, actor=actor)
        return {
            "safe_only": True,
            "project_id": project_id,
            "submission_id": submission_id,
            "reviews": [
                review
                for review in result["reviews"]
                if review["submission_id"] == submission_id
            ],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }

    def recovery_for_task(
        self, project_id: str, task_id: str, *, actor: str
    ) -> dict[str, Any]:
        result = self.inspect_project(project_id, actor=actor)
        return {
            "safe_only": True,
            "project_id": project_id,
            "task_id": task_id,
            "recoveries": [
                recovery
                for recovery in result["recoveries"]
                if recovery["parent_task_id"] == task_id
                or recovery["task_id"] == task_id
            ],
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }

    def history(self, project_id: str, *, actor: str) -> dict[str, Any]:
        result = self.inspect_project(project_id, actor=actor)
        events: list[dict[str, Any]] = []
        for category in ("submission", "review", "recovery", "decision", "quality"):
            key = {
                "submission": "submissions",
                "review": "reviews",
                "recovery": "recoveries",
                "decision": "decisions",
                "quality": "quality_evaluations",
            }[category]
            events.extend({"category": category, **item} for item in result[key])
        def _event_key(item: dict[str, Any]) -> tuple[str, int, str]:
            event_id = (
                item.get("submission_id")
                or item.get("review_id")
                or item.get("task_id")
                or item.get("decision_id")
                or item.get("quality_evaluation_id")
                or ""
            )
            return (
                str(item.get("created_at", "")),
                int(item.get("revision", item.get("quality_revision", 0)) or 0),
                str(event_id),
            )

        events.sort(key=_event_key)
        return {
            "safe_only": True,
            "project_id": project_id,
            "events": events,
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }


__all__ = ["IFGuideM3Inspector"]
