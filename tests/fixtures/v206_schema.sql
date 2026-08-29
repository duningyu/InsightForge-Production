CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
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
    UNIQUE(document_id, version)
);
CREATE INDEX IF NOT EXISTS idx_document_versions_project ON document_versions(project_id, doc_type, version);
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
