from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.db import Database
from app.services.beta_metrics import PrivacyViolation, export_beta_metrics


RELEASE = "closed_beta_release_1"
BASE = "2026-08-30T08:00:00+00:00"


def _business_hash(db_path: Path) -> str:
    db = Database(db_path)
    payload = {}
    for table in ("projects", "beta_sessions", "product_events", "beta_feedback"):
        payload[table] = db.fetch_all(f"SELECT * FROM {table} ORDER BY rowid")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _instance(root: Path, participant: str) -> Database:
    directory = root / participant
    directory.mkdir(parents=True)
    db = Database(directory / "insightforge.db")
    db.init_schema()
    return db


def _session(db: Database, participant: str, sid: str, started: str, ended: str) -> None:
    db.execute(
        "INSERT INTO beta_sessions VALUES (?,?,?,?,?)",
        (sid, participant, RELEASE, started, ended),
    )


def _project(db: Database, pid: str, *, origin: str = "user", excluded: int = 0) -> None:
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at,project_origin,exclude_from_beta_metrics) VALUES (?,?,?,?,?,?,?,?)",
        (pid, "Title", "Summary", "active", BASE, BASE, origin, excluded),
    )


def _event(db: Database, participant: str, sid: str, name: str, when: str, *, project: str | None = None, props=None) -> None:
    defaults = {
        "idea_submitted": {"idea_length_bucket": "21_50"},
        "solutions_generated": {"solution_count": 3, "mechanisms": ["rule_based"]},
        "solution_selected": {"mechanism": "rule_based", "selection_strategy": "recommended"},
        "snapshot_created": {"snapshot_version": 1},
        "evidence_added": {"source_type": "user_input", "file_type": "txt", "size_bucket": "0_1kb"},
        "evidence_impact_viewed": {"impact_count": 1},
        "prd_generated": {"doc_type": "prd", "generation_status": "succeeded"},
        "handoff_exported": {"format": "zip", "handoff_type": "codex"},
    }
    count = db.fetch_one("SELECT COUNT(*) AS n FROM product_events")["n"]
    db.execute(
        "INSERT INTO product_events VALUES (?,?,?,?,?,?,?,?)",
        (f"event-{participant}-{count}", participant, sid, project, name, json.dumps(defaults.get(name, {}) if props is None else props), RELEASE, when),
    )


def _fixtures(root: Path) -> list[Path]:
    one = _instance(root, "beta_001")
    _session(one, "beta_001", "s1", BASE, "2026-08-30T08:10:00+00:00")
    _session(one, "beta_001", "s1b", "2026-08-31T09:00:00+00:00", "2026-08-31T09:05:00+00:00")
    _project(one, "user-1")
    _project(one, "demo-1", origin="demo")
    _project(one, "qa-1", origin="qa")
    _event(one, "beta_001", "s1", "snapshot_created", "2026-08-30T07:59:00+00:00", project="user-1")
    timeline = [
        ("idea_submitted", "2026-08-30T08:00:00+00:00"),
        ("idea_submitted", "2026-08-30T08:00:10+00:00"),
        ("solutions_generated", "2026-08-30T08:01:00+00:00"),
        ("solution_selected", "2026-08-30T08:01:30+00:00"),
        ("snapshot_created", "2026-08-30T08:02:00+00:00"),
        ("evidence_added", "2026-08-30T08:02:30+00:00"),
        ("evidence_impact_viewed", "2026-08-30T08:02:40+00:00"),
        ("prd_generated", "2026-08-30T08:03:20+00:00"),
        ("handoff_exported", "2026-08-30T08:04:10+00:00"),
        ("beta_task_completed", "2026-08-30T08:05:00+00:00"),
    ]
    for name, when in timeline:
        _event(one, "beta_001", "s1", name, when, project="user-1")
    _event(one, "beta_001", "s1", "prd_generated", "2026-08-30T08:06:00+00:00", project="demo-1")
    _event(one, "beta_001", "s1", "evidence_added", "2026-08-30T08:06:10+00:00", project="qa-1")
    one.execute(
        "INSERT INTO beta_feedback VALUES (?,?,?,?,?,?,?,?,?)",
        ("f1", "beta_001", "user-1", "snapshot", 5, "helpful", "=SUM(1,1) UNIQUE_FEEDBACK_COMMENT_ALLOWED", RELEASE, "2026-08-30T08:07:00+00:00"),
    )

    two = _instance(root, "beta_002")
    _session(two, "beta_002", "s2", "2026-08-30T10:00:00+00:00", "2026-08-30T10:02:00+00:00")
    _project(two, "user-2")
    _event(two, "beta_002", "s2", "idea_submitted", "2026-08-30T10:00:00+00:00", project="user-2")
    _event(two, "beta_002", "s2", "solutions_generated", "2026-08-30T10:01:00+00:00", project="user-2")

    three = _instance(root, "beta_003")
    _session(three, "beta_003", "s3", "2026-08-30T11:00:00+00:00", "2026-08-30T11:01:00+00:00")
    (root / "beta_004_bad").mkdir()
    return [one.path, two.path, three.path]


