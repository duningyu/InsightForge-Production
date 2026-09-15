from __future__ import annotations

import sqlite3

import pytest

from app.db import utc_now
from app.services.real_idea_budget import (
    EXTENSION_CREDITS,
    EXTENSION_ID,
    RealIdeaBudgetService,
    ReservationStateError,
)


def _seed_batch(db, batch_id: str) -> None:
    now = utc_now()
    with db.connect() as connection:
        connection.execute(
            """
            INSERT INTO real_idea_batches(
                batch_id, batch_key, status, created_at, manifest_sha256,
                source_commit, deployment_id, model, prompt_hash, schema_hash,
                completeness_contract_version, questionnaire_version,
                sample_count, provider_policy_version, created_by
            ) VALUES (?, ?, 'CREATED', ?, 'manifest', 'source', 'deployment',
                      'model', 'prompt', 'schema', 'completeness', 'questionnaire',
                      3, 'policy', 'test')
            """,
            (batch_id, batch_id, now),
        )


def test_extension_starts_unbound_restricted_and_reports_restricted_accounting(db):
    budget = RealIdeaBudgetService(db, durable_budget=6)

    budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)

    with db.connect() as connection:
        state = connection.execute(
            "SELECT state FROM real_idea_budget_extensions WHERE extension_id = ?",
            (EXTENSION_ID,),
        ).fetchone()[0]
    assert state == "UNBOUND_RESTRICTED"

    summary = budget.accounting_summary()
    assert summary == {
        "authorized_total": 9,
        "general_spendable": 6,
        "restricted_unbound": 3,
        "bound_allocation": 0,
        "safe_ceiling": 5,
    }


def test_extension_binds_releases_and_cannot_rebind(db):
    budget = RealIdeaBudgetService(db, durable_budget=6)
    _seed_batch(db, "batch-1")
    _seed_batch(db, "batch-2")
    budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)

    budget.earmark_batch("batch-1", 6)
    with db.connect() as connection:
        assert tuple(connection.execute(
            "SELECT state, bound_batch_id FROM real_idea_budget_extensions WHERE extension_id = ?",
            (EXTENSION_ID,),
        ).fetchone()) == ("BOUND", "batch-1")

    with pytest.raises(ValueError, match="already bound"):
        budget.earmark_batch("batch-2", 6)

    budget.release_extension(EXTENSION_ID, "batch-1")
    with db.connect() as connection:
        assert tuple(connection.execute(
            "SELECT state FROM real_idea_budget_extensions WHERE extension_id = ?",
            (EXTENSION_ID,),
        ).fetchone()) == ("RELEASED",)

    with pytest.raises(ReservationStateError, match="released"):
        budget.release_extension(EXTENSION_ID, "batch-1")


def test_official_budget_extension_operator_is_visible_without_running_mutation(db, capsys):
    from scripts.stage_b_evaluation_inspect import main

    assert main(["--help"]) == 0
    help_output = capsys.readouterr().out
    assert "create-real-idea-budget-extension" in help_output

    assert main(["create-real-idea-budget-extension", "--help"]) == 0
    command_help = capsys.readouterr().out
    assert "REAL_IDEA_BATCH_01_EXT_01" in command_help

    with db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM real_idea_budget_extensions"
        ).fetchone()[0] == 0


def test_extension_inspection_exposes_safe_state_only(db):
    budget = RealIdeaBudgetService(db, durable_budget=6)
    budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)

    inspection = budget.inspect_extension()

    assert inspection == {
        "extension_id": EXTENSION_ID,
        "authorized_credits": 3,
        "state": "UNBOUND_RESTRICTED",
        "bound_batch_id": None,
    }


def test_v2_migration_preserves_old_extension_and_unrelated_data(tmp_path):
    from app.migrations import real_idea_evaluation_v1 as v1
    from app.migrations import real_idea_evaluation_v2 as v2

    path = tmp_path / "v1-to-v2.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(v1.MIGRATION_SQL)
        connection.execute(
            "INSERT INTO real_idea_evaluation_schema_meta(singleton, version) VALUES (1, 1)"
        )
        connection.execute(
            """
            INSERT INTO real_idea_budget_extensions(
                extension_id, authorized_credits, state, created_at, created_by
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (EXTENSION_ID, 3, "AUTHORIZED", "now", "legacy-test"),
        )
        connection.execute("CREATE TABLE migration_sentinel(value TEXT NOT NULL)")
        connection.execute("INSERT INTO migration_sentinel(value) VALUES ('preserve')")
        connection.execute("PRAGMA user_version = 37")

        v2.apply(connection)

        row = connection.execute(
            "SELECT state, bound_batch_id FROM real_idea_budget_extensions WHERE extension_id = ?",
            (EXTENSION_ID,),
        ).fetchone()
        assert tuple(row) == ("UNBOUND_RESTRICTED", None)
        assert connection.execute(
            "SELECT value FROM migration_sentinel"
        ).fetchone()[0] == "preserve"
        assert connection.execute(
            "SELECT version FROM real_idea_evaluation_schema_meta WHERE singleton = 1"
        ).fetchone()[0] == 2
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 37

        v2.apply(connection)
        assert connection.execute(
            "SELECT COUNT(*) FROM real_idea_budget_extensions"
        ).fetchone()[0] == 1
