"""Read-only, safe metadata inspector for the IF Guide R1.1 M2 flow.

The inspector intentionally reads the database directly instead of calling
the M2 services.  Some service ``get_current`` methods perform stale-binding
invalidation as part of normal request handling; an inspector must not turn a
read into a mutation.  No artifact body or private input is projected.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.db import Database


_M2_METRICS = {
    "scope_recall",
    "scope_precision",
    "acceptance_coverage",
    "acceptance_testability",
    "constraint_preservation",
    "dependency_clarity",
    "unsupported_claim_rate",
}
_SAFE_PAYLOAD_KEYS = {
    "codes",
    "p0_violations",
    "p1_gaps",
    "evidence_ids",
    "evidence_kind",
    "rubric_version",
    "unknown_count",
}


def _json_object(raw: Any) -> Mapping[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _safe_quality(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = _json_object(row["metric_payload"])
    metrics = {
        key: payload[key]
        for key in _M2_METRICS
        if key in payload and isinstance(payload[key], (int, float))
    }
    safe: dict[str, Any] = {
        "quality_evaluation_id": row["quality_evaluation_id"],
        "artifact_type": row["artifact_type"],
        "artifact_id": row["artifact_id"],
        "artifact_revision": row["artifact_revision"],
        "quality_layer": row["quality_layer"],
        "quality_revision": row["quality_revision"],
        "status": row["status"],
        "metrics": metrics,
        "codes": [],
        "evidence_ids": [],
        "evidence_kind": None,
        "rubric_version": None,
        "unknown_count": payload.get("unknown_count", 0),
        "input_manifest_sha256": row["input_manifest_sha256"],
        "evidence_manifest_sha256": row["evidence_manifest_sha256"],
        "policy_version": row["policy_version"],
        "evaluation_scope": row["evaluation_scope"],
    }
    for key in _SAFE_PAYLOAD_KEYS:
        if key not in payload:
            continue
        value = payload[key]
        if key in {"codes", "p0_violations", "p1_gaps", "evidence_ids"}:
            if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                if key == "evidence_ids":
                    safe["evidence_ids"] = list(value)
                else:
                    safe["codes"].extend(value)
        elif key == "evidence_kind" and isinstance(value, str):
            safe[key] = value
        elif key == "rubric_version" and isinstance(value, str):
            safe[key] = value
        elif key == "unknown_count" and isinstance(value, int) and not isinstance(value, bool):
            safe[key] = value
    safe["codes"] = list(dict.fromkeys(safe["codes"]))
    return safe


class IFGuideM2Inspector:
    """Recover only non-sensitive M2 metadata without changing state."""

    def __init__(self, database: Database):
        self.database = database

    def inspect_project(self, project_id: str, *, actor: str | None = None) -> dict[str, Any]:
        if not self.database.path.exists():
            raise KeyError(project_id)

        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id, status, current_snapshot_id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise KeyError(project_id)

            intent = connection.execute(
                "SELECT intent_id, owner_actor, revision, confirmed_at "
                "FROM project_intents WHERE project_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            owner_matches = None if actor is None else bool(intent and intent["owner_actor"] == actor)

            snapshot = None
            if project["current_snapshot_id"]:
                snapshot = connection.execute(
                    "SELECT id, version, confirmed_at FROM project_snapshots WHERE id = ?",
                    (project["current_snapshot_id"],),
                ).fetchone()

            action = connection.execute(
                "SELECT task_id, intent_revision, card_revision, status, confirmed, confirmed_at "
                "FROM first_action_cards WHERE project_id = ? "
                "ORDER BY intent_revision DESC, card_revision DESC, created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()

            build_slice = connection.execute(
                "SELECT slice_id, intent_revision, snapshot_id, snapshot_version, revision, "
                "status, confirmed_at FROM build_slices WHERE project_id = ? "
                "ORDER BY revision DESC, updated_at DESC, slice_id DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            prototype_task = connection.execute(
                "SELECT task_id, slice_id, slice_revision, snapshot_id, snapshot_version, "
                "revision, status, confirmed_at FROM prototype_tasks WHERE project_id = ? "
                "ORDER BY revision DESC, updated_at DESC, task_id DESC LIMIT 1",
                (project_id,),
            ).fetchone()

            quality_rows = connection.execute(
                "SELECT quality_evaluation_id, artifact_type, artifact_id, artifact_revision, "
                "quality_layer, quality_revision, status, metric_payload, "
                "input_manifest_sha256, evidence_manifest_sha256, policy_version, "
                "evaluation_scope "
                "FROM real_idea_quality_evaluations "
                "WHERE project_id = ? AND evaluation_scope = 'IF_GUIDE_M2' "
                "ORDER BY artifact_type, artifact_revision, quality_revision, created_at",
                (project_id,),
            ).fetchall()

        return {
            "safe_only": True,
            "project_id": project["id"],
            "project_status": project["status"],
            "owner_actor_matches": owner_matches,
            "snapshot": (
                None
                if snapshot is None
                else {
                    "snapshot_id": snapshot["id"],
                    "version": snapshot["version"],
                    "confirmed": bool(snapshot["confirmed_at"]),
                }
            ),
            "intent": (
                None
                if intent is None
                else {
                    "intent_id": intent["intent_id"],
                    "revision": intent["revision"],
                    "confirmed": bool(intent["confirmed_at"]),
                    "owner_actor_matches": owner_matches,
                }
            ),
            "first_action": (
                None
                if action is None
                else {
                    "task_id": action["task_id"],
                    "intent_revision": action["intent_revision"],
                    "revision": action["card_revision"],
                    "status": action["status"],
                    "confirmed": bool(action["confirmed"]),
                }
            ),
            "build_slice": (
                None
                if build_slice is None
                else {
                    "slice_id": build_slice["slice_id"],
                    "intent_revision": build_slice["intent_revision"],
                    "snapshot_id": build_slice["snapshot_id"],
                    "snapshot_version": build_slice["snapshot_version"],
                    "revision": build_slice["revision"],
                    "status": build_slice["status"],
                    "confirmed": build_slice["status"] == "CONFIRMED",
                }
            ),
            "prototype_task": (
                None
                if prototype_task is None
                else {
                    "task_id": prototype_task["task_id"],
                    "slice_id": prototype_task["slice_id"],
                    "slice_revision": prototype_task["slice_revision"],
                    "snapshot_id": prototype_task["snapshot_id"],
                    "snapshot_version": prototype_task["snapshot_version"],
                    "revision": prototype_task["revision"],
                    "status": prototype_task["status"],
                    "confirmed": prototype_task["status"] == "READY",
                }
            ),
            "quality_evaluations": [_safe_quality(row) for row in quality_rows],
        }
