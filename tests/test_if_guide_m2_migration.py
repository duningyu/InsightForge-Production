from __future__ import annotations


def test_m2_schema_is_installed_and_versioned(db):
    with db.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"build_slices", "prototype_tasks", "if_guide_m2_schema_meta"} <= tables
        version = connection.execute(
            "SELECT version FROM if_guide_m2_schema_meta WHERE singleton=1"
        ).fetchone()[0]
        assert version >= 1


def test_m2_quality_ledger_accepts_project_local_artifacts(db):
    with db.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(real_idea_quality_evaluations)"
            ).fetchall()
        }
    assert {"owner_actor", "artifact_id", "artifact_revision", "evaluation_scope"} <= columns


def test_m2_tables_have_revision_and_project_ownership_columns(db):
    with db.connect() as connection:
        for table in ("build_slices", "prototype_tasks"):
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert {"project_id", "owner_actor", "revision", "status", "created_at", "updated_at"} <= columns
