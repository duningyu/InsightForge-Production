from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

SOURCE_TYPES = {
    "real_user_research",
    "simulated_research",
    "public_source",
    "user_input",
    "model_hypothesis",
    "implementation_evidence",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def chunk_text(text: str, max_chars: int = 520, overlap: int = 60) -> list[str]:
    normalized = "\n".join(line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip())
    if not normalized:
        return []
    if max_chars <= 0 or overlap < 0 or overlap >= max_chars:
        raise ValueError("max_chars must be positive and overlap must be in [0, max_chars)")
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            candidates = [
                normalized.rfind("。", start, end),
                normalized.rfind("\n", start, end),
                normalized.rfind("；", start, end),
            ]
            boundary = max(candidates)
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunks.append(normalized[start:end].strip())
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return [chunk for chunk in chunks if chunk]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    current_snapshot_id TEXT,
    project_origin TEXT NOT NULL DEFAULT 'user' CHECK(project_origin IN ('user','demo','qa')),
    exclude_from_beta_metrics INTEGER NOT NULL DEFAULT 0 CHECK(exclude_from_beta_metrics IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_relations (
    parent_project_id TEXT NOT NULL REFERENCES projects(id),
    child_project_id TEXT PRIMARY KEY REFERENCES projects(id),
    relation_type TEXT NOT NULL CHECK(relation_type IN ('example_copy','project_copy')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_relations_parent
    ON project_relations(parent_project_id, relation_type, created_at);
CREATE TABLE IF NOT EXISTS project_canvas (
    project_id TEXT PRIMARY KEY REFERENCES projects(id),
    version INTEGER NOT NULL,
    problem TEXT NOT NULL,
    target_users TEXT NOT NULL,
    goals_json TEXT NOT NULL,
    non_goals_json TEXT NOT NULL,
    success_metrics_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_canvas_versions (
    project_id TEXT NOT NULL REFERENCES projects(id),
    version INTEGER NOT NULL,
    problem TEXT NOT NULL,
    target_users TEXT NOT NULL,
    goals_json TEXT NOT NULL,
    non_goals_json TEXT NOT NULL,
    success_metrics_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, version)
);
CREATE INDEX IF NOT EXISTS idx_canvas_versions_project
    ON project_canvas_versions(project_id, version DESC);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN (
        'real_user_research','simulated_research','public_source',
        'user_input','model_hypothesis','implementation_evidence'
    )),
    authority REAL NOT NULL CHECK(authority >= 0 AND authority <= 1),
    content TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    source_url TEXT,
    publisher TEXT,
    published_at TEXT,
    captured_at TEXT,
    authority_label TEXT,
    authority_basis TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id, source_type);
CREATE TABLE IF NOT EXISTS source_chunks (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_source_chunks_project ON source_chunks(project_id);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    doc_type TEXT NOT NULL CHECK(doc_type IN ('prd','techdoc')),
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, doc_type)
);
CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    doc_type TEXT NOT NULL,
    version INTEGER NOT NULL,
    canvas_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    trashed_at TEXT,
    restored_from_version_id TEXT REFERENCES document_versions(id),
    UNIQUE(document_id, version)
);
CREATE INDEX IF NOT EXISTS idx_document_versions_project ON document_versions(project_id, doc_type, version);
CREATE TABLE IF NOT EXISTS document_edit_drafts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    doc_type TEXT NOT NULL CHECK(doc_type IN ('prd','techdoc')),
    base_version_id TEXT NOT NULL REFERENCES document_versions(id),
    content TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, doc_type)
);
CREATE INDEX IF NOT EXISTS idx_document_edit_drafts_project
    ON document_edit_drafts(project_id, doc_type);
CREATE TABLE IF NOT EXISTS project_tour_progress (
    project_id TEXT NOT NULL REFERENCES projects(id),
    tour_id TEXT NOT NULL,
    current_step TEXT NOT NULL,
    completed_steps_json TEXT NOT NULL DEFAULT '[]',
    dismissed_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, tour_id)
);
CREATE INDEX IF NOT EXISTS idx_project_tour_progress_updated
    ON project_tour_progress(updated_at DESC);