def _read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_schema_has_explicit_metrics_exclusion_metadata_and_seeds_demo_as_excluded(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.seed_demo_data()
    row = db.fetch_one("SELECT project_origin,exclude_from_beta_metrics FROM projects WHERE id='project_insightforge_demo'")
    assert row == {"project_origin": "demo", "exclude_from_beta_metrics": 1}


def test_export_exact_funnel_metrics_ttfv_feedback_and_return_rate(tmp_path):
    root, output = tmp_path / "instances", tmp_path / "export"
    _fixtures(root)
    manifest = export_beta_metrics(root, output)
    funnel = {row["stage"]: row for row in _read_csv(output / "beta_funnel.csv")}
    assert funnel["idea_submitted"] == {"stage": "idea_submitted", "participant_count": "2", "conversion_from_previous": "", "conversion_from_idea": "1.0"}
    assert funnel["snapshot_created"]["participant_count"] == "1"
    assert funnel["snapshot_created"]["conversion_from_idea"] == "0.5"
    assert funnel["beta_task_completed"]["participant_count"] == "1"
    summary = json.loads((output / "beta_summary.json").read_text(encoding="utf-8"))
    assert summary["participant_count"] == 3
    assert summary["median_time_to_first_value_seconds"] == 120.0
    assert summary["ttfv_observation_count"] == 1
    assert summary["ttfv_invalid_timestamp_pair_count"] == 1
    assert summary["metrics"]["idea_to_snapshot"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert summary["metrics"]["solution_adoption"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert summary["metrics"]["snapshot_to_evidence"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert summary["metrics"]["evidence_impact_open"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert summary["metrics"]["prd_generation"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert summary["metrics"]["task_completion"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert summary["metrics"]["return_rate"] == {"numerator": 1, "denominator": 3, "rate": pytest.approx(1 / 3)}
    assert summary["feedback_summary"] == {"feedback_count": 1, "average_feedback_rating": 5.0, "feedback_type_counts": {"helpful": 1}, "rating_distribution": {"5": 1}}
    assert "UNIQUE_FEEDBACK_COMMENT_ALLOWED" not in json.dumps(summary)
    assert manifest["participant_instance_count"] == 3
    assert manifest["active_participant_count"] == 3
    assert manifest["demo_excluded_count"] == 1
    assert manifest["qa_excluded_count"] == 1


def test_participant_session_fields_dedupe_and_feedback_csv_injection_protection(tmp_path):
    root, output = tmp_path / "instances", tmp_path / "operator-export"
    _fixtures(root)
    export_beta_metrics(root, output)
    participants = {row["participant_id"]: row for row in _read_csv(output / "beta_participants.csv")}
    assert list(participants["beta_001"]) == ["participant_id", "first_session_at", "last_session_at", "session_count", "distinct_active_days", "idea_submitted", "solutions_generated", "solution_selected", "snapshot_created", "evidence_added", "evidence_impact_viewed", "prd_generated", "handoff_exported", "task_completed"]
    assert participants["beta_001"]["session_count"] == "2"
    assert participants["beta_001"]["distinct_active_days"] == "2"
    assert participants["beta_001"]["idea_submitted"] == "1"
    assert participants["beta_003"]["idea_submitted"] == "0"
    sessions = _read_csv(output / "beta_sessions.csv")
    assert list(sessions[0]) == ["participant_id", "session_id", "started_at", "last_activity_at", "duration_seconds"]
    feedback = _read_csv(output / "beta_feedback.csv")
    assert feedback[0]["comment"].startswith("'=SUM")
    assert "UNIQUE_FEEDBACK_COMMENT_ALLOWED" in feedback[0]["comment"]
    for name in ("beta_funnel.csv", "beta_participants.csv", "beta_sessions.csv", "beta_summary.json"):
        assert "UNIQUE_FEEDBACK_COMMENT_ALLOWED" not in (output / name).read_text(encoding="utf-8-sig")


def test_export_is_read_only_and_manifest_hashes_fixed_five_reports(tmp_path):
    root, output = tmp_path / "instances", tmp_path / "export"
    paths = _fixtures(root)
    before = [_business_hash(path) for path in paths]
    manifest = export_beta_metrics(root, output)
    after = [_business_hash(path) for path in paths]
    assert before == after
    assert set(manifest["files"]) == {"beta_funnel.csv", "beta_participants.csv", "beta_sessions.csv", "beta_feedback.csv", "beta_summary.json"}
    assert all(len(info["sha256"]) == 64 for info in manifest["files"].values())
    assert manifest["privacy_scan_status"] == "PASS"
    assert manifest["contains_user_submitted_feedback_text"] is True
    assert (output / "EXPORT_MANIFEST.json").exists()


def test_zero_denominators_are_null(tmp_path):
    root, output = tmp_path / "instances", tmp_path / "export"
    db = _instance(root, "beta_001")
    _session(db, "beta_001", "s", BASE, BASE)
    export_beta_metrics(root, output)
    summary = json.loads((output / "beta_summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["idea_to_snapshot"]["rate"] is None
    funnel = _read_csv(output / "beta_funnel.csv")
    assert all(row["conversion_from_idea"] == "" for row in funnel)


def test_privacy_scanner_rejects_forbidden_event_payload(tmp_path):
    root, output = tmp_path / "instances", tmp_path / "export"
    db = _instance(root, "beta_001")
    _session(db, "beta_001", "s", BASE, BASE)
    _event(db, "beta_001", "s", "idea_submitted", BASE, props={"prompt": "UNIQUE_PROMPT_LEAK"})
    with pytest.raises(PrivacyViolation, match="METRICS_PRIVACY_VIOLATION"):
        export_beta_metrics(root, output)


def test_operator_cli_exports_to_explicit_output_directory_without_network(tmp_path):
    root, output = tmp_path / "instances", tmp_path / "operator-output"
    _fixtures(root)
    script = Path(__file__).resolve().parents[1] / "scripts" / "export_beta_metrics.py"
    result = subprocess.run(
        [sys.executable, str(script), "--instances-root", str(root), "--output-dir", str(output)],
        cwd=script.parents[1], capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["privacy_scan_status"] == "PASS"
    assert (output / "EXPORT_MANIFEST.json").is_file()
