from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.services.beta_analytics import EVENTS, EVENT_PROPERTIES, _scan, _validate_values


INSTANCE_PATTERN = re.compile(r"^beta_[0-9]{3}$")
FUNNEL_STAGES = (
    "idea_submitted", "solutions_generated", "solution_selected",
    "snapshot_created", "evidence_added", "evidence_impact_viewed",
    "prd_generated", "handoff_exported", "beta_task_completed",
)
PARTICIPANT_EVENT_COLUMNS = (
    "idea_submitted", "solutions_generated", "solution_selected",
    "snapshot_created", "evidence_added", "evidence_impact_viewed",
    "prd_generated", "handoff_exported", "task_completed",
)
LEAK_MARKER = re.compile(r"UNIQUE_(?:IDEA|PRD|EVIDENCE|PROMPT|COMPLETION)(?:_|\b)", re.I)


class PrivacyViolation(RuntimeError):
    pass


def _read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return []
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()]


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator, "rate": _safe_rate(numerator, denominator)}


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_csv(path: Path, fields: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    field_names = list(fields)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=field_names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_safe(row.get(field, "")) for field in field_names})


def _scan_events(events: list[dict[str, Any]]) -> None:
    for event in events:
        try:
            properties = json.loads(event.get("properties_json") or "{}")
            event_name = str(event.get("event_name") or "")
            if event_name not in EVENTS or set(properties) - EVENT_PROPERTIES[event_name]:
                raise ValueError("event contract violation")
            _scan(properties)
            _validate_values(event_name, properties)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PrivacyViolation("METRICS_PRIVACY_VIOLATION") from exc
        candidate = f"{event.get('event_name', '')} {json.dumps(properties, ensure_ascii=False)}"
        if LEAK_MARKER.search(candidate):
            raise PrivacyViolation("METRICS_PRIVACY_VIOLATION")


def _discover(instances_root: Path) -> list[tuple[str, Path]]:
    if not instances_root.is_dir():
        raise FileNotFoundError(f"instances root not found: {instances_root}")
    discovered = []
    for child in sorted(instances_root.iterdir(), key=lambda item: item.name):
        database = child / "insightforge.db"
        if child.is_dir() and INSTANCE_PATTERN.fullmatch(child.name) and database.is_file():
            discovered.append((child.name, database))
    return discovered


