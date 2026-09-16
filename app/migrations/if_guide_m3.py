"""IF Guide R1.1 M3 result, review, recovery, and decision schema."""

from __future__ import annotations

import sqlite3


VERSION = 1
_VERSION_TABLE = "if_guide_m3_schema_meta"


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _add_column_if_missing(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    if column not in _columns(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _extend_action_cards(connection: sqlite3.Connection) -> None:
    _add_column_if_missing(
        connection,
        "first_action_cards",
        "kind",
        "TEXT NOT NULL DEFAULT 'FIRST_ACTION' CHECK(kind IN ('FIRST_ACTION', 'RECOVERY'))",
    )
    _add_column_if_missing(connection, "first_action_cards", "parent_task_id", "TEXT")
    _add_column_if_missing(
        connection, "first_action_cards", "source_submission_id", "TEXT"
    )
    _add_column_if_missing(connection, "first_action_cards", "source_review_id", "TEXT")
    _add_column_if_missing(
        connection,
        "first_action_cards",
        "execution_state",
        "TEXT NOT NULL DEFAULT 'READY' CHECK(execution_state IN ('DRAFT', 'READY', 'IN_PROGRESS', 'SUBMITTED', 'CLOSED', 'PAUSED', 'NEEDS_REVISION'))",
    )
    _add_column_if_missing(
        connection,
        "first_action_cards",
        "execution_revision",
        "INTEGER NOT NULL DEFAULT 1 CHECK(execution_revision >= 1)",
    )


SUBMISSIONS_SQL = """
CREATE TABLE IF NOT EXISTS action_submissions (
    submission_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES first_action_cards(task_id),
    task_revision INTEGER NOT NULL CHECK(task_revision >= 1),
    submission_kind TEXT NOT NULL CHECK(submission_kind IN ('DONE', 'BLOCKED')),
    description TEXT NOT NULL CHECK(length(trim(description)) > 0),
    attachment_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(attachment_refs_json)),
    check_results_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(check_results_json)),
    execution_claim_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(execution_claim_json)),
    source_identity TEXT NOT NULL CHECK(source_identity IN (
        'USER_INPUT', 'MODEL_HYPOTHESIS', 'REAL_OBSERVATION',
        'SIMULATION', 'IMPLEMENTATION_EVIDENCE'
    )),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    submitted_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, task_id, task_revision, revision)
);

CREATE INDEX IF NOT EXISTS idx_action_submissions_project
    ON action_submissions(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_submissions_task
    ON action_submissions(task_id, task_revision, created_at DESC);
"""


REVIEWS_SQL = """
CREATE TABLE IF NOT EXISTS action_reviews (
    review_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    submission_id TEXT NOT NULL REFERENCES action_submissions(submission_id),
    submission_revision INTEGER NOT NULL CHECK(submission_revision >= 1),
    task_id TEXT NOT NULL REFERENCES first_action_cards(task_id),
    task_revision INTEGER NOT NULL CHECK(task_revision >= 1),
    check_items_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(check_items_json)),
    overall_status TEXT NOT NULL CHECK(overall_status IN (
        'PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE'
    )),
    known_unknowns_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(known_unknowns_json)),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN (
        'USER_REPORTED', 'ARTIFACT_CHECKED', 'AUTHORIZED_RUN'
    )),
    recommendation TEXT NOT NULL DEFAULT '',
    reviewer_role TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    evidence_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(submission_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_action_reviews_project
    ON action_reviews(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_reviews_submission
    ON action_reviews(submission_id, revision);
"""


DECISIONS_SQL = """
CREATE TABLE IF NOT EXISTS decision_records (
    decision_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_submission_id TEXT NOT NULL REFERENCES action_submissions(submission_id),
    source_review_id TEXT NOT NULL REFERENCES action_reviews(review_id),
    decision TEXT NOT NULL CHECK(decision IN (
        'CONTINUE', 'NARROW', 'CHANGE', 'STOP', 'FINISH'
    )),
    rationale TEXT NOT NULL CHECK(length(trim(rationale)) > 0),
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
    confirmed_by TEXT,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_decision_records_project
    ON decision_records(project_id, revision DESC);
"""


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        connection.execute(statement)


def apply(connection: sqlite3.Connection) -> None:
    """Apply M3 schema in the caller's transaction."""
    row = connection.execute(
        "SELECT version FROM if_guide_m3_schema_meta WHERE singleton=1"
    ).fetchone() if _table_exists(connection, _VERSION_TABLE) else None
    current = int(row[0]) if row is not None else 0
    if current >= VERSION:
        return

    connection.execute("SAVEPOINT if_guide_m3")
    try:
        _extend_action_cards(connection)
        _execute_script(connection, SUBMISSIONS_SQL)
        _execute_script(connection, REVIEWS_SQL)
        _execute_script(connection, DECISIONS_SQL)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS if_guide_m3_schema_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO if_guide_m3_schema_meta(singleton, version) VALUES (1, ?)",
            (VERSION,),
        )
        connection.execute("RELEASE SAVEPOINT if_guide_m3")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT if_guide_m3")
        connection.execute("RELEASE SAVEPOINT if_guide_m3")
        raise
