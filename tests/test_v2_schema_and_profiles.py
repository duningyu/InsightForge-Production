import sqlite3
from contextlib import closing

from app.config import Settings
from app.db import Database
from app.retrieval_profiles import get_retrieval_profile, list_retrieval_profiles


NEW_TABLES = {
    "guided_sessions",
    "guided_messages",
    "project_decisions",
    "retrieval_runs",
    "retrieval_hits",
    "document_claims",
    "claim_evidence_links",
    "handoff_runs",
}


def test_settings_default_to_v2():
    assert Settings().app_version == "3.0.0"


def test_fresh_database_contains_v2_tables_and_source_provenance_columns(tmp_path):
    db = Database(tmp_path / "fresh.sqlite3")
    db.init_schema()

    tables = {
        row["name"]
        for row in db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert NEW_TABLES <= tables

    columns = {
        row["name"] for row in db.fetch_all("PRAGMA table_info(sources)")
    }
    assert {
        "source_url",
        "publisher",
        "published_at",
        "captured_at",
        "authority_label",
        "authority_basis",
        "status",
        "metadata_json",
    } <= columns


def test_minimal_v1_database_is_upgraded_without_losing_project(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE sources (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                source_type TEXT NOT NULL,
                authority REAL NOT NULL,
                content TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO projects VALUES (
                'legacy_project', 'Legacy', 'kept', 'active',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
            );
            """
        )

    db = Database(path)
    db.init_schema()

    assert db.fetch_one("SELECT summary FROM projects WHERE id = ?", ("legacy_project",)) == {
        "summary": "kept"
    }
    columns = {row["name"] for row in db.fetch_all("PRAGMA table_info(sources)")}
    assert "authority_basis" in columns
    assert db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='retrieval_runs'"
    ) == {"name": "retrieval_runs"}


def test_retrieval_profiles_have_single_source_of_truth_and_manual_baseline_label():
    profiles = list_retrieval_profiles()
    assert {item["id"] for item in profiles} == {
        "quick_explore_v1",
        "balanced_traceable_v1",
        "thorough_review_v1",
        "document_generation_v1",
    }
    balanced = get_retrieval_profile("balanced_traceable_v1")
    assert balanced.top_k == 8
    assert balanced.weights == {"bm25": 0.55, "cosine": 0.30, "authority": 0.15}
    assert balanced.validation_status == "manual_baseline_not_frozen_best"
    assert "未通过冻结评测集证明最优" in balanced.selection_basis