def export_beta_metrics(instances_root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    instances_root, output_dir = Path(instances_root), Path(output_dir)
    instances = _discover(instances_root)
    if not instances:
        raise ValueError("NO_BETA_INSTANCES_FOUND")

    sessions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    feedback: list[dict[str, Any]] = []
    releases: set[str] = set()
    demo_excluded = qa_excluded = 0

    for instance_id, database in instances:
        with _read_only(database) as connection:
            instance_sessions = _rows(connection, "beta_sessions")
            instance_events = _rows(connection, "product_events")
            instance_feedback = _rows(connection, "beta_feedback")
            projects = {row["id"]: row for row in _rows(connection, "projects")}
        _scan_events(instance_events)
        for row in instance_sessions + instance_events + instance_feedback:
            release = row.get("beta_release_id")
            if release:
                releases.add(str(release))
        sessions.extend(instance_sessions)
        feedback.extend(instance_feedback)
        for event in instance_events:
            project = projects.get(event.get("project_id"))
            excluded = bool(project and int(project.get("exclude_from_beta_metrics") or 0))
            origin = str(project.get("project_origin") or "user") if project else "user"
            if event.get("project_id") and (excluded or origin in {"demo", "qa"}):
                if origin == "qa":
                    qa_excluded += 1
                else:
                    demo_excluded += 1
                continue
            events.append(event)

    if len(releases) > 1:
        raise ValueError("MIXED_BETA_RELEASE_IDS")
    release_id = next(iter(releases), "unknown")
    output_dir.mkdir(parents=True, exist_ok=True)

    sessions.sort(key=lambda row: (row["participant_id"], row["started_at"], row["id"]))
    events.sort(key=lambda row: (row["participant_id"], row["occurred_at"], row["id"]))
    feedback.sort(key=lambda row: (row["participant_id"], row["created_at"], row["id"]))
    sessions_by_participant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    events_by_participant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sessions:
        sessions_by_participant[row["participant_id"]].append(row)
    for row in events:
        events_by_participant[row["participant_id"]].append(row)

    participant_rows = []
    for participant_id in sorted(sessions_by_participant):
        participant_sessions = sessions_by_participant[participant_id]
        event_names = {row["event_name"] for row in events_by_participant.get(participant_id, [])}
        active_days = {_timestamp(row["started_at"]).date().isoformat() for row in participant_sessions}
        participant_rows.append({
            "participant_id": participant_id,
            "first_session_at": min(row["started_at"] for row in participant_sessions),
            "last_session_at": max(row["started_at"] for row in participant_sessions),
            "session_count": len(participant_sessions),
            "distinct_active_days": len(active_days),
            **{name: int(("beta_task_completed" if name == "task_completed" else name) in event_names) for name in PARTICIPANT_EVENT_COLUMNS},
        })
    _write_csv(
        output_dir / "beta_participants.csv",
        ("participant_id", "first_session_at", "last_session_at", "session_count", "distinct_active_days", *PARTICIPANT_EVENT_COLUMNS),
        participant_rows,
    )

    session_rows = []
    for row in sessions:
        duration = max(0, int((_timestamp(row["last_activity_at"]) - _timestamp(row["started_at"])).total_seconds()))
        session_rows.append({
            "participant_id": row["participant_id"], "session_id": row["id"],
            "started_at": row["started_at"], "last_activity_at": row["last_activity_at"],
            "duration_seconds": duration,
        })
    _write_csv(output_dir / "beta_sessions.csv", ("participant_id", "session_id", "started_at", "last_activity_at", "duration_seconds"), session_rows)

    feedback_rows = [{
        "participant_id": row["participant_id"], "project_stage": row["project_stage"],
        "rating": row["rating"], "feedback_type": row["feedback_type"],
        "comment": row["comment"], "created_at": row["created_at"],
    } for row in feedback]
    _write_csv(output_dir / "beta_feedback.csv", ("participant_id", "project_stage", "rating", "feedback_type", "comment", "created_at"), feedback_rows)

    stage_participants = {
        stage: {row["participant_id"] for row in events if row["event_name"] == stage}
        for stage in FUNNEL_STAGES
    }
    idea_count = len(stage_participants["idea_submitted"])
    funnel_rows = []
    previous_count: int | None = None
    for stage in FUNNEL_STAGES:
        count = len(stage_participants[stage])
        funnel_rows.append({
            "stage": stage,
            "participant_count": count,
            "conversion_from_previous": None if previous_count is None else _safe_rate(count, previous_count),
            "conversion_from_idea": _safe_rate(count, idea_count),
        })
        previous_count = count
    _write_csv(output_dir / "beta_funnel.csv", ("stage", "participant_count", "conversion_from_previous", "conversion_from_idea"), funnel_rows)

    ttfv_values: list[float] = []
    invalid_pairs = 0
    for participant_id, participant_events in events_by_participant.items():
        ideas = [_timestamp(row["occurred_at"]) for row in participant_events if row["event_name"] == "idea_submitted"]
        snapshots = [_timestamp(row["occurred_at"]) for row in participant_events if row["event_name"] == "snapshot_created"]
        if not ideas:
            continue
        first_idea = min(ideas)
        invalid_pairs += sum(1 for value in snapshots if value < first_idea)
        valid = [value for value in snapshots if value >= first_idea]
        if valid:
            ttfv_values.append((min(valid) - first_idea).total_seconds())

    generated = stage_participants["solutions_generated"]
    selected = stage_participants["solution_selected"]
    snapshots = stage_participants["snapshot_created"]
    evidence = stage_participants["evidence_added"]
    impact = stage_participants["evidence_impact_viewed"]
    prd = stage_participants["prd_generated"]
    completed = stage_participants["beta_task_completed"]
    return_users = sum(1 for row in participant_rows if row["distinct_active_days"] >= 2)
    feedback_type_counts = Counter(row["feedback_type"] for row in feedback)
    rating_distribution = Counter(str(row["rating"]) for row in feedback)
    summary = {
        "beta_release_id": release_id,
        "participant_count": len(sessions_by_participant),
        "ttfv_definition": "participant first idea_submitted to first snapshot_created at or after that idea",
        "median_time_to_first_value_seconds": statistics.median(ttfv_values) if ttfv_values else None,
        "ttfv_observation_count": len(ttfv_values),
        "ttfv_invalid_timestamp_pair_count": invalid_pairs,
        "return_rate_definition": "participant active on at least two distinct UTC calendar days",
        "metrics": {
            "idea_to_snapshot": _metric(len(snapshots), idea_count),
            "solution_adoption": _metric(len(selected), len(generated)),
            "snapshot_to_evidence": _metric(len(evidence), len(snapshots)),
            "evidence_impact_open": _metric(len(impact), len(evidence)),
            "prd_generation": _metric(len(prd), len(snapshots)),
            "task_completion": _metric(len(completed), idea_count),
            "return_rate": _metric(return_users, len(sessions_by_participant)),
        },
        "feedback_summary": {
            "feedback_count": len(feedback),
            "average_feedback_rating": (sum(int(row["rating"]) for row in feedback) / len(feedback)) if feedback else None,
            "feedback_type_counts": dict(sorted(feedback_type_counts.items())),
            "rating_distribution": dict(sorted(rating_distribution.items())),
        },
        "contains_user_submitted_feedback_text": False,
    }
    summary_path = output_dir / "beta_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report_names = ("beta_funnel.csv", "beta_participants.csv", "beta_sessions.csv", "beta_feedback.csv", "beta_summary.json")
    for name in report_names[:-1] + (report_names[-1],):
        if name != "beta_feedback.csv" and LEAK_MARKER.search((output_dir / name).read_text(encoding="utf-8-sig")):
            raise PrivacyViolation("METRICS_PRIVACY_VIOLATION")
    files = {
        name: {"sha256": hashlib.sha256((output_dir / name).read_bytes()).hexdigest()}
        for name in report_names
    }
    manifest = {
        "beta_release_id": release_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "participant_instance_count": len(instances),
        "active_participant_count": len(sessions_by_participant),
        "files": files,
        "privacy_scan_status": "PASS",
        "contains_user_submitted_feedback_text": bool(feedback),
        "feedback_access_classification": "researcher_controlled_not_for_publication",
        "demo_excluded_count": demo_excluded,
        "qa_excluded_count": qa_excluded,
    }
    (output_dir / "EXPORT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
