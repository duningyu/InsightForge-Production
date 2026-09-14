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

CREATE TABLE IF NOT EXISTS real_idea_budget_extensions (
    extension_id TEXT PRIMARY KEY,
    authorized_credits INTEGER NOT NULL CHECK(authorized_credits > 0),
    state TEXT NOT NULL CHECK(state IN ('AUTHORIZED', 'BOUND', 'RELEASED')),
    created_at TEXT NOT NULL,
    bound_batch_id TEXT REFERENCES real_idea_batches(batch_id),
    released_at TEXT,
    created_by TEXT NOT NULL,
    UNIQUE(bound_batch_id)
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

CREATE TABLE IF NOT EXISTS real_idea_quality_evaluations (
    quality_evaluation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES real_idea_batches(batch_id),
    sample_id TEXT NOT NULL REFERENCES real_idea_samples(sample_id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    artifact_type TEXT NOT NULL CHECK(artifact_type IN ('SOLUTIONS', 'PRD', 'TECHDOC', 'HANDOFF')),
    artifact_version_id TEXT NOT NULL,
    selected_solution_id TEXT REFERENCES solution_candidates(id),
    snapshot_id TEXT REFERENCES project_snapshots(id),
    upstream_version_ids TEXT NOT NULL CHECK(json_valid(upstream_version_ids)),
    quality_layer TEXT NOT NULL CHECK(quality_layer IN ('P0', 'P1', 'P2')),
    quality_revision INTEGER NOT NULL CHECK(quality_revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('PASS', 'PARTIAL', 'FAIL')),
    metric_payload TEXT NOT NULL CHECK(json_valid(metric_payload)),
    input_manifest_sha256 TEXT NOT NULL,
    evidence_manifest_sha256 TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    quality_schema_version TEXT NOT NULL,
    evaluator_role TEXT NOT NULL CHECK(evaluator_role IN ('system', 'idea_provider', 'independent_reviewer', 'llm_assist')),
    created_at TEXT NOT NULL,
    supersedes_quality_evaluation_id TEXT REFERENCES real_idea_quality_evaluations(quality_evaluation_id),
    UNIQUE(batch_id, sample_id, artifact_type, artifact_version_id, quality_revision),
    UNIQUE(quality_evaluation_id, batch_id, sample_id),
    FOREIGN KEY (batch_id, sample_id)
        REFERENCES real_idea_samples(batch_id, sample_id)
);

CREATE TABLE IF NOT EXISTS real_idea_annotations (
    annotation_id TEXT PRIMARY KEY,
    quality_evaluation_id TEXT NOT NULL REFERENCES real_idea_quality_evaluations(quality_evaluation_id),
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
    FOREIGN KEY (quality_evaluation_id, batch_id, sample_id)
        REFERENCES real_idea_quality_evaluations(quality_evaluation_id, batch_id, sample_id),
    FOREIGN KEY (batch_id, sample_id)
        REFERENCES real_idea_samples(batch_id, sample_id)
);

CREATE INDEX IF NOT EXISTS idx_real_idea_samples_batch
    ON real_idea_samples(batch_id);
CREATE INDEX IF NOT EXISTS idx_real_idea_batches_batch_key
    ON real_idea_batches(batch_key);
CREATE INDEX IF NOT EXISTS idx_real_idea_samples_project
    ON real_idea_samples(project_id);
CREATE INDEX IF NOT EXISTS idx_real_idea_allocations_batch
    ON real_idea_budget_allocations(batch_id);
CREATE INDEX IF NOT EXISTS idx_real_idea_reservations_sample
    ON real_idea_transport_reservations(sample_id, stage);
CREATE INDEX IF NOT EXISTS idx_real_idea_feedback_sample
    ON real_idea_feedback(batch_id, sample_id, stage);
CREATE INDEX IF NOT EXISTS idx_real_idea_quality_batch
    ON real_idea_quality_evaluations(batch_id, sample_id);
CREATE INDEX IF NOT EXISTS idx_real_idea_quality_artifact_status
    ON real_idea_quality_evaluations(artifact_type, status);
CREATE INDEX IF NOT EXISTS idx_real_idea_quality_evidence
    ON real_idea_quality_evaluations(evidence_manifest_sha256);
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

CREATE TRIGGER IF NOT EXISTS trg_real_idea_quality_evaluation_immutable
BEFORE UPDATE ON real_idea_quality_evaluations
BEGIN
    SELECT RAISE(ABORT, 'real idea quality evaluation is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_quality_evaluation_no_delete
BEFORE DELETE ON real_idea_quality_evaluations
BEGIN
    SELECT RAISE(ABORT, 'real idea quality evaluation is immutable');
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

CREATE TRIGGER IF NOT EXISTS trg_real_idea_budget_extension_audit_immutable
BEFORE UPDATE ON real_idea_budget_extensions
WHEN NEW.extension_id IS NOT OLD.extension_id
  OR NEW.authorized_credits IS NOT OLD.authorized_credits
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.created_by IS NOT OLD.created_by
BEGIN
    SELECT RAISE(ABORT, 'real idea budget extension authorization is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_real_idea_budget_extension_no_delete
BEFORE DELETE ON real_idea_budget_extensions
BEGIN
    SELECT RAISE(ABORT, 'real idea budget extension authorization is immutable');
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


_EXPECTED_COLUMNS = {
    "real_idea_batches": {
        "batch_id", "batch_key", "status", "created_at", "started_at", "finished_at",
        "finalized_at", "manifest_sha256", "source_commit", "deployment_id", "model",
        "prompt_hash", "schema_hash", "completeness_contract_version", "questionnaire_version",
        "sample_count", "search_allowed", "provider_policy_version", "batch_version_split",
        "failure_classification", "safe_counts_json", "created_by",
    },
    "real_idea_samples": {
        "sample_id", "batch_id", "sample_key", "source_type", "project_id", "raw_idea_sha256",
        "redaction_version", "state", "withdrawal_reason", "brief_version_id",
        "solutions_evaluation_id", "selected_solution_id", "snapshot_id", "prd_version_id",
        "techdoc_version_id", "handoff_run_id", "sample_manifest_sha256", "budget_allocation_id",
        "created_at", "terminal_at", "terminal_reason", "created_by",
    },
    "real_idea_budget_allocations": {
        "allocation_id", "batch_id", "authorized_total", "batch_earmark", "sample_cap",
        "quickstart_cap", "solutions_cap", "purpose", "state", "created_at", "released_at",
        "release_count", "created_by",
    },
    "real_idea_budget_extensions": {
        "extension_id", "authorized_credits", "state", "created_at",
        "bound_batch_id", "released_at", "created_by",
    },
    "real_idea_transport_reservations": {
        "reservation_id", "batch_id", "sample_id", "stage", "ordinal", "idempotency_key",
        "state", "reserved_at", "attempted_at", "dispatch_id", "transport_id", "released_at",
        "failure_classification", "created_by",
    },
    "real_idea_feedback": {
        "feedback_id", "batch_id", "sample_id", "stage", "submitted_by", "submitted_at",
        "accepted", "score_payload", "raw_feedback_text", "feedback_attestation",
        "feedback_schema_version", "created_by",
    },
    "real_idea_quality_evaluations": {
        "quality_evaluation_id", "batch_id", "sample_id", "project_id", "artifact_type",
        "artifact_version_id", "selected_solution_id", "snapshot_id", "upstream_version_ids",
        "quality_layer", "quality_revision", "status", "metric_payload", "input_manifest_sha256",
        "evidence_manifest_sha256", "policy_version", "quality_schema_version", "evaluator_role",
        "created_at", "supersedes_quality_evaluation_id",
    },
    "real_idea_annotations": {
        "annotation_id", "quality_evaluation_id", "batch_id", "sample_id", "annotation_kind", "target_type", "target_id",
        "payload_json", "annotation_schema_version", "policy_version", "revision", "input_sha256",
        "evidence_sha256", "supersedes_annotation_id", "created_at", "created_by",
    },
}

_EXPECTED_PRIMARY_KEYS = {
    "real_idea_batches": ("batch_id",),
    "real_idea_samples": ("sample_id",),
    "real_idea_budget_allocations": ("allocation_id",),
    "real_idea_budget_extensions": ("extension_id",),
    "real_idea_transport_reservations": ("reservation_id",),
    "real_idea_feedback": ("feedback_id",),
    "real_idea_quality_evaluations": ("quality_evaluation_id",),
    "real_idea_annotations": ("annotation_id",),
}

_EXPECTED_UNIQUES = {
    "real_idea_batches": {("batch_key",)},
    "real_idea_samples": {("batch_id", "sample_key"), ("project_id",), ("batch_id", "sample_id")},
    "real_idea_budget_allocations": {("batch_id",), ("batch_id", "allocation_id")},
    "real_idea_budget_extensions": {("bound_batch_id",)},
    "real_idea_transport_reservations": {("idempotency_key",), ("batch_id", "sample_id", "stage", "ordinal")},
    "real_idea_feedback": set(),
    "real_idea_quality_evaluations": {
        ("batch_id", "sample_id", "artifact_type", "artifact_version_id", "quality_revision"),
        ("quality_evaluation_id", "batch_id", "sample_id"),
    },
    "real_idea_annotations": {("sample_id", "annotation_kind", "target_id", "revision")},
}

_EXPECTED_CHECKS = {
    "real_idea_batches": (
        "CHECK(sample_count=3)", "CHECK(search_allowed=0)",
        "CHECK(batch_version_splitIN(0,1))", "CHECK(started_atISNULLORfinished_atISNULLORfinished_at>=started_at)",
        "CHECK(finished_atISNULLORfinalized_atISNULLORfinalized_at>=finished_at)",
    ),
    "real_idea_samples": ("CHECK(sample_keyIN('REAL_IDEA_01','REAL_IDEA_02','REAL_IDEA_03'))",),
    "real_idea_budget_allocations": (
        "CHECK(authorized_total>=0)", "CHECK(batch_earmark>=0)", "CHECK(sample_cap>=0)",
        "CHECK(quickstart_cap>=0)", "CHECK(solutions_cap>=0)", "CHECK(release_countIN(0,1))",
    ),
    "real_idea_budget_extensions": ("CHECK(authorized_credits>0)", "CHECK(stateIN('AUTHORIZED','BOUND','RELEASED'))"),
    "real_idea_transport_reservations": (
        "CHECK(ordinal=1)", "CHECK(stateIN('RESERVED','ATTEMPTED','RELEASED'))",
    ),
    "real_idea_feedback": (
        "CHECK(submitted_by='idea_provider')", "CHECK(acceptedIN(0,1))",
        "CHECK(json_valid(score_payload))", "CHECK(feedback_attestation=1)",
    ),
    "real_idea_quality_evaluations": (
        "CHECK(artifact_typeIN('SOLUTIONS','PRD','TECHDOC','HANDOFF'))",
        "CHECK(json_valid(upstream_version_ids))", "CHECK(quality_layerIN('P0','P1','P2'))",
        "CHECK(quality_revision>=1)", "CHECK(statusIN('PASS','PARTIAL','FAIL'))",
        "CHECK(json_valid(metric_payload))",
        "CHECK(evaluator_roleIN('system','idea_provider','independent_reviewer','llm_assist'))",
    ),
    "real_idea_annotations": (
        "CHECK(annotation_kindIN('requirement','claim','decision','inheritance'))",
        "CHECK(json_valid(payload_json))", "CHECK(revision>=1)",
    ),
}

_EXPECTED_FOREIGN_KEYS = {
    "real_idea_batches": set(),
    "real_idea_samples": {
        ("real_idea_batches", ("batch_id",), ("batch_id",)),
        ("projects", ("project_id",), ("id",)),
        ("project_snapshots", ("snapshot_id",), ("id",)),
        ("document_versions", ("prd_version_id",), ("id",)),
        ("document_versions", ("techdoc_version_id",), ("id",)),
        ("real_idea_budget_allocations", ("batch_id", "budget_allocation_id"), ("batch_id", "allocation_id")),
        ("idea_briefs", ("brief_version_id",), ("id",)),
        ("solution_runs", ("solutions_evaluation_id",), ("id",)),
        ("solution_candidates", ("selected_solution_id",), ("id",)),
        ("handoff_runs", ("handoff_run_id",), ("id",)),
    },
    "real_idea_budget_allocations": {("real_idea_batches", ("batch_id",), ("batch_id",))},
    "real_idea_budget_extensions": {("real_idea_batches", ("bound_batch_id",), ("batch_id",))},
    "real_idea_transport_reservations": {
        ("real_idea_batches", ("batch_id",), ("batch_id",)),
        ("real_idea_samples", ("sample_id",), ("sample_id",)),
        ("real_idea_samples", ("batch_id", "sample_id"), ("batch_id", "sample_id")),
    },
    "real_idea_feedback": {
        ("real_idea_batches", ("batch_id",), ("batch_id",)),
        ("real_idea_samples", ("sample_id",), ("sample_id",)),
        ("real_idea_samples", ("batch_id", "sample_id"), ("batch_id", "sample_id")),
    },
    "real_idea_quality_evaluations": {
        ("real_idea_batches", ("batch_id",), ("batch_id",)),
        ("real_idea_samples", ("sample_id",), ("sample_id",)),
        ("projects", ("project_id",), ("id",)),
        ("solution_candidates", ("selected_solution_id",), ("id",)),
        ("project_snapshots", ("snapshot_id",), ("id",)),
        ("real_idea_samples", ("batch_id", "sample_id"), ("batch_id", "sample_id")),
        ("real_idea_quality_evaluations", ("supersedes_quality_evaluation_id",), ("quality_evaluation_id",)),
    },
    "real_idea_annotations": {
        ("real_idea_quality_evaluations", ("quality_evaluation_id",), ("quality_evaluation_id",)),
        ("real_idea_batches", ("batch_id",), ("batch_id",)),
        ("real_idea_samples", ("sample_id",), ("sample_id",)),
        ("real_idea_samples", ("batch_id", "sample_id"), ("batch_id", "sample_id")),
        ("real_idea_annotations", ("supersedes_annotation_id",), ("annotation_id",)),
        ("real_idea_quality_evaluations", ("quality_evaluation_id", "batch_id", "sample_id"), ("quality_evaluation_id", "batch_id", "sample_id")),
    },
}

_EXPECTED_INDEXES = {
    "real_idea_batches": {"idx_real_idea_batches_batch_key": ("batch_key",)},
    "real_idea_samples": {
        "idx_real_idea_samples_batch": ("batch_id",),
        "idx_real_idea_samples_project": ("project_id",),
    },
    "real_idea_budget_allocations": {"idx_real_idea_allocations_batch": ("batch_id",)},
    "real_idea_budget_extensions": {},
    "real_idea_transport_reservations": {"idx_real_idea_reservations_sample": ("sample_id", "stage")},
    "real_idea_feedback": {"idx_real_idea_feedback_sample": ("batch_id", "sample_id", "stage")},
    "real_idea_quality_evaluations": {
        "idx_real_idea_quality_batch": ("batch_id", "sample_id"),
        "idx_real_idea_quality_artifact_status": ("artifact_type", "status"),
        "idx_real_idea_quality_evidence": ("evidence_manifest_sha256",),
    },
    "real_idea_annotations": {"idx_real_idea_annotations_sample_kind": ("sample_id", "annotation_kind")},
}

_EXPECTED_TRIGGERS = {
    "real_idea_batches": {
        "trg_real_idea_batch_finalize_immutable", "trg_real_idea_batch_finalize_no_delete",
        "trg_real_idea_batch_audit_immutable",
    },
    "real_idea_samples": {"trg_real_idea_sample_binding_immutable"},
    "real_idea_budget_allocations": {"trg_real_idea_allocation_audit_immutable"},
    "real_idea_budget_extensions": {
        "trg_real_idea_budget_extension_audit_immutable",
        "trg_real_idea_budget_extension_no_delete",
    },
    "real_idea_transport_reservations": {"trg_real_idea_reservation_identity_immutable"},
    "real_idea_feedback": {"trg_real_idea_feedback_immutable", "trg_real_idea_feedback_no_delete"},
    "real_idea_quality_evaluations": {
        "trg_real_idea_quality_evaluation_immutable", "trg_real_idea_quality_evaluation_no_delete",
    },
    "real_idea_annotations": {"trg_real_idea_annotation_immutable", "trg_real_idea_annotation_no_delete"},
}


def _normalized_sql(sql: str) -> str:
    return "".join(sql.lower().split())


def _foreign_keys(connection: sqlite3.Connection, table: str) -> set[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    grouped: dict[int, list[tuple[int, str, str, str]]] = {}
    for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
        grouped.setdefault(row[0], []).append((row[1], row[2], row[3], row[4]))
    return {
        (rows[0][1], tuple(row[2] for row in sorted(rows)), tuple(row[3] for row in sorted(rows)))
        for rows in grouped.values()
    }


def _unique_indexes(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    uniques: set[tuple[str, ...]] = set()
    for row in connection.execute(f"PRAGMA index_list({table})"):
        if row[2]:
            uniques.add(tuple(info[2] for info in connection.execute(f"PRAGMA index_info({row[1]})")))
    return uniques


def _validate_schema(connection: sqlite3.Connection) -> None:
    for table, expected_columns in _EXPECTED_COLUMNS.items():
        table_info = list(connection.execute(f"PRAGMA table_info({table})"))
        if not table_info:
            raise RuntimeError(f"real idea schema {table} is missing")
        columns = {row[1] for row in table_info}
        if columns != expected_columns:
            missing = ", ".join(sorted(expected_columns - columns))
            extra = ", ".join(sorted(columns - expected_columns))
            detail = f"missing columns: {missing}" if missing else f"unexpected columns: {extra}"
            raise RuntimeError(f"real idea schema {table} has invalid columns: {detail}")

        primary_key = tuple(row[1] for row in sorted(table_info, key=lambda row: row[5]) if row[5])
        if primary_key != _EXPECTED_PRIMARY_KEYS[table]:
            raise RuntimeError(f"real idea schema {table} has invalid primary key")
        if not _EXPECTED_UNIQUES[table] <= _unique_indexes(connection, table):
            raise RuntimeError(f"real idea schema {table} is missing unique constraints")
        sql = _normalized_sql(connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0])
        for check in _EXPECTED_CHECKS[table]:
            if _normalized_sql(check) not in sql:
                raise RuntimeError(f"real idea schema {table} is missing check constraint")
        if _foreign_keys(connection, table) != _EXPECTED_FOREIGN_KEYS[table]:
            raise RuntimeError(f"real idea schema {table} has invalid foreign keys")
        for index_name, expected_index_columns in _EXPECTED_INDEXES[table].items():
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
            ).fetchone()
            actual_index_columns = tuple(
                info[2] for info in connection.execute(f"PRAGMA index_info({index_name})")
            ) if row else ()
            if actual_index_columns != expected_index_columns:
                raise RuntimeError(f"real idea schema {table} is missing index {index_name}")
        trigger_names = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)
            )
        }
        if not _EXPECTED_TRIGGERS[table] <= trigger_names:
            raise RuntimeError(f"real idea schema {table} is missing immutability trigger")


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
