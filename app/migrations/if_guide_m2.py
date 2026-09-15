"""IF Guide R1.1 M2 schema migration.

M2 is project-local and provider-free.  Its quality evidence deliberately
uses the existing Real Idea quality ledger; this migration only extends that
ledger so that project-local artifacts do not need a second quality store.
"""

from __future__ import annotations

import sqlite3


VERSION = 1
_VERSION_TABLE = "if_guide_m2_schema_meta"


BUILD_SLICES_SQL = """
CREATE TABLE IF NOT EXISTS build_slices (
    slice_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_actor TEXT NOT NULL,
    intent_revision INTEGER NOT NULL CHECK(intent_revision >= 1),
    first_action_task_id TEXT,
    first_action_revision INTEGER,
    snapshot_id TEXT REFERENCES project_snapshots(id),
    snapshot_version INTEGER,
    purpose TEXT NOT NULL,
    confirmed_constraints TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(confirmed_constraints)),
    in_scope_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(in_scope_json)),
    out_of_scope_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(out_of_scope_json)),
    minimal_flow_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(minimal_flow_json)),
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(acceptance_criteria_json)),
    inputs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(inputs_json)),
    expected_outputs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(expected_outputs_json)),
    error_handling_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(error_handling_json)),
    unknowns_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(unknowns_json)),
    constraint_notes_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(constraint_notes_json)),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'CONFIRMED', 'NEEDS_REVISION')),
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, slice_id)
);

CREATE INDEX IF NOT EXISTS idx_build_slices_project
    ON build_slices(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_build_slices_owner
    ON build_slices(owner_actor, project_id);
"""


PROTOTYPE_TASKS_SQL = """
CREATE TABLE IF NOT EXISTS prototype_tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_actor TEXT NOT NULL,
    slice_id TEXT NOT NULL REFERENCES build_slices(slice_id),
    slice_revision INTEGER NOT NULL CHECK(slice_revision >= 1),
    snapshot_id TEXT REFERENCES project_snapshots(id),
    snapshot_version INTEGER,
    purpose TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(scope_json)),
    inputs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(inputs_json)),
    outputs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(outputs_json)),
    existing_behaviors_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(existing_behaviors_json)),
    non_goals_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(non_goals_json)),
    known_context_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(known_context_json)),
    unknown_dependencies_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(unknown_dependencies_json)),
    implementation_tasks_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(implementation_tasks_json)),
    acceptance_steps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(acceptance_steps_json)),
    failure_recovery_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(failure_recovery_json)),
    required_evidence_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_evidence_json)),
    permission_risk_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(permission_risk_json)),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'READY', 'NEEDS_REVISION')),
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_prototype_tasks_project
    ON prototype_tasks(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_prototype_tasks_slice
    ON prototype_tasks(slice_id, slice_revision);
"""


