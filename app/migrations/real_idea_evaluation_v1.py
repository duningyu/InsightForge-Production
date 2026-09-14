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
    created_by TEXT NOT NULL
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
    UNIQUE(batch_id, sample_key),
    UNIQUE(project_id)
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
    UNIQUE(batch_id)
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
    UNIQUE(batch_id, sample_id, stage, ordinal)
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
    feedback_attestation INTEGER NOT NULL CHECK(feedback_attestation IN (0, 1)),
    feedback_schema_version TEXT NOT NULL,
    created_by TEXT NOT NULL
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
    UNIQUE(sample_id, annotation_kind, target_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_real_idea_samples_batch
    ON real_idea_samples(batch_id);
CREATE INDEX IF NOT EXISTS idx_real_idea_reservations_sample
    ON real_idea_transport_reservations(sample_id, stage);
CREATE INDEX IF NOT EXISTS idx_real_idea_annotations_sample_kind
    ON real_idea_annotations(sample_id, annotation_kind);
"""


def apply(connection: sqlite3.Connection) -> None:
    """Apply the additive Real Idea evaluation schema in the caller's transaction."""
    connection.executescript(MIGRATION_SQL)
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current < VERSION:
        connection.execute(f"PRAGMA user_version = {VERSION}")
