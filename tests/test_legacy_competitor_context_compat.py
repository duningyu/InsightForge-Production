"""Compatibility boundaries for document generations created before competitors."""

import json

import pytest

from app.services.example_projects import ExampleProjectSeeder
from app.services.legacy_migration import LegacyMigrationService
from app.services.loop import DocumentLoop
from app.db import utc_now


def _ensure_confirmed_project_snapshot(db):
    """Put the pre-competitor project into the normal 3.0 document precondition."""

    LegacyMigrationService(db).migrate_project("project_insightforge_demo")


def test_legacy_example_seeding_allows_missing_competitor_snapshot(db):
    """Canonical pre-competitor documents must remain seedable at startup."""

    ExampleProjectSeeder(db).seed()


def test_explicit_competitor_skip_allows_generation_without_snapshot(db):
    project_id = "project_insightforge_demo"
    _ensure_confirmed_project_snapshot(db)
    assert db.fetch_one(
        "SELECT current_competitor_snapshot_id FROM projects WHERE id=?",
        (project_id,),
    )["current_competitor_snapshot_id"] is None

    result = DocumentLoop(db).run(
        project_id,
        "prd",
        idempotency_key="compat-explicit-skip",
        require_snapshot=True,
        use_competitor_snapshot=False,
    )

    version = db.fetch_one(
        "SELECT competitor_snapshot_id FROM document_versions WHERE id=?",
        (result["version_id"],),
    )
    assert version["competitor_snapshot_id"] is None


def test_new_generation_with_competitor_context_requires_project_snapshot(db):
    project_id = "project_insightforge_demo"
    _ensure_confirmed_project_snapshot(db)
    now = utc_now()
    comparison_id = "compat-comparison-present"
    snapshot_id = "compat-snapshot-present"
    db.execute(
        """
        INSERT INTO competitor_comparisons(
            id, project_id, created_by, candidate_ids_json, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (comparison_id, project_id, "synthetic-owner", "[]", json.dumps({"competitors": []}), now),
    )
    db.execute(
        """
        INSERT INTO competitor_decision_snapshots(
            id, project_id, created_by, comparison_id, candidate_ids_json,
            content_json, content_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            project_id,
            "synthetic-owner",
            comparison_id,
            "[]",
            json.dumps({"decisions": []}),
            "compat-hash-present",
            now,
        ),
    )
    db.execute(
        "UPDATE projects SET current_competitor_snapshot_id=? WHERE id=?",
        (snapshot_id, project_id),
    )

    result = DocumentLoop(db).run(
        project_id,
        "prd",
        idempotency_key="compat-snapshot-present",
        require_snapshot=True,
        use_competitor_snapshot=True,
    )
    version = db.fetch_one(
        "SELECT competitor_snapshot_id FROM document_versions WHERE id=?",
        (result["version_id"],),
    )
    assert version["competitor_snapshot_id"] == snapshot_id


def test_new_generation_declaring_competitor_context_fails_closed_without_snapshot(db):
    _ensure_confirmed_project_snapshot(db)
    with pytest.raises(
        ValueError,
        match="current confirmed competitor snapshot is required",
    ):
        DocumentLoop(db).run(
            "project_insightforge_demo",
            "prd",
            idempotency_key="compat-snapshot-missing",
            require_snapshot=True,
            use_competitor_snapshot=True,
        )