_QUALITY_EXTENSION_COLUMNS = {
    "owner_actor",
    "artifact_id",
    "artifact_revision",
    "evaluation_scope",
    "intent_revision",
    "slice_id",
    "slice_revision",
}


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a schema script without implicit commits.

    ``Connection.executescript`` commits the active transaction before it
    runs.  M2 is applied from inside the application's migration transaction,
    so using it here would destroy the savepoint that makes the migration
    rollback-safe.  The existing migration code uses the same statement-wise
    approach for this reason.
    """
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        connection.execute(statement)


def _rebuild_quality_ledger(connection: sqlite3.Connection) -> None:
    """Extend the existing immutable ledger while preserving old rows.

    SQLite cannot make the historical batch/sample columns nullable with an
    ALTER TABLE.  Renaming both related tables and recreating them keeps their
    existing composite foreign-key contract intact and lets M2 use NULL for
    batch/sample, without introducing a parallel quality ledger.
    """
    if not _table_exists(connection, "real_idea_quality_evaluations"):
        return
    columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(real_idea_quality_evaluations)"
        ).fetchall()
    }
    if _QUALITY_EXTENSION_COLUMNS <= columns:
        return

    for trigger in (
        "trg_real_idea_quality_evaluation_immutable",
        "trg_real_idea_quality_evaluation_no_delete",
        "trg_real_idea_annotation_immutable",
        "trg_real_idea_annotation_no_delete",
    ):
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    for index in (
        "idx_real_idea_quality_batch",
        "idx_real_idea_quality_artifact_status",
        "idx_real_idea_quality_evidence",
        "idx_real_idea_annotations_sample_kind",
    ):
        connection.execute(f"DROP INDEX IF EXISTS {index}")

    connection.execute(
        "ALTER TABLE real_idea_annotations RENAME TO real_idea_annotations_legacy"
    )
    connection.execute(
        "ALTER TABLE real_idea_quality_evaluations "
        "RENAME TO real_idea_quality_evaluations_legacy"
    )

    connection.execute(
        """
        CREATE TABLE real_idea_quality_evaluations (
            quality_evaluation_id TEXT PRIMARY KEY,
            batch_id TEXT REFERENCES real_idea_batches(batch_id),
            sample_id TEXT REFERENCES real_idea_samples(sample_id),
            project_id TEXT NOT NULL REFERENCES projects(id),
            artifact_type TEXT NOT NULL CHECK(artifact_type IN (
                'SOLUTIONS', 'PRD', 'TECHDOC', 'HANDOFF',
                'BUILD_SLICE', 'PROTOTYPE_TASK'
            )),
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
            evaluator_role TEXT NOT NULL CHECK(evaluator_role IN (
                'system', 'idea_provider', 'independent_reviewer', 'llm_assist'
            )),
            created_at TEXT NOT NULL,
            supersedes_quality_evaluation_id TEXT
                REFERENCES real_idea_quality_evaluations(quality_evaluation_id),
            owner_actor TEXT,
            artifact_id TEXT,
            artifact_revision INTEGER,
            evaluation_scope TEXT NOT NULL DEFAULT 'REAL_IDEA_BATCH',
            intent_revision INTEGER,
            slice_id TEXT,
            slice_revision INTEGER,
            UNIQUE(batch_id, sample_id, artifact_type, artifact_version_id, quality_revision),
            UNIQUE(quality_evaluation_id, batch_id, sample_id),
            FOREIGN KEY (batch_id, sample_id)
                REFERENCES real_idea_samples(batch_id, sample_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO real_idea_quality_evaluations(
            quality_evaluation_id, batch_id, sample_id, project_id,
            artifact_type, artifact_version_id, selected_solution_id, snapshot_id,
            upstream_version_ids, quality_layer, quality_revision, status,
            metric_payload, input_manifest_sha256, evidence_manifest_sha256,
            policy_version, quality_schema_version, evaluator_role, created_at,
            supersedes_quality_evaluation_id, evaluation_scope, artifact_id,
            artifact_revision
        )
        SELECT quality_evaluation_id, batch_id, sample_id, project_id,
            artifact_type, artifact_version_id, selected_solution_id, snapshot_id,
            upstream_version_ids, quality_layer, quality_revision, status,
            metric_payload, input_manifest_sha256, evidence_manifest_sha256,
            policy_version, quality_schema_version, evaluator_role, created_at,
            supersedes_quality_evaluation_id, 'REAL_IDEA_BATCH',
            artifact_version_id, 1
        FROM real_idea_quality_evaluations_legacy
        """
    )
    connection.execute(
        """
        CREATE TABLE real_idea_annotations (
            annotation_id TEXT PRIMARY KEY,
            quality_evaluation_id TEXT NOT NULL
                REFERENCES real_idea_quality_evaluations(quality_evaluation_id),
            batch_id TEXT NOT NULL REFERENCES real_idea_batches(batch_id),
            sample_id TEXT NOT NULL REFERENCES real_idea_samples(sample_id),
            annotation_kind TEXT NOT NULL CHECK(annotation_kind IN (
                'requirement', 'claim', 'decision', 'inheritance'
            )),
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
                REFERENCES real_idea_quality_evaluations(
                    quality_evaluation_id, batch_id, sample_id
                ),
            FOREIGN KEY (batch_id, sample_id)
                REFERENCES real_idea_samples(batch_id, sample_id)
        )
        """
    )
    connection.execute(
        """
        INSERT INTO real_idea_annotations(
            annotation_id, quality_evaluation_id, batch_id, sample_id,
            annotation_kind, target_type, target_id, payload_json,
            annotation_schema_version, policy_version, revision, input_sha256,
            evidence_sha256, supersedes_annotation_id, created_at, created_by
        )
        SELECT annotation_id, quality_evaluation_id, batch_id, sample_id,
            annotation_kind, target_type, target_id, payload_json,
            annotation_schema_version, policy_version, revision, input_sha256,
            evidence_sha256, supersedes_annotation_id, created_at, created_by
        FROM real_idea_annotations_legacy
        """
    )
    connection.execute("DROP TABLE real_idea_annotations_legacy")
    connection.execute("DROP TABLE real_idea_quality_evaluations_legacy")

    _execute_script(
        connection,
        """
        CREATE INDEX IF NOT EXISTS idx_real_idea_quality_batch
            ON real_idea_quality_evaluations(batch_id, sample_id);
        CREATE INDEX IF NOT EXISTS idx_real_idea_quality_artifact_status
            ON real_idea_quality_evaluations(artifact_type, status);
        CREATE INDEX IF NOT EXISTS idx_real_idea_quality_evidence
            ON real_idea_quality_evaluations(evidence_manifest_sha256);
        CREATE INDEX IF NOT EXISTS idx_real_idea_quality_project
            ON real_idea_quality_evaluations(project_id, evaluation_scope);
        CREATE INDEX IF NOT EXISTS idx_real_idea_annotations_sample_kind
            ON real_idea_annotations(sample_id, annotation_kind);
        CREATE TRIGGER trg_real_idea_quality_evaluation_immutable
        BEFORE UPDATE ON real_idea_quality_evaluations
        BEGIN
            SELECT RAISE(ABORT, 'real idea quality evaluation is immutable');
        END;
        CREATE TRIGGER trg_real_idea_quality_evaluation_no_delete
        BEFORE DELETE ON real_idea_quality_evaluations
        BEGIN
            SELECT RAISE(ABORT, 'real idea quality evaluation is immutable');
        END;
        CREATE TRIGGER trg_real_idea_annotation_immutable
        BEFORE UPDATE ON real_idea_annotations
        BEGIN
            SELECT RAISE(ABORT, 'real idea annotation is immutable');
        END;
        CREATE TRIGGER trg_real_idea_annotation_no_delete
        BEFORE DELETE ON real_idea_annotations
        BEGIN
            SELECT RAISE(ABORT, 'real idea annotation is immutable');
        END;
        """
    )


def apply(connection: sqlite3.Connection) -> None:
    """Apply M2 schema in the caller's transaction."""
    row = connection.execute(
        "SELECT version FROM if_guide_m2_schema_meta WHERE singleton=1"
    ).fetchone() if _table_exists(connection, _VERSION_TABLE) else None
    current = int(row[0]) if row is not None else 0
    if current >= VERSION:
        return

    connection.execute("SAVEPOINT if_guide_m2")
    try:
        _execute_script(connection, BUILD_SLICES_SQL)
        _execute_script(connection, PROTOTYPE_TASKS_SQL)
        _rebuild_quality_ledger(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS if_guide_m2_schema_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO if_guide_m2_schema_meta(singleton, version) VALUES (1, ?)",
            (VERSION,),
        )
        connection.execute("RELEASE SAVEPOINT if_guide_m2")
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT if_guide_m2")
        connection.execute("RELEASE SAVEPOINT if_guide_m2")
        raise
