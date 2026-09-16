"""IF Guide R1.1 M4 controlled-evaluation schema."""

from __future__ import annotations

import sqlite3

from app.migrations.if_guide_m2 import _rebuild_quality_ledger


VERSION = 3
_VERSION_TABLE = "if_guide_m4_schema_meta"


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


EXPERIMENTS_SQL = """
CREATE TABLE IF NOT EXISTS m4_experiments (
    experiment_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    condition_definitions_json TEXT NOT NULL CHECK(json_valid(condition_definitions_json)),
    assignment_rule TEXT NOT NULL,
    metric_versions_json TEXT NOT NULL CHECK(json_valid(metric_versions_json)),
    rubric_versions_json TEXT NOT NULL CHECK(json_valid(rubric_versions_json)),
    threshold_policy_json TEXT NOT NULL CHECK(json_valid(threshold_policy_json)),
    operator_assistance_policy_json TEXT NOT NULL CHECK(json_valid(operator_assistance_policy_json)),
    state TEXT NOT NULL CHECK(state IN ('DRAFT', 'FROZEN', 'VERSION_SPLIT', 'CLOSED')),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    frozen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_m4_experiments_account
    ON m4_experiments(account_id, created_at DESC);
"""


PARTICIPANTS_SQL = """
CREATE TABLE IF NOT EXISTS m4_participants (
    participant_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES m4_experiments(experiment_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK(purpose IN ('LEARNING', 'PERSONAL_USE', 'FOR_OTHERS')),
    prior_ai_familiarity TEXT NOT NULL,
    prior_product_experience TEXT NOT NULL,
    task_category TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'CREATED', 'ASSIGNED', 'READY', 'IN_PROGRESS', 'COMPLETED',
        'WITHDRAWN', 'OPERATIONAL_INCOMPLETE', 'QUALITY_INCOMPLETE', 'FINALIZED'
    )),
    withdrawal_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(experiment_id, participant_id)
);
CREATE INDEX IF NOT EXISTS idx_m4_participants_experiment
    ON m4_participants(experiment_id, state, created_at);
"""


SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS m4_sessions (
    session_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES m4_experiments(experiment_id) ON DELETE CASCADE,
    participant_id TEXT NOT NULL REFERENCES m4_participants(participant_id) ON DELETE CASCADE,
    account_id TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    condition TEXT NOT NULL CHECK(condition IN (
        'STATIC_TEMPLATE', 'GENERAL_AI', 'INSIGHTFORGE_STATEFUL'
    )),
    assignment_rule_version TEXT NOT NULL,
    condition_version TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'CREATED', 'ASSIGNED', 'READY', 'IN_PROGRESS', 'COMPLETED',
        'WITHDRAWN', 'OPERATIONAL_INCOMPLETE', 'QUALITY_INCOMPLETE', 'FINALIZED'
    )),
    version_split INTEGER NOT NULL DEFAULT 0 CHECK(version_split IN (0, 1)),
    version_split_reason TEXT,
    outcome_classification TEXT CHECK(outcome_classification IN (
        'WITHDRAWN', 'OPERATIONAL_INCOMPLETE', 'QUALITY_INCOMPLETE',
        'COMPLETED', 'INTEGRITY_FAIL'
    )),
    elapsed_ms INTEGER,
    time_to_first_valid_action_ms INTEGER,
    time_to_first_usable_flow_ms INTEGER,
    edit_count INTEGER NOT NULL DEFAULT 0 CHECK(edit_count >= 0),
    support_minutes REAL NOT NULL DEFAULT 0 CHECK(support_minutes >= 0),
    provider_calls INTEGER NOT NULL DEFAULT 0 CHECK(provider_calls >= 0),
    provider_cost REAL NOT NULL DEFAULT 0 CHECK(provider_cost >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    timeout_count INTEGER NOT NULL DEFAULT 0 CHECK(timeout_count >= 0),
    severe_error_count INTEGER NOT NULL DEFAULT 0 CHECK(severe_error_count >= 0),
    recovery_attempts INTEGER NOT NULL DEFAULT 0 CHECK(recovery_attempts >= 0),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(experiment_id, participant_id)
);
CREATE INDEX IF NOT EXISTS idx_m4_sessions_experiment
    ON m4_sessions(experiment_id, state, created_at);
CREATE INDEX IF NOT EXISTS idx_m4_sessions_account
    ON m4_sessions(account_id, project_id, created_at);
"""


GOLD_ITEMS_SQL = """
CREATE TABLE IF NOT EXISTS m4_requirement_gold_items (
    gold_item_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES m4_sessions(session_id) ON DELETE CASCADE,
    participant_id TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    requirement_id TEXT NOT NULL,
    canonical_text TEXT NOT NULL CHECK(length(trim(canonical_text)) > 0),
    importance TEXT NOT NULL CHECK(importance IN ('CRITICAL', 'SECONDARY')),
    source TEXT NOT NULL CHECK(source IN ('RAW_IDEA', 'USER_CONFIRMED_BRIEF', 'USER_EDIT')),
    confirmed_by TEXT NOT NULL CHECK(confirmed_by = 'idea_provider'),
    participant_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(participant_confirmed IN (0, 1)),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    created_at TEXT NOT NULL,
    UNIQUE(session_id, requirement_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_m4_gold_items_session
    ON m4_requirement_gold_items(session_id, importance, revision);
"""


ANNOTATIONS_SQL = """
CREATE TABLE IF NOT EXISTS m4_quality_annotations (
    annotation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES m4_sessions(session_id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    artifact_ref TEXT NOT NULL,
    annotation_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    label TEXT NOT NULL,
    evaluator_role TEXT NOT NULL CHECK(evaluator_role IN (
        'PARTICIPANT', 'INDEPENDENT_REVIEWER', 'LLM_ASSIST', 'SYSTEM'
    )),
    adjudication_status TEXT NOT NULL CHECK(adjudication_status IN (
        'PENDING', 'ADJUDICATED', 'NOT_REQUIRED'
    )),
    evidence_hash TEXT,
    evidence_ref_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_ref_json)),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    created_at TEXT NOT NULL,
    UNIQUE(session_id, artifact_ref, target_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_m4_annotations_session
    ON m4_quality_annotations(session_id, annotation_type, created_at);
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
    """Apply the M4 schema inside the caller-owned transaction."""
    row = (
        connection.execute(
            "SELECT version FROM if_guide_m4_schema_meta WHERE singleton=1"
        ).fetchone()
        if _table_exists(connection, _VERSION_TABLE)
        else None
    )
    current = int(row[0]) if row is not None else 0
    if current >= VERSION:
        return

    connection.execute("SAVEPOINT if_guide_m4")
    try:
        _execute_script(connection, EXPERIMENTS_SQL)
        _execute_script(connection, PARTICIPANTS_SQL)
        _execute_script(connection, SESSIONS_SQL)
        _execute_script(connection, GOLD_ITEMS_SQL)
        _execute_script(connection, ANNOTATIONS_SQL)
        if current < 2:
            _rebuild_quality_ledger(connection)
        if current < 3 and _table_exists(connection, "m4_sessions"):
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(m4_sessions)").fetchall()
            }
            if "outcome_classification" not in columns:
                connection.execute(
                    "ALTER TABLE m4_sessions ADD COLUMN outcome_classification TEXT"
                )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS if_guide_m4_schema_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO if_guide_m4_schema_meta(singleton, version) VALUES (1, ?)",
            (VERSION,),
        )
        connection.execute("RELEASE SAVEPOINT if_guide_m4")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT if_guide_m4")
        connection.execute("RELEASE SAVEPOINT if_guide_m4")
        raise
