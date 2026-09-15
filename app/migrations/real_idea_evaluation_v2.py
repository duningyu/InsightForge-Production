"""Canonical restricted budget-extension lifecycle migration."""

from __future__ import annotations

import sqlite3

from app.migrations import real_idea_evaluation_v1 as v1


VERSION = 2
_VERSION_TABLE = "real_idea_evaluation_schema_meta"
_STATE_CHECK = "CHECK(stateIN('UNBOUND_RESTRICTED','BOUND','RELEASED'))"


def apply(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        f"SELECT version FROM {_VERSION_TABLE} WHERE singleton = 1"
    ).fetchone()
    current = int(row[0]) if row is not None else 0
    if current > VERSION:
        return
    if current == VERSION:
        v1._validate_schema(connection, extension_state_check=_STATE_CHECK)
        return
    if current != 1:
        raise RuntimeError(f"unsupported real idea schema version for v2: {current}")

    connection.execute("SAVEPOINT real_idea_evaluation_v2")
    try:
        connection.execute("DROP TRIGGER trg_real_idea_budget_extension_audit_immutable")
        connection.execute("DROP TRIGGER trg_real_idea_budget_extension_no_delete")
        connection.execute("ALTER TABLE real_idea_budget_extensions RENAME TO real_idea_budget_extensions_v1")
        connection.execute(
            """
            CREATE TABLE real_idea_budget_extensions (
                extension_id TEXT PRIMARY KEY,
                authorized_credits INTEGER NOT NULL CHECK(authorized_credits > 0),
                state TEXT NOT NULL CHECK(state IN ('UNBOUND_RESTRICTED', 'BOUND', 'RELEASED')),
                created_at TEXT NOT NULL,
                bound_batch_id TEXT REFERENCES real_idea_batches(batch_id),
                released_at TEXT,
                created_by TEXT NOT NULL,
                UNIQUE(bound_batch_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO real_idea_budget_extensions(
                extension_id, authorized_credits, state, created_at,
                bound_batch_id, released_at, created_by
            )
            SELECT extension_id, authorized_credits,
                   CASE state WHEN 'AUTHORIZED' THEN 'UNBOUND_RESTRICTED' ELSE state END,
                   created_at, bound_batch_id, released_at, created_by
            FROM real_idea_budget_extensions_v1
            """
        )
        connection.execute("DROP TABLE real_idea_budget_extensions_v1")
        connection.execute(
            """
            CREATE TRIGGER trg_real_idea_budget_extension_audit_immutable
            BEFORE UPDATE ON real_idea_budget_extensions
            WHEN NEW.extension_id IS NOT OLD.extension_id
              OR NEW.authorized_credits IS NOT OLD.authorized_credits
              OR NEW.created_at IS NOT OLD.created_at
              OR NEW.created_by IS NOT OLD.created_by
            BEGIN
                SELECT RAISE(ABORT, 'real idea budget extension authorization is immutable');
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER trg_real_idea_budget_extension_no_delete
            BEFORE DELETE ON real_idea_budget_extensions
            BEGIN
                SELECT RAISE(ABORT, 'real idea budget extension authorization is immutable');
            END
            """
        )
        connection.execute(
            f"UPDATE {_VERSION_TABLE} SET version = ? WHERE singleton = 1", (VERSION,)
        )
        v1._validate_schema(connection, extension_state_check=_STATE_CHECK)
        connection.execute("RELEASE SAVEPOINT real_idea_evaluation_v2")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT real_idea_evaluation_v2")
        connection.execute("RELEASE SAVEPOINT real_idea_evaluation_v2")
        raise