CREATE TABLE IF NOT EXISTS generation_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    doc_type TEXT NOT NULL,
    status TEXT NOT NULL,
    terminal_state TEXT NOT NULL,
    rounds INTEGER NOT NULL DEFAULT 0,
    version_id TEXT,
    retrieval_run_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validation_issues (
    id TEXT PRIMARY KEY,
    generation_run_id TEXT NOT NULL REFERENCES generation_runs(id),
    version_id TEXT,
    round_no INTEGER NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    section TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guided_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL UNIQUE REFERENCES projects(id),
    current_step TEXT NOT NULL,
    state_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guided_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES guided_sessions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    message_type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guided_messages_session
    ON guided_messages(session_id, created_at, id);
CREATE TABLE IF NOT EXISTS project_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    decision_type TEXT NOT NULL,
    options_json TEXT NOT NULL,
    selected_option_id TEXT,
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    decision_key TEXT,
    decision_version INTEGER,
    decision_payload_json TEXT NOT NULL DEFAULT '{}',
    supersedes_decision_id TEXT,
    confirmed_by TEXT,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_project_decisions_project
    ON project_decisions(project_id, created_at DESC);
CREATE TABLE IF NOT EXISTS retrieval_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    query TEXT NOT NULL,
    purpose TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    top_k INTEGER NOT NULL,
    bm25_weight REAL NOT NULL,
    cosine_weight REAL NOT NULL,
    authority_weight REAL NOT NULL,
    source_types_json TEXT NOT NULL,
    candidate_count INTEGER NOT NULL,
    returned_count INTEGER NOT NULL,
    actor TEXT NOT NULL,
    selection_basis TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retrieval_runs_project
    ON retrieval_runs(project_id, created_at DESC);
CREATE TABLE IF NOT EXISTS retrieval_hits (
    run_id TEXT NOT NULL REFERENCES retrieval_runs(id),
    rank INTEGER NOT NULL,
    chunk_id TEXT NOT NULL REFERENCES source_chunks(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    bm25_score REAL NOT NULL,
    cosine_score REAL NOT NULL,
    authority_score REAL NOT NULL,
    hybrid_score REAL NOT NULL,
    PRIMARY KEY(run_id, rank)
);
CREATE INDEX IF NOT EXISTS idx_retrieval_hits_chunk
    ON retrieval_hits(chunk_id, run_id);
CREATE TABLE IF NOT EXISTS document_claims (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES document_versions(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    section TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK(claim_type IN (
        'user_confirmed','source_backed','model_suggestion','unresolved'
    )),
    support_status TEXT NOT NULL,
    explanation TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_document_claims_version
    ON document_claims(version_id, section, id);
CREATE TABLE IF NOT EXISTS claim_evidence_links (
    claim_id TEXT NOT NULL REFERENCES document_claims(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    chunk_id TEXT NOT NULL REFERENCES source_chunks(id),
    relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','context')),
    retrieval_run_id TEXT REFERENCES retrieval_runs(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(claim_id, chunk_id, relation)
);
CREATE TABLE IF NOT EXISTS handoff_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    target_client TEXT NOT NULL,
    status TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    sha256 TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_handoff_runs_project
    ON handoff_runs(project_id, created_at DESC);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idea_briefs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    version INTEGER NOT NULL,
    original_idea TEXT NOT NULL,
    target_user TEXT NOT NULL,
    problem TEXT NOT NULL,
    desired_outcome TEXT NOT NULL,
    known_resources_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    unknowns_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    clarification_required INTEGER NOT NULL DEFAULT 0 CHECK(clarification_required IN (0,1)),
    clarification_question TEXT,
    confirmation_status TEXT NOT NULL CHECK(confirmation_status IN ('inferred','confirmed','superseded')),
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    supersedes_id TEXT REFERENCES idea_briefs(id),
    UNIQUE(project_id, version)
);
CREATE INDEX IF NOT EXISTS idx_idea_briefs_project
    ON idea_briefs(project_id, version DESC);

CREATE TABLE IF NOT EXISTS solution_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    idea_brief_id TEXT NOT NULL REFERENCES idea_briefs(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    output_sha256 TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_solution_runs_project
    ON solution_runs(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS solution_candidates (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES solution_runs(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    mechanism TEXT NOT NULL CHECK(mechanism IN (
        'rule_based','workflow_based','prediction_based','recommendation_based',
        'optimization','search_retrieval','automation','human_in_the_loop',
        'assistant','marketplace','other'
    )),
    summary TEXT NOT NULL,
    why_fit TEXT NOT NULL,
    user_flow_json TEXT NOT NULL,
    mvp_pages_json TEXT NOT NULL,
    features_json TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    outputs_json TEXT NOT NULL,
    decision_logic_json TEXT NOT NULL,
    data_requirements_json TEXT NOT NULL,
    technical_components_json TEXT NOT NULL,
    implementation_plan_json TEXT NOT NULL,
    acceptance_cases_json TEXT NOT NULL,
    risks_json TEXT NOT NULL,
    unknowns_json TEXT NOT NULL,
    complexity TEXT NOT NULL,
    provenance TEXT NOT NULL,
    required_data_class TEXT NOT NULL DEFAULT '',
    automation_level TEXT NOT NULL DEFAULT 'low',
    human_role TEXT NOT NULL DEFAULT '',
    core_decision_logic TEXT NOT NULL DEFAULT '',
    major_dependency TEXT NOT NULL DEFAULT '',
    requires_llm_runtime INTEGER NOT NULL DEFAULT 0 CHECK(requires_llm_runtime IN (0,1)),
    requires_rag_runtime INTEGER NOT NULL DEFAULT 0 CHECK(requires_rag_runtime IN (0,1)),
    requires_agent_runtime INTEGER NOT NULL DEFAULT 0 CHECK(requires_agent_runtime IN (0,1)),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_solution_candidates_run
    ON solution_candidates(run_id, created_at, id);

CREATE TABLE IF NOT EXISTS project_claims (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    claim_type TEXT NOT NULL CHECK(claim_type IN ('target_user','user_problem','behavior','value','feasibility')),
    statement TEXT NOT NULL,
    provenance TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK(verification_status IN (
        'unverified','limited_support','supported','conflict','contradicted','stale'
    )),
    criticality TEXT NOT NULL,
    scope_note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    supersedes_claim_id TEXT REFERENCES project_claims(id)
);
CREATE INDEX IF NOT EXISTS idx_project_claims_project
    ON project_claims(project_id, status, criticality);

CREATE TABLE IF NOT EXISTS project_claim_evidence_links (
    claim_id TEXT NOT NULL REFERENCES project_claims(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    chunk_id TEXT NOT NULL REFERENCES source_chunks(id),
    relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','contextualizes')),
    directness TEXT NOT NULL,
    scope_fit TEXT NOT NULL,
    recency_state TEXT NOT NULL,
    retrieval_run_id TEXT REFERENCES retrieval_runs(id),
    analysis_version TEXT NOT NULL,
    evidence_span TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    source_sha256_at_link TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    created_at TEXT NOT NULL,
    PRIMARY KEY(claim_id, chunk_id, relation)
);

CREATE TABLE IF NOT EXISTS decision_claim_links (
    decision_id TEXT NOT NULL REFERENCES project_decisions(id),
    claim_id TEXT NOT NULL REFERENCES project_claims(id),
    role TEXT NOT NULL CHECK(role IN ('supports','blocks','assumption')),
    created_at TEXT NOT NULL,
    PRIMARY KEY(decision_id, claim_id, role)
);

CREATE TABLE IF NOT EXISTS project_snapshots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    version INTEGER NOT NULL,
    idea_brief_id TEXT NOT NULL REFERENCES idea_briefs(id),
    decision_id TEXT NOT NULL REFERENCES project_decisions(id),
    title TEXT NOT NULL,
    one_liner TEXT NOT NULL,
    target_user_json TEXT NOT NULL,
    problem_json TEXT NOT NULL,
    solution_json TEXT NOT NULL,
    mvp_json TEXT NOT NULL,
    user_flow_json TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    outputs_json TEXT NOT NULL,
    technical_plan_json TEXT NOT NULL,
    unknowns_json TEXT NOT NULL,
    next_action_json TEXT NOT NULL,
    snapshot_origin TEXT NOT NULL CHECK(snapshot_origin IN ('quick_value_flow','change_proposal','legacy_migration')),
    created_at TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    supersedes_snapshot_id TEXT REFERENCES project_snapshots(id),
    content_sha256 TEXT NOT NULL,
    UNIQUE(project_id, version)
);

CREATE TABLE IF NOT EXISTS snapshot_claim_links (
    snapshot_id TEXT NOT NULL REFERENCES project_snapshots(id),
    claim_id TEXT NOT NULL REFERENCES project_claims(id),
    role TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, claim_id, role)
);

CREATE TABLE IF NOT EXISTS snapshot_decision_links (
    snapshot_id TEXT NOT NULL REFERENCES project_snapshots(id),
    decision_id TEXT NOT NULL REFERENCES project_decisions(id),
    role TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, decision_id, role)
);

CREATE TABLE IF NOT EXISTS change_proposals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    trigger_source_id TEXT REFERENCES sources(id),
    from_snapshot_id TEXT NOT NULL REFERENCES project_snapshots(id),
    proposal_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    reason TEXT NOT NULL,
    affected_claims_json TEXT NOT NULL,
    affected_decisions_json TEXT NOT NULL,
    suggested_changes_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','accepted','rejected','deferred')),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_change_proposals_project
    ON change_proposals(project_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS artifact_dependencies (
    artifact_type TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    dependency_type TEXT NOT NULL,
    dependency_id TEXT NOT NULL,
    dependency_version TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(artifact_type, artifact_id, dependency_type, dependency_id)
);
CREATE INDEX IF NOT EXISTS idx_artifact_dependencies_dependency
    ON artifact_dependencies(dependency_type, dependency_id);

CREATE TABLE IF NOT EXISTS artifact_health (
    artifact_type TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    health_status TEXT NOT NULL CHECK(health_status IN ('current','needs_review','stale_evidence','superseded')),
    reason TEXT NOT NULL,
    trigger_source_id TEXT REFERENCES sources(id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(artifact_type, artifact_id)
);

CREATE TABLE IF NOT EXISTS model_profiles (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    protocol TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    model_id TEXT NOT NULL,
    credential_ref TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1)),
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    capabilities_checked_at TEXT,
    last_test_status TEXT,
    last_tested_at TEXT,
    last_live_test_status TEXT,
    last_live_tested_at TEXT,
    last_live_latency_ms INTEGER,
    last_live_error_code TEXT,
    last_live_model_returned TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_profiles_default
    ON model_profiles(is_default, enabled);

CREATE TABLE IF NOT EXISTS model_profile_revisions (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES model_profiles(id),
    revision INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    protocol TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    model_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1)),
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    capabilities_checked_at TEXT,
    last_test_status TEXT,
    last_tested_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(profile_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_model_profile_revisions_profile
    ON model_profile_revisions(profile_id, revision DESC);

CREATE TABLE IF NOT EXISTS project_model_profiles (
    project_id TEXT PRIMARY KEY REFERENCES projects(id),
    profile_id TEXT REFERENCES model_profiles(id),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_model_profiles_profile
    ON project_model_profiles(profile_id);
CREATE TABLE IF NOT EXISTS beta_consents (
    id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, beta_release_id TEXT NOT NULL,
    consent_version INTEGER NOT NULL, consented_at TEXT NOT NULL,
    UNIQUE(participant_id, beta_release_id, consent_version)
);
CREATE TABLE IF NOT EXISTS beta_sessions (
    id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, beta_release_id TEXT NOT NULL,
    started_at TEXT NOT NULL, last_activity_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_beta_sessions_participant
    ON beta_sessions(participant_id, beta_release_id, last_activity_at);
CREATE TABLE IF NOT EXISTS product_events (
    id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, session_id TEXT NOT NULL,
    project_id TEXT, event_name TEXT NOT NULL, properties_json TEXT NOT NULL,
    beta_release_id TEXT NOT NULL, occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_events_participant ON product_events(participant_id, occurred_at);
CREATE TABLE IF NOT EXISTS beta_feedback (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    project_id TEXT REFERENCES projects(id),
    project_stage TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    feedback_type TEXT NOT NULL,
    comment TEXT NOT NULL CHECK(length(comment) BETWEEN 1 AND 2000),
    beta_release_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_beta_feedback_participant
    ON beta_feedback(participant_id, beta_release_id, created_at);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA_SQL)
            self._migrate_schema(connection)
            connection.execute(
                """
                INSERT OR IGNORE INTO project_canvas_versions(
                    project_id, version, problem, target_users, goals_json,
                    non_goals_json, success_metrics_json, constraints_json, created_at
                )
                SELECT project_id, version, problem, target_users, goals_json,
                       non_goals_json, success_metrics_json, constraints_json, updated_at
                FROM project_canvas
                """
            )

    @staticmethod
    def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}

    @classmethod
    def _ensure_column(
        cls,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        if column not in cls._table_columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @classmethod
    def _migrate_schema(cls, connection: sqlite3.Connection) -> None:
        cls._ensure_column(connection, "projects", "current_snapshot_id", "TEXT")
        cls._ensure_column(connection, "projects", "project_origin", "TEXT NOT NULL DEFAULT 'user'")
        cls._ensure_column(connection, "projects", "exclude_from_beta_metrics", "INTEGER NOT NULL DEFAULT 0")
        source_columns = {
            "source_url": "TEXT",
            "publisher": "TEXT",
            "published_at": "TEXT",
            "captured_at": "TEXT",
            "authority_label": "TEXT",
            "authority_basis": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, definition in source_columns.items():
            cls._ensure_column(connection, "sources", column, definition)
        decision_columns = {
            "decision_key": "TEXT",
            "decision_version": "INTEGER",
            "decision_payload_json": "TEXT NOT NULL DEFAULT '{}'",
            "supersedes_decision_id": "TEXT",
            "confirmed_by": "TEXT",
        }
        for column, definition in decision_columns.items():
            cls._ensure_column(connection, "project_decisions", column, definition)
        idea_brief_columns = {
            "clarification_required": "INTEGER NOT NULL DEFAULT 0",
            "clarification_question": "TEXT",
        }
        for column, definition in idea_brief_columns.items():
            cls._ensure_column(connection, "idea_briefs", column, definition)
        solution_candidate_columns = {
            "required_data_class": "TEXT NOT NULL DEFAULT ''",
            "automation_level": "TEXT NOT NULL DEFAULT 'low'",
            "human_role": "TEXT NOT NULL DEFAULT ''",
            "core_decision_logic": "TEXT NOT NULL DEFAULT ''",
            "major_dependency": "TEXT NOT NULL DEFAULT ''",
            "requires_llm_runtime": "INTEGER NOT NULL DEFAULT 0",
            "requires_rag_runtime": "INTEGER NOT NULL DEFAULT 0",
            "requires_agent_runtime": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in solution_candidate_columns.items():
            cls._ensure_column(connection, "solution_candidates", column, definition)
        model_profile_live_columns = {
            "last_live_test_status": "TEXT",
            "last_live_tested_at": "TEXT",
            "last_live_latency_ms": "INTEGER",
            "last_live_error_code": "TEXT",
            "last_live_model_returned": "TEXT",
        }
        for column, definition in model_profile_live_columns.items():
            cls._ensure_column(connection, "model_profiles", column, definition)
        cls._ensure_column(
            connection,
            "generation_runs",
            "retrieval_run_ids_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        cls._ensure_column(
            connection,
            "document_claims",
            "metadata_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        cls._ensure_column(
            connection,
            "document_versions",
            "lifecycle_status",
            "TEXT NOT NULL DEFAULT 'active'",
        )
        cls._ensure_column(connection, "document_versions", "trashed_at", "TEXT")
        cls._ensure_column(connection, "document_versions", "restored_from_version_id", "TEXT")
        connection.execute(
            "UPDATE sources SET captured_at = COALESCE(captured_at, created_at), "
            "authority_label = COALESCE(authority_label, CASE "
            "WHEN authority >= 0.8 THEN 'high' WHEN authority >= 0.55 THEN 'medium' ELSE 'low' END), "
            "authority_basis = COALESCE(authority_basis, 'legacy_numeric_score_without_recorded_basis'), "
            "status = COALESCE(status, 'active'), metadata_json = COALESCE(metadata_json, '{}')"
        )
        connection.execute(
            "UPDATE document_versions SET lifecycle_status = COALESCE(lifecycle_status, 'active')"
        )

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.connect() as connection:
            cursor = connection.execute(sql, params)
            return cursor.rowcount

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return dict(row) if row else None

    def insert_audit_tx(
        self,
        connection: sqlite3.Connection,
        *,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        event_id = f"audit_{uuid.uuid4().hex}"
        connection.execute(
            "INSERT INTO audit_events(id, actor, action, entity_type, entity_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(payload or {}, ensure_ascii=False),
                utc_now(),
            ),
        )
        return event_id

    def insert_audit(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        with self.connect() as connection:
            return self.insert_audit_tx(
                connection,
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )

    def get_canvas(self, project_id: str, version: int | None = None) -> dict[str, Any] | None:
        if version is None:
            row = self.fetch_one("SELECT * FROM project_canvas WHERE project_id = ?", (project_id,))
        else:
            row = self.fetch_one(
                "SELECT * FROM project_canvas_versions WHERE project_id = ? AND version = ?",
                (project_id, version),
            )
        if row is None:
            return None
        for field in ("goals_json", "non_goals_json", "success_metrics_json", "constraints_json"):
            row[field.removesuffix("_json")] = json.loads(row.pop(field))
        return row

    def add_source(
        self,
        *,
        project_id: str,
        title: str,
        source_type: str,
        authority: float,
        content: str,
        filename: str,
        source_url: str | None = None,
        publisher: str | None = None,
        published_at: str | None = None,
        captured_at: str | None = None,
        authority_label: str | None = None,
        authority_basis: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"invalid source_type: {source_type}")
        if not 0 <= authority <= 1:
            raise ValueError("authority must be in [0, 1]")
        if self.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,)) is None:
            raise KeyError("project not found")
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source_id = stable_id("source", f"{project_id}:{title}:{filename}:{sha256}")
        now = utc_now()
        with self.connect() as connection:
            derived_label = authority_label or (
                "high" if authority >= 0.8 else "medium" if authority >= 0.55 else "low"
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO sources(
                    id, project_id, title, filename, source_type, authority, content, sha256,
                    source_url, publisher, published_at, captured_at, authority_label,
                    authority_basis, status, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id, project_id, title, filename, source_type, authority, content, sha256,
                    source_url, publisher, published_at, captured_at or now, derived_label,
                    authority_basis or "manual_numeric_score_without_recorded_basis",
                    status, json.dumps(metadata or {}, ensure_ascii=False), now,
                ),
            )
            for index, chunk in enumerate(chunk_text(content)):
                chunk_id = stable_id("chunk", f"{source_id}:{index}:{chunk}")
                connection.execute(
                    "INSERT OR IGNORE INTO source_chunks(id, source_id, project_id, chunk_index, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (chunk_id, source_id, project_id, index, chunk, now),
                )
        return source_id

    def seed_demo_data(self) -> None:
        self.init_schema()
        now = utc_now()
        project_id = "project_insightforge_demo"
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO projects(id, title, summary, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    project_id,
                    "InsightForge AI 产品洞察平台",
                    "将分散的需求、研究、竞品和实现证据组织为可追溯的产品文档。",
                    "active",
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE projects SET project_origin='demo', exclude_from_beta_metrics=1 WHERE id=?",
                (project_id,),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO project_canvas(
                    project_id, version, problem, target_users, goals_json,
                    non_goals_json, success_metrics_json, constraints_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    1,
                    "产品资料分散在访谈、竞品文章、历史 PRD 与实现记录中，生成文档缺少来源边界和版本一致性。",
                    "需要快速整理 AI 产品方案的产品经理、创业团队和 AI coding 协作者。",
                    json.dumps([
                        "在一个项目范围内检索来源并生成带引用 PRD",
                        "区分真实研究、模拟研究、公开资料、假设与实现证据",
                        "通过受控质量 Loop 检查文档完整性和主张边界",
                    ], ensure_ascii=False),
                    json.dumps([
                        "不自动发布外部文档",
                        "不把模型推测改写为真实用户调研",
                        "当前版本不实现 GraphRAG 或无限自主 Agent",
                    ], ensure_ascii=False),
                    json.dumps([
                        "引用完整率达到 100%",
                        "无依据主张率为 0",
                        "文档生成 Loop 不超过 2 轮",
                    ], ensure_ascii=False),
                    json.dumps([
                        "默认本地可运行且不依赖云 API",
                        "所有检索必须绑定 project_id",
                        "批准版本只能新建版本，不能被覆盖",
                    ], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO project_canvas_versions(
                    project_id, version, problem, target_users, goals_json,
                    non_goals_json, success_metrics_json, constraints_json, created_at
                )
                SELECT project_id, version, problem, target_users, goals_json,
                       non_goals_json, success_metrics_json, constraints_json, updated_at
                FROM project_canvas WHERE project_id = ?
                """,
                (project_id,),
            )

        seed_sources = [
            {
                "title": "项目发起说明",
                "filename": "project_brief.md",
                "source_type": "user_input",
                "authority": 0.90,
                "content": """
项目目标：帮助 AI 产品经理把需求背景、目标用户、竞品资料和技术实现整理为可执行 PRD 与 TechDoc。
关键要求：文档中的事实必须能追溯到来源；没有证据的内容必须标记为假设；不同版本需要可审计。
首期功能包括项目画布、资料录入、混合检索、PRD/TechDoc 生成、质量检查和导出。
""".strip(),
            },
            {
                "title": "模拟用户访谈样本",
                "filename": "simulated_interviews.txt",
                "source_type": "simulated_research",
                "authority": 0.45,
                "content": """
以下内容为人工构造的模拟访谈，不是真实用户研究。
样本 A：整理竞品和需求时经常复制粘贴，无法确认某句话来自哪里。
样本 B：使用大模型生成 PRD 后，需要逐段检查是否与最初目标冲突。
样本 C：希望把已批准 PRD 交给 AI coding 工具，但担心读取到过期版本。
""".strip(),
            },
            {
                "title": "公开竞品观察",
                "filename": "competitor_notes.md",
                "source_type": "public_source",
                "authority": 0.65,
                "content": """
公开产品通常分别覆盖知识库问答、文档协作或原型生成。常见差异包括：是否显示引用、是否保留版本、是否支持结构化项目画布、是否允许外部工具读取已批准产物。
本项目的比较维度应包括证据追溯、来源真实性标签、文档一致性验证和本地工具接入。该资料是公开信息整理，不代表完整市场研究。
""".strip(),
            },
            {
                "title": "MVP 实现证据",
                "filename": "mvp_readme.md",
                "source_type": "implementation_evidence",
                "authority": 0.85,
                "content": """
当前 MVP 已完成 Web 项目列表、项目画布、来源录入、SQLite 持久化和本地 fallback 文档生成流程。
后续实现要求：项目级 BM25 与 TF-IDF 混合检索；source_type 和 authority 字段；文档版本表；引用验证；最多两轮的质量 Loop；Markdown、JSON、DOCX 导出；本地 MCP STDIO Server。
未完成：企业 SSO、远程 MCP OAuth、真实在线协作和生产规模性能验证。
""".strip(),
            },
        ]
        for source in seed_sources:
            self.add_source(project_id=project_id, **source)
