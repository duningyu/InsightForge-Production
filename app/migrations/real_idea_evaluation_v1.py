from __future__ import annotations

import sqlite3


VERSION = 1


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS real_idea_batches (
    batch_id TEXT PRIMARY KEY,
    batch_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    finalized_at TEXT,
    manifest_sha256 TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    completeness_contract_version TEXT NOT NULL,
    questionnaire_version TEXT NOT NULL,
    sample_count INTEGER NOT NULL CHECK(sample_count = 3),
    search_allowed INTEGER NOT NULL DEFAULT 0 CHECK(search_allowed = 0),
    provider_policy_version TEXT NOT NULL,
    batch_version_split INTEGER NOT NULL DEFAULT 0 CHECK(batch_version_split IN (0, 1)),
    failure_classification TEXT,
    safe_counts_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    CHECK(started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at),
    CHECK(finished_at IS NULL OR finalized_at IS NULL OR finalized_at >= finished_at)
);

CREATE TABLE IF NOT EXISTS real_idea_samples (
    sample_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES real_idea_batches(batch_id),
    sample_key TEXT NOT NULL,
    source_type TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id),
    raw_idea_sha256 TEXT NOT NULL,
    redaction_version TEXT NOT NULL,
    state TEXT NOT NULL,
    withdrawal_reason TEXT,
    brief_version_id TEXT,
    solutions_evaluation_id TEXT,
    selected_solution_id TEXT,
    snapshot_id TEXT REFERENCES project_snapshots(id),
    prd_version_id TEXT REFERENCES document_versions(id),
    techdoc_version_id TEXT REFERENCES document_versions(id),
    handoff_run_id TEXT,
    sample_manifest_sha256 TEXT NOT NULL,
    budget_allocation_id TEXT,
    created_at TEXT NOT NULL,
    terminal_at TEXT,
    terminal_reason TEXT,
    created_by TEXT NOT NULL,
    CHECK(sample_key IN ('REAL_IDEA_01', 'REAL_IDEA_02', 'REAL_IDEA_03')),
    UNIQUE(batch_id, sample_key),
    UNIQUE(project_id),
    UNIQUE(batch_id, sample_id),
    FOREIGN KEY (batch_id, budget_allocation_id)
        REFERENCES real_idea_budget_allocations(batch_id, allocation_id),
    FOREIGN KEY (brief_version_id) REFERENCES idea_briefs(id),
    FOREIGN KEY (solutions_evaluation_id) REFERENCES solution_runs(id),
    FOREIGN KEY (selected_solution_id) REFERENCES solution_candidates(id),
    FOREIGN KEY (handoff_run_id) REFERENCES handoff_runs(id)
);

CREATE TABLE IF NOT EXISTS real_idea_budget_allocations (
    allocation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES real_idea_batches(batch_id),
    authorized_total INTEGER NOT NULL CHECK(authorized_total >= 0),
    batch_earmark INTEGER NOT NULL CHECK(batch_earmark >= 0),
    sample_cap INTEGER NOT NULL CHECK(sample_cap >= 0),
    quickstart_cap INTEGER NOT NULL CHECK(quickstart_cap >= 0),
    solutions_cap INTEGER NOT NULL CHECK(solutions_cap >= 0),
    purpose TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    released_at TEXT,
    release_count INTEGER NOT NULL DEFAULT 0 CHECK(release_count IN (0, 1)),
    created_by TEXT NOT NULL,
    UNIQUE(batch_id),
    UNIQUE(batch_id, allocation_id)
);

CREATE TABLE IF NOT EXISTS real_idea_transport_reservations (
    reservation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES real_idea_batches(batch_id),
    sample_id TEXT NOT NULL REFERENCES real_idea_samples(sample_id),
    stage TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal = 1),
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('RESERVED', 'ATTEMPTED', 'RELEASED')),
    reserved_at TEXT NOT NULL,
    attempted_at TEXT,
    dispatch_id TEXT,
    transport_id TEXT,
    released_at TEXT,
    failure_classification TEXT,
    created_by TEXT NOT NULL,
    UNIQUE(batch_id, sample_id, stage, ordinal),
    FOREIGN KEY (batch_id, sample_id)
        REFERENCES real_idea_samples(batch_id, sample_id)
);

CREATE TABLE IF NOT EXISTS real_idea_feedback (
    feedback_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES real_idea_batches(batch_id),
    sample_id TEXT NOT NULL REFERENCES real_idea_samples(sample_id),
    stage TEXT NOT NULL,
    submitted_by TEXT NOT NULL CHECK(submitted_by = 'idea_provider'),
    submitted_at TEXT NOT NULL,
    accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
    score_payload TEXT NOT NULL CHECK(json_valid(score_payload)),
    raw_feedback_text TEXT,
    feedback_attestation INTEGER NOT NULL CHECK(feedback_attestation = 1),
    feedback_schema_version TEXT NOT NULL,
    created_by TEXT NOT NULL,
    FOREIGN KEY (batch_id, sample_id)
        REFERENCES real_idea_samples(batch_id, sample_id)
);

CREATE TABLE IF NOT EXISTS real_idea_annotations (
    annotation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES real_idea_batches(batch_id),
    sample_id TEXT NOT NULL REFERENCES real_idea_samples(sample_id),
    annotation_kind TEXT NOT NULL CHECK(annotation_kind IN ('requirement', 'claim', 'decision', 'inheritance')),
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    annotation_schema_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    input_sha256 TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    supersedes_annotation_id TEXT REFERENCES real_idea_annotations(annotation_id),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    UNIQUE(sample_id, annotation_kind, target_id, revision),
    FOREIGN KEY (batch_id, sample_id)
        REFERENCES real_idea_samples(batch_id, sample_id)
);

