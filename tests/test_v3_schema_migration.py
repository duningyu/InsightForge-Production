from pathlib import Path
import sqlite3

import pytest

from app.db import Database

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "idea_briefs",
    "solution_runs",
    "solution_candidates",
    "project_claims",
    "project_claim_evidence_links",
    "decision_claim_links",
    "project_snapshots",
    "snapshot_claim_links",
    "snapshot_decision_links",
    "change_proposals",
    "artifact_dependencies",
    "artifact_health",
}


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def test_fresh_schema_contains_all_v3_tables(tmp_path):
    db = Database(tmp_path / "fresh.sqlite3")
    db.init_schema()
    assert EXPECTED_TABLES <= _tables(db.path)
    with sqlite3.connect(db.path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
    assert "current_snapshot_id" in columns


def test_v206_schema_migrates_additively_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            (ROOT / "tests/fixtures/v206_schema.sql").read_text(encoding="utf-8")
        )
        connection.execute(
            "INSERT INTO projects(id,title,summary,status,created_at,updated_at) "
            "VALUES('p1','Legacy','Old project','active','t','t')"
        )
    db = Database(path)
    db.init_schema()
    db.init_schema()
    assert EXPECTED_TABLES <= _tables(path)
    assert db.fetch_one("SELECT title FROM projects WHERE id='p1'") == {"title": "Legacy"}


def test_insert_audit_tx_participates_in_caller_transaction(tmp_path):
    db = Database(tmp_path / "audit.sqlite3")
    db.init_schema()

    with pytest.raises(RuntimeError, match="rollback sentinel"):
        with db.connect() as connection:
            db.insert_audit_tx(
                connection,
                actor="tester",
                action="transactional_write",
                entity_type="project",
                entity_id="p1",
                payload={"ok": True},
            )
            raise RuntimeError("rollback sentinel")

    assert db.fetch_all("SELECT * FROM audit_events") == []
