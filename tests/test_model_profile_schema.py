from __future__ import annotations

import sqlite3

from app.db import Database


def _columns(db: Database, table: str) -> set[str]:
    with db.connect() as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_model_profile_tables_have_non_secret_schema(tmp_path):
    db = Database(tmp_path / "profiles.sqlite3")
    db.init_schema()

    assert {row["name"] for row in db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {
        "model_profiles",
        "model_profile_revisions",
        "project_model_profiles",
    }
    assert _columns(db, "model_profiles") == {
        "id", "display_name", "provider", "protocol", "base_url", "model_id",
        "credential_ref", "enabled", "is_default", "capabilities_json",
        "capabilities_checked_at", "last_test_status", "last_tested_at",
        "last_live_test_status", "last_live_tested_at", "last_live_latency_ms",
        "last_live_error_code", "last_live_model_returned", "revision",
        "created_at", "updated_at",
    }
    assert not {column.lower() for column in _columns(db, "model_profiles")} & {
        "api_key", "secret", "masked_key", "masked_api_key",
    }
    assert not {column.lower() for column in _columns(db, "model_profile_revisions")} & {
        "api_key", "secret", "masked_key", "masked_api_key", "credential_ref",
    }


def test_schema_allows_service_controlled_default_switching(tmp_path):
    db = Database(tmp_path / "profiles.sqlite3")
    db.init_schema()
    now = "2026-01-01T00:00:00+00:00"
    rows = [
        ("p1", "One", "openai", "openai_chat_completions", "", "m1", None, 1, 1, now, now),
        ("p2", "Two", "deepseek", "openai_chat_completions", "", "m2", None, 1, 1, now, now),
    ]
    with db.connect() as connection:
        connection.executemany(
            """INSERT INTO model_profiles(
                id, display_name, provider, protocol, base_url, model_id,
                credential_ref, enabled, is_default, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    assert db.fetch_one("SELECT COUNT(*) AS count FROM model_profiles WHERE is_default = 1")["count"] == 2


def test_repeated_init_schema_preserves_profile_rows_and_migrates_old_db(tmp_path):
    path = tmp_path / "profiles.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO projects VALUES ('project-1')")
    connection.commit()
    connection.close()

    db = Database(path)
    db.init_schema()
    db.execute(
        """INSERT INTO model_profiles(
            id, display_name, provider, protocol, base_url, model_id,
            enabled, is_default, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("profile-1", "Profile", "custom", "openai_chat_completions", "", "model", 1, 1,
         "now", "now"),
    )
    db.execute(
        "INSERT INTO project_model_profiles(project_id, profile_id, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("project-1", "profile-1", 1, "now", "now"),
    )
    db.init_schema()

    assert db.fetch_one("SELECT display_name FROM model_profiles WHERE id = 'profile-1'")["display_name"] == "Profile"
    assert db.fetch_one("SELECT profile_id FROM project_model_profiles WHERE project_id = 'project-1'")["profile_id"] == "profile-1"