CREATE INDEX IF NOT EXISTS idx_real_idea_samples_batch
    ON real_idea_samples(batch_id);
CREATE INDEX IF NOT EXISTS idx_real_idea_reservations_sample
    ON real_idea_transport_reservations(sample_id, stage);
CREATE INDEX IF NOT EXISTS idx_real_idea_annotations_sample_kind
    ON real_idea_annotations(sample_id, annotation_kind);

CREATE TRIGGER IF NOT EXISTS trg_real_idea_batch_finalize_immutable
BEFORE UPDATE ON real_idea_batches
WHEN OLD.finalized_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'finalized real idea batch is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_batch_finalize_no_delete
BEFORE DELETE ON real_idea_batches
WHEN OLD.finalized_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'finalized real idea batch is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_batch_audit_immutable
BEFORE UPDATE ON real_idea_batches
WHEN NEW.created_at IS NOT OLD.created_at OR NEW.created_by IS NOT OLD.created_by
BEGIN
    SELECT RAISE(ABORT, 'real idea batch audit fields are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_sample_binding_immutable
BEFORE UPDATE ON real_idea_samples
WHEN (OLD.project_id IS NOT NEW.project_id)
  OR OLD.source_type IS NOT NEW.source_type
  OR OLD.raw_idea_sha256 IS NOT NEW.raw_idea_sha256
  OR OLD.redaction_version IS NOT NEW.redaction_version
  OR OLD.sample_manifest_sha256 IS NOT NEW.sample_manifest_sha256
  OR OLD.batch_id IS NOT NEW.batch_id
  OR OLD.sample_key IS NOT NEW.sample_key
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
BEGIN
    SELECT RAISE(ABORT, 'real idea sample binding or audit fields are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_feedback_immutable
BEFORE UPDATE ON real_idea_feedback
BEGIN
    SELECT RAISE(ABORT, 'real idea feedback is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_feedback_no_delete
BEFORE DELETE ON real_idea_feedback
BEGIN
    SELECT RAISE(ABORT, 'real idea feedback is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_annotation_immutable
BEFORE UPDATE ON real_idea_annotations
BEGIN
    SELECT RAISE(ABORT, 'real idea annotation is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_annotation_no_delete
BEFORE DELETE ON real_idea_annotations
BEGIN
    SELECT RAISE(ABORT, 'real idea annotation is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_reservation_identity_immutable
BEFORE UPDATE ON real_idea_transport_reservations
WHEN OLD.batch_id IS NOT NEW.batch_id
  OR OLD.sample_id IS NOT NEW.sample_id
  OR OLD.stage IS NOT NEW.stage
  OR OLD.ordinal IS NOT NEW.ordinal
  OR OLD.idempotency_key IS NOT NEW.idempotency_key
  OR OLD.reserved_at IS NOT NEW.reserved_at
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
BEGIN
    SELECT RAISE(ABORT, 'real idea reservation identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_allocation_audit_immutable
BEFORE UPDATE ON real_idea_budget_allocations
WHEN NEW.created_at IS NOT OLD.created_at OR NEW.created_by IS NOT OLD.created_by
BEGIN
    SELECT RAISE(ABORT, 'real idea allocation audit fields are immutable');
END;
"""


def _migration_statements() -> tuple[str, ...]:
    statements: list[str] = []
    pending: list[str] = []
    for line in MIGRATION_SQL.splitlines():
        pending.append(line)
        candidate = "\n".join(pending)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            pending = []
    if "\n".join(pending).strip():
        raise RuntimeError("incomplete real idea migration statement")
    return tuple(statements)


_REQUIRED_COLUMNS = {
    "real_idea_batches": {"batch_id", "batch_key", "finalized_at", "created_at", "created_by"},
    "real_idea_samples": {"sample_id", "batch_id", "sample_key", "project_id", "budget_allocation_id"},
    "real_idea_budget_allocations": {"allocation_id", "batch_id", "created_at", "created_by"},
    "real_idea_transport_reservations": {"reservation_id", "batch_id", "sample_id", "ordinal"},
    "real_idea_feedback": {"feedback_id", "batch_id", "sample_id", "feedback_attestation"},
    "real_idea_annotations": {"annotation_id", "batch_id", "sample_id", "annotation_kind", "payload_json"},
}


def _validate_schema(connection: sqlite3.Connection) -> None:
    for table, required in _REQUIRED_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not required <= columns:
            missing = ", ".join(sorted(required - columns))
            raise RuntimeError(f"real idea schema {table} is missing columns: {missing}")


def apply(connection: sqlite3.Connection) -> None:
    """Apply the additive Real Idea evaluation schema in the caller's transaction."""
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > VERSION:
        return
    if current == VERSION:
        _validate_schema(connection)
        return

    connection.execute("SAVEPOINT real_idea_evaluation_v1")
    try:
        for statement in _migration_statements():
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {VERSION}")
        _validate_schema(connection)
        connection.execute("RELEASE SAVEPOINT real_idea_evaluation_v1")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT real_idea_evaluation_v1")
        connection.execute("RELEASE SAVEPOINT real_idea_evaluation_v1")
        raise
