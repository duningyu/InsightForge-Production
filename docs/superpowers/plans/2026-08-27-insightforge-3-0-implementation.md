# InsightForge 3.0 Quick Value → Evidence Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the stable InsightForge 2.0.6 Evidence Workspace into InsightForge 3.0.0: a single-path Idea-to-MVP workspace that produces domain-specific solution alternatives and a Project Snapshot first, then uses validated evidence relationships to propose visible, user-confirmed changes without mutating historical artifacts.

**Architecture:** Keep the existing FastAPI + SQLite + static Web foundation and preserve 2.0.6 source ingestion, retrieval, document versioning, bounded validation, audit, export, handoff, Function Calling, and local MCP foundations. Add an additive 3.0 domain layer (`IdeaBrief → SolutionCandidate → Decision → ProjectSnapshot`, plus `Source ↔ ProjectClaim → Decision → Artifact`) with deterministic validators and dependency propagation; LLM services only propose structured outputs, while formal decisions/snapshots remain transactional and human-confirmed.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, Pydantic v2, pytest, vanilla HTML/CSS/JavaScript, existing BM25 + TF-IDF retrieval, optional OpenAI-compatible structured LLM runtime, existing local MCP package.

**Spec:** `docs/superpowers/specs/2026-08-27-insightforge-3-0-quick-value-evidence-depth-design.md`

## Global Constraints

- Target release is exactly `3.0.0`.
- Untouched 2.0.6 baseline is `99 passed`; do not delete or weaken old tests merely to obtain green status.
- Primary user is AI product job seekers + junior/transitioning PMs; independent developers and experienced PMs are secondary.
- Top-level navigation is fixed to exactly five user tasks: `项目成果`, `方案`, `证据`, `文档`, `开发交接`.
- No mandatory Canvas, source upload, RAG screen, claim ledger, validation state, approval state, or handoff step may precede Project Snapshot v1.
- `ProjectSnapshot` is the user-facing source of truth; Canvas is a deterministic compatibility projection only.
- AI proposes; deterministic code validates and propagates; user confirmation is required for formal decisions and formal artifacts.
- `provenance` and `verification_status` are independent. `user_input` is not market validation. `simulated_research` never upgrades real-world validation state.
- Do not emit arbitrary 0–100 evidence scores or exact solution-total scores.
- Unless user-confirmed `llm_core_required=true`, every valid solution set contains at least one non-LLM/non-RAG/non-Agent core solution.
- Pairwise solution diversity passes only when at least two of six dimensions differ: mechanism, required-data class, automation level, human role, core decision logic, major implementation dependency.
- Historical Snapshot/PRD/TechDoc content is immutable; only current artifact health may change.
- Cross-project evidence/citation references fail closed.
- Evidence links require a stored project-scoped source, active source state, matching chunk, exact evidence span, and admissible source-type × claim-type policy.
- Runtime modes are exactly `llm_structured` and `deterministic_demo`; no silent fallback between them.
- No multi-agent architecture, GraphRAG, enterprise approval/RBAC, remote MCP OAuth, autonomous decision changes, or autonomous document confirmation in P0.
- All three formal transaction boundaries in the Spec must be atomic: initial solution confirmation, accepted change proposal, source archive.
- Handoff fails closed unless current Snapshot, confirmed PRD, and confirmed TechDoc are healthy.

---

## File map before implementation

Existing files that remain central:

- `app/db.py` — schema creation, additive migration helpers, DB transaction primitives.
- `app/schemas.py` — strict HTTP/AI structured contracts.
- `app/main.py` — FastAPI state wiring and HTTP routes.
- `app/services/projects.py` — project lifecycle and Canvas compatibility API.
- `app/services/sources.py` — source ingest/read lifecycle.
- `app/services/retrieval_service.py` — project-scoped retrieval and retrieval traces.
- `app/services/generation.py` — PRD/TechDoc composition.
- `app/services/loop.py` — bounded document validation/repair loop.
- `app/services/document_versions.py` — document lifecycle.
- `app/services/handoff.py` — AI Coding handoff package/readiness.
- `app/tools.py` — Function Calling registry and risk gates.
- `app/mcp_functions.py`, `app/mcp_server.py` — local MCP interface.
- `app/static/index.html`, `app/static/app.js`, `app/static/styles.css` — current Guided/Advanced UI to replace with one 3.0 shell.

New focused files:

- `app/services/ai_runtime.py` — explicit runtime-mode abstraction and structured run metadata; no silent fallback.
- `app/services/solution_design.py` — Idea interpretation/solution generation orchestration plus deterministic completeness/diversity/overengineering validators.
- `app/services/quick_start.py` — create project + IdeaBrief/refinement/confirmation API semantics.
- `app/services/decisions.py` — immutable/superseding formal project decisions.
- `app/services/snapshots.py` — transactional Snapshot creation/read/history/current pointer/derived UX state/next-best-action.
- `app/services/canvas_projection.py` — exact deterministic Snapshot → Canvas mapping and reconciliation trigger.
- `app/services/project_claims.py` — project-level Claims, evidence policy, exact-span validation, status recomputation.
- `app/services/impact.py` — deterministic claim → decision → artifact traversal, material-change detection, artifact health updates.
- `app/services/change_proposals.py` — open/accept/reject/defer lifecycle and accepted-proposal Snapshot transaction.
- `app/services/artifact_health.py` — current/needs_review/stale_evidence/superseded health store and queries.
- `app/services/legacy_migration.py` — idempotent 2.0.6 data migration and `legacy_migration` Snapshot creation.
- `app/errors.py` — explicit application exceptions such as HTTP-409 conflict and unavailable structured runtime, instead of overloading `ValueError`.
- `tests/fixtures/v206_schema.sql` — frozen 2.0.6 schema used to prove additive migration.
- `tests/fixtures/v3_golden_cases.json` — frozen P0 product cases; deterministic demo runtime consumes only these cases.

Do not split the static front end into a framework migration in P0. Retain vanilla HTML/CSS/JS and replace the current dual-mode shell in place.

### Implementation clarifications discovered while mapping the approved Spec to 2.0.6

These are implementation-level resolutions of gaps between behavioral requirements and the table sketches; they do not change the approved product semantics:

1. **Persist the validated evidence span.** Spec §12.2 and §13 require exact-span validation and restore-time revalidation, but the §10.8 table sketch omits the span. Add `evidence_span TEXT NOT NULL`, `reason TEXT NOT NULL DEFAULT ''`, and `source_sha256_at_link TEXT NOT NULL` to `project_claim_evidence_links`. Without these fields, restore-time revalidation cannot prove that the originally validated excerpt still belongs to the same immutable source identity.
2. **Persist AI-run metadata through existing audit infrastructure.** For Idea interpretation and Evidence analysis, write an `audit_events` record with `provider`, `model`, `prompt_version`, `schema_version`, `generator/analyzer_version`, `input_sha256`, `output_sha256`, `latency_ms`, `status`, and `runtime_mode`. `solution_runs` keeps its dedicated fields and also emits the same audit payload. This satisfies Spec §17 without creating an extra generalized AI-run table not present in the approved data model.
3. **P0 combination means staged combination, not free-form AI merging.** `SolutionSelectRequest` uses `strategy: "single" | "staged"` and ordered `candidate_ids`. For `staged`, `candidate_ids[0]` is the current MVP and later IDs become an explicit evolution path in `solution_json`; the system does not invent a fourth merged solution.

---

### Task 1: Establish 3.0 release identity and baseline guard

**Files:**
- Modify: `app/config.py:8-39`
- Modify: `pyproject.toml:1-30`
- Modify: `app/static/index.html` asset query strings
- Modify: `README.md` version references only
- Create: `tests/test_v3_release_identity.py`

**Interfaces:**
- Consumes: current `Settings.from_env()` and static asset contract.
- Produces: one canonical release value `3.0.0` across runtime/package/static identity; later final verification extends this check to `VERIFICATION_REPORT.md`.

- [ ] **Step 1: Write the failing release-identity test**

```python
# tests/test_v3_release_identity.py
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_is_3_0_0_across_runtime_package_and_static_assets():
    assert Settings().app_version == "3.0.0"
    assert 'version = "3.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert 'href="/static/styles.css?v=3.0.0"' in html
    assert 'src="/static/app.js?v=3.0.0"' in html
```

- [ ] **Step 2: Run the test and confirm the known 2.0.0/2.0.6 mismatch fails**

Run:

```bash
pytest tests/test_v3_release_identity.py -q
```

Expected: FAIL because `Settings().app_version` and `pyproject.toml` are `2.0.0` and static assets use `2.0.6`.

- [ ] **Step 3: Set the runtime/package/static release identity to exactly 3.0.0**

Use these exact values:

```python
# app/config.py
app_version: str = "3.0.0"
# Settings.from_env default
app_version=os.getenv("INSIGHTFORGE_APP_VERSION", "3.0.0")
```

```toml
# pyproject.toml
version = "3.0.0"
description = "Idea-to-MVP workspace with evidence-aware product decision provenance"
```

```html
<link rel="stylesheet" href="/static/styles.css?v=3.0.0">
<script src="/static/app.js?v=3.0.0" defer></script>
```

Update only explicit version strings in `README.md`; do not claim 3.0 user-test results.

- [ ] **Step 4: Run identity plus current full regression suite**

Run:

```bash
pytest tests/test_v3_release_identity.py -q
pytest -q
```

Expected at this point: identity test PASS; the old suite should still report 99 legacy tests passing plus the new identity test. If any old test fails only because it hardcodes `2.0.6` static identity, update that old test in the same commit to assert `3.0.0` and document the semantic reason in the commit message; do not weaken unrelated assertions.

- [ ] **Step 5: Commit the release foundation**

```bash
git add app/config.py pyproject.toml app/static/index.html README.md tests/test_v3_release_identity.py tests/test_v2_ui_contract.py
git commit -m "chore: establish InsightForge 3.0 release identity"
```

---

### Task 2: Add transactional database primitives and additive 3.0 schema

**Files:**
- Modify: `app/db.py:56-430`
- Create: `tests/fixtures/v206_schema.sql`
- Create: `tests/test_v3_schema_migration.py`

**Interfaces:**
- Consumes: current `Database.connect()`, `_ensure_column()`, `_migrate_schema()`.
- Produces:
  - `Database.insert_audit_tx(connection, *, actor, action, entity_type, entity_id, payload) -> str`
  - all Spec §10 tables/columns;
  - rerunnable fresh/legacy schema migration.

- [ ] **Step 1: Freeze the exact 2.0.6 schema into a fixture**

Copy the pre-3.0 `SCHEMA_SQL` definition from the baseline package into `tests/fixtures/v206_schema.sql`. It must include the old `projects`, Canvas, sources/chunks, document, guided, project_decisions, retrieval, document claims, handoff, and audit tables but none of the new 3.0 tables/columns.

- [ ] **Step 2: Write failing fresh-schema and 2.0.6 migration tests**

```python
# tests/test_v3_schema_migration.py
from pathlib import Path
import sqlite3

from app.db import Database

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "idea_briefs", "solution_runs", "solution_candidates", "project_claims",
    "project_claim_evidence_links", "decision_claim_links", "project_snapshots",
    "snapshot_claim_links", "snapshot_decision_links", "change_proposals",
    "artifact_dependencies", "artifact_health",
}


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_schema_contains_all_v3_tables(tmp_path):
    db = Database(tmp_path / "fresh.sqlite3")
    db.init_schema()
    assert EXPECTED_TABLES <= _tables(db.path)
    columns = {row[1] for row in sqlite3.connect(db.path).execute("PRAGMA table_info(projects)")}
    assert "current_snapshot_id" in columns


def test_v206_schema_migrates_additively_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript((ROOT / "tests/fixtures/v206_schema.sql").read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES('p1','Legacy','Old project','active','t','t')"
        )
    db = Database(path)
    db.init_schema()
    db.init_schema()
    assert EXPECTED_TABLES <= _tables(path)
    assert db.fetch_one("SELECT title FROM projects WHERE id='p1'") == {"title": "Legacy"}
```

- [ ] **Step 3: Run the migration tests to verify failure**

Run:

```bash
pytest tests/test_v3_schema_migration.py -q
```

Expected: FAIL because the 3.0 tables and `projects.current_snapshot_id` do not exist.

- [ ] **Step 4: Add the exact 3.0 tables and indexes to `SCHEMA_SQL`**

Implement the Spec §10 schemas, including `CHECK` constraints for fixed P0 enums where SQLite can enforce them. Add the three evidence-link implementation columns declared above (`evidence_span`, `reason`, `source_sha256_at_link`) because later restore semantics require them. Add `current_snapshot_id TEXT` through `_ensure_column()` so an old DB can migrate. Do not drop or rewrite legacy tables.

At minimum add indexes for:

```sql
CREATE INDEX IF NOT EXISTS idx_idea_briefs_project ON idea_briefs(project_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_solution_runs_project ON solution_runs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_solution_candidates_run ON solution_candidates(run_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_project_claims_project ON project_claims(project_id, status, criticality);
CREATE INDEX IF NOT EXISTS idx_change_proposals_project ON change_proposals(project_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_dependencies_dependency ON artifact_dependencies(dependency_type, dependency_id);
```

- [ ] **Step 5: Add transaction-safe audit insertion**

Refactor `insert_audit()` to reuse a connection-aware helper:

```python
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
        "INSERT INTO audit_events(id,actor,action,entity_type,entity_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
        (event_id, actor, action, entity_type, entity_id,
         json.dumps(payload or {}, ensure_ascii=False), utc_now()),
    )
    return event_id


def insert_audit(self, actor: str, action: str, entity_type: str, entity_id: str,
                 payload: dict[str, Any] | None = None) -> str:
    with self.connect() as connection:
        return self.insert_audit_tx(
            connection, actor=actor, action=action, entity_type=entity_type,
            entity_id=entity_id, payload=payload,
        )
```

This helper is mandatory for the later atomic Snapshot/change/archive transactions.

- [ ] **Step 6: Run schema and legacy DB tests**

Run:

```bash
pytest tests/test_v3_schema_migration.py tests/test_db.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the additive schema foundation**

```bash
git add app/db.py tests/fixtures/v206_schema.sql tests/test_v3_schema_migration.py
git commit -m "feat: add InsightForge 3.0 additive schema"
```

---

### Task 3: Define strict AI runtime contracts and deterministic solution validators

**Files:**
- Modify: `app/schemas.py:1-100`
- Create: `app/services/ai_runtime.py`
- Create: `app/services/solution_design.py`
- Create: `tests/fixtures/v3_golden_cases.json`
- Create: `tests/test_v3_solution_design.py`

**Interfaces:**
- Consumes: `StrictModel`, optional OpenAI dependency, `solution_runs`/`solution_candidates` schema.
- Produces:
  - `RuntimeMode = Literal["llm_structured", "deterministic_demo"]`
  - `IdeaBriefDraft`, `SolutionCandidateDraft`, `SolutionSetDraft`
  - `StructuredAIRuntime.interpret_idea(...)`
  - `StructuredAIRuntime.design_solutions(...)`
  - `validate_solution_set(candidates, *, llm_core_required) -> list[SolutionCandidateDraft]`
  - explicit runtime metadata; no silent fallback.

- [ ] **Step 1: Add failing strict-schema and validator tests**

Tests must cover completeness, pairwise diversity, non-AI baseline, two-candidate fallback, and no silent runtime fallback. Use a compact candidate builder with all required fields and these exact diversity dimensions:

```python
DIVERSITY_FIELDS = (
    "mechanism", "required_data_class", "automation_level", "human_role",
    "core_decision_logic", "major_dependency",
)
```

Example required assertions:

```python
def test_pairwise_candidates_need_two_material_dimension_differences():
    candidates = [candidate("rule_based", "inventory", "low", "confirm", "threshold", "sqlite"),
                  candidate("rule_based", "inventory", "low", "confirm", "threshold", "fastapi")]
    with pytest.raises(ValueError, match="SOLUTION_DIVERSITY_FAILED"):
        validate_solution_set(candidates, llm_core_required=False)


def test_default_set_requires_non_llm_core_solution():
    candidates = [llm_candidate("assistant"), llm_candidate("search_retrieval")]
    with pytest.raises(ValueError, match="OVERENGINEERED_SOLUTION_SET"):
        validate_solution_set(candidates, llm_core_required=False)
```

- [ ] **Step 2: Run the tests and confirm failure**

```bash
pytest tests/test_v3_solution_design.py -q
```

Expected: FAIL because contracts/runtime/validators do not exist.

- [ ] **Step 3: Extend `app/schemas.py` with strict P0 request/output models**

Add strict request models needed later (`QuickStartRequest`, `IdeaBriefRefineRequest`, `HumanConfirmRequest`, `SolutionSelectRequest`) and structured AI output models. Define solution selection exactly as `strategy: Literal["single", "staged"]`, `candidate_ids: list[str]` with 1–3 IDs, `rationale: str`, and `human_confirmed: bool`; `single` requires exactly one ID and `staged` requires at least two ordered IDs. `SolutionCandidateDraft` must contain every field in Spec §7.1 plus explicit validator dimensions:

```python
class SolutionCandidateDraft(StrictModel):
    title: str
    mechanism: Literal[
        "rule_based", "workflow_based", "prediction_based", "recommendation_based",
        "optimization", "search_retrieval", "automation", "human_in_the_loop",
        "assistant", "marketplace", "other",
    ]
    summary: str
    why_fit: str
    user_flow: list[str]
    mvp_pages: list[str]
    features: list[str]
    inputs: list[str]
    outputs: list[str]
    decision_logic: list[str]
    data_requirements: list[str]
    technical_components: list[str]
    implementation_plan: list[str]
    acceptance_cases: list[str]
    risks: list[str]
    unknowns: list[str]
    complexity: Literal["low", "medium", "high"]
    provenance: Literal["model_hypothesis", "user_input"]
    required_data_class: str
    automation_level: Literal["low", "medium", "high"]
    human_role: str
    core_decision_logic: str
    major_dependency: str
    requires_llm_runtime: bool
    requires_rag_runtime: bool
    requires_agent_runtime: bool
```

- [ ] **Step 4: Implement `ai_runtime.py` with explicit adapters**

Define a protocol and two concrete runtimes. The deterministic runtime reads frozen fixtures only and returns an explicit unsupported error for unknown cases rather than pretending to semantically understand arbitrary ideas.

```python
class StructuredAIRuntime(Protocol):
    mode: str
    provider: str
    model: str
    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft: ...
    def design_solutions(self, brief: IdeaBriefDraft) -> SolutionSetDraft: ...
    def analyze_evidence(self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
```

`build_structured_runtime()` selects from configuration and raises an explicit runtime error when `llm_structured` is requested but unavailable. It must not catch the failure and return deterministic fixtures silently. Add `build_ai_trace_payload(...) -> dict[str, Any]` so Idea/Solution/Evidence/Document paths persist the exact Spec §17 metadata consistently through `audit_events` rather than inventing different field names in each service.

- [ ] **Step 5: Implement deterministic completeness/diversity/overengineering validators**

Use pairwise comparison across the six specified fields. If three fail, allow one regeneration callback; after that return two valid candidates if possible. Do not pass fewer than two.

- [ ] **Step 6: Create frozen deterministic demo cases**

`tests/fixtures/v3_golden_cases.json` must include at least:

- convenience-store replenishment with rule / forecast / human-confirmed forecast;
- a non-AI workflow problem where an LLM-only set is invalid;
- a genuinely ambiguous school-selection idea requiring one clarification;
- a case with only two materially different valid solutions.

Fixture records must label all inferred market statements `model_hypothesis`.

- [ ] **Step 7: Run validator/runtime tests**

```bash
pytest tests/test_v3_solution_design.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit AI contracts and validators**

```bash
git add app/schemas.py app/services/ai_runtime.py app/services/solution_design.py tests/fixtures/v3_golden_cases.json tests/test_v3_solution_design.py
git commit -m "feat: add structured quick-value AI contracts"
```

---

### Task 4: Implement Quick Start and IdeaBrief lifecycle

**Files:**
- Create: `app/services/quick_start.py`
- Create: `app/errors.py`
- Modify: `app/main.py:46-240`
- Modify: `app/services/projects.py:10-76`
- Create: `tests/test_v3_quick_start.py`

**Interfaces:**
- Consumes: `QuickStartRequest`, `StructuredAIRuntime`, `idea_briefs` table, `ProjectService.create_project()`.
- Produces:
  - `QuickStartService.quick_start(payload, actor) -> dict`
  - `get_brief(project_id)`
  - `confirm_brief(project_id, *, human_confirmed, actor)`
  - `refine_brief(project_id, patch, actor)`
  - routes from Spec §20.1–20.2.

- [ ] **Step 1: Write failing service/API tests**

Tests must assert:

```python
def test_quick_start_creates_project_and_inferred_brief_without_canvas_or_guide(client):
    response = client.post("/api/projects/quick-start", json={
        "idea": "帮小型便利店减少缺货", "target_user": None,
        "resources": [], "priority": "fast_mvp",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["idea_brief"]["confirmation_status"] == "inferred"
    assert body["idea_brief"]["provenance"]["problem"] == "model_hypothesis"
    assert body["clarification_required"] is False
    project_id = body["project_id"]
    assert client.get(f"/api/projects/{project_id}/canvas").status_code == 404
    assert client.app.state.db.fetch_one(
        "SELECT id FROM guided_sessions WHERE project_id = ?", (project_id,)
    ) is None
```

and:

```python
def test_confirming_brief_does_not_upgrade_provenance_to_market_evidence(client):
    project_id = create_quick_project(client)
    response = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "理解准确"},
    )
    assert response.status_code == 200
    assert response.json()["confirmation_status"] == "confirmed"
    assert "model_hypothesis" in response.json()["provenance"].values()
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_quick_start.py -q
```

- [ ] **Step 3: Implement `QuickStartService`**

`quick_start()` must:

1. create a normal project row;
2. call the configured structured runtime for an `IdeaBriefDraft`;
3. persist `idea_briefs.version=1` with `confirmation_status='inferred'`;
4. store the complete Spec §17 trace in an `audit_events` payload: provider, model, prompt_version, schema_version, interpreter_version, input_sha256, output_sha256, latency_ms, status, runtime_mode;
5. not create Canvas, guided session, solution decision, or Snapshot.

If clarification is required, store the inferred brief plus one `clarification_question`; do not ask additional blocking questions unless the user explicitly chooses refine.

- [ ] **Step 4: Add 3.0 routes and application state wiring**

Wire one structured runtime and `QuickStartService` in FastAPI lifespan, then implement exact routes:

```text
POST /api/projects/quick-start
GET  /api/projects/{project_id}/idea-brief
POST /api/projects/{project_id}/idea-brief/confirm
POST /api/projects/{project_id}/idea-brief/refine
```

Create `ConflictError` and `StructuredRuntimeUnavailableError` in `app/errors.py`; map them in `app/main.py` to HTTP 409 and 503 respectively. Return HTTP 403 when `human_confirmed` is false for confirmation; use `ConflictError` when confirming a superseded brief. Do not map these semantics through generic 422 `ValueError`.

- [ ] **Step 5: Run API and old project tests**

```bash
pytest tests/test_v3_quick_start.py tests/test_api.py tests/test_v2_project_lifecycle.py -q
```

Expected: PASS without creating legacy guided rows for quick-start projects.

- [ ] **Step 6: Commit Quick Start**

```bash
git add app/services/quick_start.py app/errors.py app/main.py app/services/projects.py tests/test_v3_quick_start.py
git commit -m "feat: add quick-start IdeaBrief flow"
```

---

### Task 5: Persist solution runs/candidates and expose generation APIs

**Files:**
- Modify: `app/services/solution_design.py`
- Create: `app/services/decisions.py`
- Modify: `app/main.py`
- Create: `tests/test_v3_solution_api.py`

**Interfaces:**
- Consumes: confirmed IdeaBrief, `StructuredAIRuntime.design_solutions()`, validators.
- Produces:
  - `SolutionDesignService.generate(project_id, actor) -> dict`
  - `SolutionDesignService.list_candidates(project_id) -> dict`
  - formal solution-selection proposal through `DecisionService`; Snapshot creation is Task 6.

- [ ] **Step 1: Write failing persistence/API tests**

Assert that generation:

- rejects unconfirmed IdeaBrief with 409;
- persists one `solution_runs` row and 2–3 `solution_candidates` rows;
- records provider/model/prompt/schema/generator versions, input/output SHA-256, status, runtime mode in trace metadata;
- returns no exact aggregate score;
- contains one non-LLM core candidate unless `llm_core_required=true`;
- produces convenience-store candidates whose mechanisms include a rule-based baseline and a prediction/human decision alternative, not the legacy three InsightForge workflow forms.

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_solution_api.py -q
```

- [ ] **Step 3: Implement solution run persistence and one-regeneration policy**

The service must persist the raw structured output hash before validator outcomes, then update run status to one of:

```text
completed
completed_two_candidates
failed_diversity
failed_overengineering
failed_schema
```

Never fabricate a third candidate merely to satisfy UI cardinality.

- [ ] **Step 4: Add generation/list endpoints**

```text
POST /api/projects/{project_id}/solutions/generate
GET  /api/projects/{project_id}/solutions
```

The list response must identify the latest run and keep prior runs inspectable through audit/advanced debugging but not as top-level UI state.

- [ ] **Step 5: Add `DecisionService` proposal primitive**

Define:

```python
class DecisionService:
    def propose_solution_selection(
        self, *, connection: sqlite3.Connection, project_id: str,
        option_ids: list[str], selected_option_id: str, rationale: str,
        decision_payload: dict[str, Any], actor: str,
    ) -> dict[str, Any]:
        ...
```

This helper inserts a proposed row only; it does not confirm or update project state yet.

- [ ] **Step 6: Run solution API tests plus legacy proposal tests**

```bash
pytest tests/test_v3_solution_api.py tests/test_v2_solution_proposals.py -q
```

Legacy tests remain readable until Task 13 retires their UI semantics.

- [ ] **Step 7: Commit solution generation**

```bash
git add app/services/solution_design.py app/services/decisions.py app/main.py tests/test_v3_solution_api.py
git commit -m "feat: persist domain-specific solution candidates"
```

---

### Task 6: Implement atomic solution confirmation, Snapshot v1, project Claims, and Canvas projection

**Files:**
- Create: `app/services/canvas_projection.py`
- Create: `app/services/project_claims.py`
- Create: `app/services/snapshots.py`
- Modify: `app/services/decisions.py`
- Modify: `app/services/projects.py:154-235`
- Modify: `app/main.py`
- Create: `tests/test_v3_snapshot_transaction.py`

**Interfaces:**
- Consumes: one confirmed IdeaBrief, latest valid solution candidates, DB transaction helper.
- Produces:
  - `CanvasProjectionService.project(snapshot_payload) -> CanvasProjection`
  - `ProjectClaimService.create_initial_claims_tx(connection, ...)`
  - `SnapshotService.confirm_initial_solution(...) -> ProjectSnapshot`
  - `SnapshotService.get_current(project_id)` / `list_versions(project_id)` / `get(snapshot_id)`
  - routes from Spec §20.3–20.4.

- [ ] **Step 1: Write failing transaction and immutability tests**

Cover all required atomic writes:

```python
def test_confirm_solution_atomically_creates_decision_claims_snapshot_pointer_canvas_and_audit(db):
    # Arrange confirmed brief + valid candidates.
    # Act through SnapshotService.confirm_initial_solution(..., human_confirmed=True).
    # Assert decision.status == 'confirmed'.
    # Assert project_claims exist with separate provenance/verification_status.
    # Assert project_snapshots.version == 1 and snapshot_origin == 'quick_value_flow'.
    # Assert projects.current_snapshot_id points at v1.
    # Assert project_canvas and project_canvas_versions were projected from the Snapshot.
    # Assert a same-transaction audit event exists.
```

Add a failure-injection test that raises after decision insert and proves no decision/snapshot/Canvas/audit partial writes remain.

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_snapshot_transaction.py -q
```

- [ ] **Step 3: Extract one connection-aware Canvas writer and build projection service**

Refactor `ProjectService.update_canvas()` so both legacy direct writes and Snapshot projection use the same low-level function:

```python
def write_canvas_tx(
    self,
    connection: sqlite3.Connection,
    project_id: str,
    *, problem: str, target_users: str, goals: list[str], non_goals: list[str],
    success_metrics: list[str], constraints: list[str], now: str,
) -> dict[str, Any]:
    ...
```

`CanvasProjectionService` must use the exact Spec mapping and must not infer missing content.

- [ ] **Step 4: Implement initial project Claim extraction deterministically from selected Snapshot fields**

Create only five P0 claim types. Initial examples:

```text
target_user  <- Snapshot target user
user_problem <- Snapshot core problem
value        <- selected solution value hypothesis
feasibility  <- each critical data/technical dependency
behavior     <- only when IdeaBrief explicitly contains current-user behavior
```

All unverified AI-inferred claims begin `verification_status='unverified'`; user confirmation does not change that.

- [ ] **Step 5: Implement `SnapshotService.confirm_initial_solution()` as one DB transaction**

Inside one `with db.connect() as connection:` block:

1. verify `human_confirmed=True`;
2. verify current confirmed IdeaBrief and selected candidate scope;
3. insert/confirm immutable `project_decisions` row with `decision_type='solution_selection'` and `decision_version=1`;
4. create initial project claims and `decision_claim_links`;
5. compute deterministic next-best-action from claim criticality/status/dependency count;
6. insert `project_snapshots.version=1`, relation rows, SHA-256;
7. update `projects.current_snapshot_id`;
8. create Canvas projection/version;
9. insert audit event through `insert_audit_tx()`.

- [ ] **Step 6: Add solution-select and Snapshot read routes**

```text
POST /api/projects/{project_id}/solutions/select
GET  /api/projects/{project_id}/snapshot
GET  /api/projects/{project_id}/snapshots
GET  /api/project-snapshots/{snapshot_id}
```

`SolutionSelectRequest` must require `human_confirmed=true`. For `strategy='single'`, persist the sole candidate as the current solution. For `strategy='staged'`, persist `candidate_ids[0]` as the current MVP and the remaining ordered candidates as `solution_json.evolution_path`; do not synthesize a new fourth solution.

- [ ] **Step 7: Fail closed on direct 3.0 Canvas edits until reconciliation exists**

Until Task 9 provides `ArtifactHealthService` and `ChangeProposalService`, `PUT /api/projects/{project_id}/canvas` must reject writes for projects with `current_snapshot_id` using HTTP 409 `SNAPSHOT_MANAGED_CANVAS`. Legacy projects without a 3.0 Snapshot keep the existing direct Canvas API. Task 9 replaces this temporary fail-closed rule with the final Spec behavior: write Canvas + mark Snapshot `needs_review` + create `snapshot_canvas_reconciliation` proposal.

- [ ] **Step 8: Run transaction/Canvas/API tests**

```bash
pytest tests/test_v3_snapshot_transaction.py tests/test_v2_project_lifecycle.py tests/test_api.py -q
```

- [ ] **Step 9: Commit Snapshot v1 foundation**

```bash
git add app/services/canvas_projection.py app/services/project_claims.py app/services/snapshots.py app/services/decisions.py app/services/projects.py app/main.py tests/test_v3_snapshot_transaction.py
git commit -m "feat: create immutable Project Snapshot from solution choice"
```

---

### Task 7: Replace the dual-mode UI with the five-module Quick Value shell

**Files:**
- Replace primary markup in: `app/static/index.html`
- Refactor: `app/static/app.js`
- Refactor: `app/static/styles.css`
- Replace semantics in: `tests/test_v2_ui_contract.py`
- Create: `tests/test_v3_ui_quick_value_contract.py`

**Interfaces:**
- Consumes: Quick Start, IdeaBrief, solutions, Snapshot routes from Tasks 4–6.
- Produces: one UI shell with exactly five top-level modules and no Guided/Advanced mode switch.

- [ ] **Step 1: Write failing 3.0 UI contract tests before markup changes**

```python
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app/static"


def test_v3_has_exactly_five_primary_nav_tasks_and_no_dual_mode_toggle():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for label in ("项目成果", "方案", "证据", "文档", "开发交接"):
        assert label in html
    for forbidden in ("新手引导", "高级工作台", "RAG 检索", "主张账本", "人工审批"):
        assert forbidden not in html
    assert 'id="mode-toggle"' not in html


def test_first_screen_accepts_one_idea_before_project_navigation():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="quick-start-form"' in html
    assert 'id="quick-start-idea"' in html
    assert 'id="project-shell"' in html
```

- [ ] **Step 2: Run the UI contract and confirm it fails on 2.0.6 markup**

```bash
pytest tests/test_v3_ui_quick_value_contract.py -q
```

- [ ] **Step 3: Replace the top-level HTML shell**

Required structure:

```html
<section id="quick-start-view">
  <form id="quick-start-form">
    <textarea id="quick-start-idea" required></textarea>
    <input id="quick-start-target-user" type="text">
    <textarea id="quick-start-resources"></textarea>
    <select id="quick-start-priority">
      <option value="fast_mvp">最快 MVP</option>
      <option value="lowest_cost">最低成本</option>
      <option value="strongest_value">产品价值</option>
      <option value="portfolio_signal">作品集表达</option>
    </select>
    <button type="submit">生成项目方案</button>
  </form>
</section>
<section id="project-shell" class="hidden">
  <aside id="primary-nav">
    <button data-view="snapshot">项目成果</button>
    <button data-view="solutions">方案</button>
    <button data-view="evidence">证据</button>
    <button data-view="documents">文档</button>
    <button data-view="handoff">开发交接</button>
  </aside>
  <main id="project-content"></main>
</section>
```

Do not retain a hidden Guided/Advanced toggle in the new primary markup.

- [ ] **Step 4: Refactor JS state to page-oriented 3.0 state**

Replace `state.mode`, Guided steps, and advanced-view switching with:

```javascript
const state = {
  projects: [],
  currentProjectId: null,
  activeView: "snapshot",
  ideaBrief: null,
  solutions: null,
  snapshot: null,
  sources: [],
  claims: [],
  impacts: [],
  documents: [],
  handoff: null,
  runtimeMode: null,
};
```

Implement the first-value loop: quick start → show Idea Brief confirmation → generate solutions → show comparison/recommendation → select → show Snapshot.

- [ ] **Step 5: Implement Snapshot first viewport and one primary next action**

The renderer must expose project one-liner, selected solution, MVP, largest uncertainty, and one primary `Next Best Action`. Source/claim/document counts must not be the first-view hierarchy.

- [ ] **Step 6: Implement Solutions cards with compact and expandable detail**

Compact cards show only title, plain-language mechanism, fit, difficulty, data requirement, primary risk. Expandable detail shows flow/pages/features/inputs/outputs/logic/data/technical plan/two-week plan/acceptance cases/unknowns.

- [ ] **Step 7: Add responsive sidebar behavior**

CSS requirements:

```css
@media (max-width: 1199px) { /* compact nav */ }
@media (max-width: 760px) { /* drawer nav; main width 100%; overflow-x hidden only after layout is intrinsically responsive */ }
```

Do not solve horizontal overflow by clipping inaccessible content; cards/tables must wrap or scroll locally.

- [ ] **Step 8: Replace old v2 UI tests only where semantics were intentionally removed**

Keep accessibility/static-asset assertions that remain valid. Replace assertions for Guided Mode, Advanced Workspace, old six-step rail, primary RAG nav, and old solution templates with 3.0 contracts. In test comments, state that they are intentionally superseded by Spec §9.

- [ ] **Step 9: Run static UI contracts and full browser-independent API regressions**

```bash
pytest tests/test_v3_ui_quick_value_contract.py tests/test_v2_ui_contract.py tests/test_api.py -q
```

- [ ] **Step 10: Commit the 3.0 UI shell**

```bash
git add app/static/index.html app/static/app.js app/static/styles.css tests/test_v2_ui_contract.py tests/test_v3_ui_quick_value_contract.py
git commit -m "feat: replace dual-mode UI with quick-value workspace"
```

---

### Task 8: Implement project-level Claim evidence policy and exact-span validation

**Files:**
- Expand: `app/services/project_claims.py`
- Create: `tests/test_v3_project_claim_evidence.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: project Claims, active project-scoped Sources/Chunks, retrieval service.
- Produces:
  - `ProjectClaimService.list_claims(project_id)`
  - `validate_relation_proposal(...)`
  - `persist_relation(...)`
  - `recompute_status_tx(connection, claim_id) -> str`
  - source-type × claim-type admissibility policy.

- [ ] **Step 1: Write failing evidence-policy tests**

Required cases:

```python
def test_exact_span_must_exist_in_same_project_chunk(...): ...
def test_cross_project_source_or_chunk_is_rejected(...): ...
def test_simulated_research_never_upgrades_real_validation(...): ...
def test_implementation_evidence_may_support_feasibility_but_not_user_value(...): ...
def test_two_independent_direct_sources_can_produce_supported_with_scope_notes(...): ...
def test_support_and_direct_contradiction_from_different_sources_produce_conflict(...): ...
def test_source_archived_between_analysis_and_commit_is_rejected(...): ...
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_project_claim_evidence.py -q
```

- [ ] **Step 3: Implement explicit qualitative admissibility policy**

Represent policy as data, not free-form LLM judgment. Example:

```python
ADMISSIBILITY = {
    "real_user_research": {"target_user", "user_problem", "behavior", "value", "feasibility"},
    "public_source": {"target_user", "user_problem", "behavior", "value", "feasibility"},
    "user_input": set(),
    "model_hypothesis": set(),
    "implementation_evidence": {"feasibility"},
    "simulated_research": set(),
}
```

`public_source` and `real_user_research` still require scope/directness rules; membership means “eligible for relation validation,” not “automatically strong evidence.”

- [ ] **Step 4: Implement exact evidence-span validation with one documented normalization rule**

Use normalization that only standardizes line endings and surrounding whitespace; it must not fuzzy-match paraphrases. Persist relation only if the exact normalized span exists in the stored chunk.

- [ ] **Step 5: Implement Spec §12.5 status recomputation using independent source IDs**

Do not count multiple chunks from one source as independent support. Set `scope_note` before a claim can become `supported`.

- [ ] **Step 6: Add project-scoped Evidence Analyzer flow and API routes**

For each requested Claim, call `ProjectRetrievalService.execute_retrieval(..., purpose="evidence_analysis")`, pass only returned project-scoped chunks to `StructuredAIRuntime.analyze_evidence()`, then pass every proposed relation through the deterministic gates before persistence. The runtime never receives unscoped global chunks.

```text
GET  /api/projects/{project_id}/claims
GET  /api/projects/{project_id}/claims/{claim_id}
POST /api/projects/{project_id}/evidence/analyze
GET  /api/projects/{project_id}/evidence/impact
```

At this task, `/evidence/analyze` persists only validated relation links and returns status changes; Change Proposal creation is Task 9. Every analyzer run must also emit the complete Spec §17 trace to `audit_events`, including input/output SHA-256 and explicit runtime mode. Before committing a relation, re-read source status inside the write transaction so a source archived during model analysis is rejected.

- [ ] **Step 7: Run evidence tests plus existing retrieval isolation tests**

```bash
pytest tests/test_v3_project_claim_evidence.py tests/test_retrieval.py tests/test_v2_retrieval_trace.py tests/test_v2_claim_ledger.py -q
```

- [ ] **Step 8: Commit project-level evidence semantics**

```bash
git add app/services/project_claims.py app/main.py tests/test_v3_project_claim_evidence.py
git commit -m "feat: validate project claim evidence relationships"
```

---

### Task 9: Implement deterministic Impact Resolver, artifact health, and Change Proposals

**Files:**
- Create: `app/services/artifact_health.py`
- Create: `app/services/impact.py`
- Create: `app/services/change_proposals.py`
- Modify: `app/services/snapshots.py`
- Modify: `app/main.py`
- Create: `tests/test_v3_change_proposals.py`

**Interfaces:**
- Consumes: claim status changes, `decision_claim_links`, Snapshot/document dependencies.
- Produces:
  - `ArtifactHealthService.get/set/recompute`
  - `ImpactResolver.resolve_claim_change_tx(...)`
  - `ChangeProposalService.list_for_project()`
  - `accept/reject/defer()`
  - accepted proposal creates Snapshot vN+1 transactionally.

- [ ] **Step 1: Write failing material-change and proposal lifecycle tests**

Cover exactly:

- low-value contextual evidence does not create a proposal;
- critical assumption → `conflict` creates one open proposal;
- accept requires `human_confirmed=true` and creates Snapshot v2, superseding decision/claim rows as required;
- reject and defer leave `projects.current_snapshot_id` unchanged;
- accept against non-current `from_snapshot_id` returns conflict/raises a stale-proposal exception mapped to HTTP 409;
- historical Snapshot v1 content/SHA remains byte-for-byte unchanged;
- derived UX state is `exploring` without a confirmed Snapshot, `executable` with a healthy current Snapshot and no material blocker, and `reconfirm_required` when a material proposal is open or a critical artifact is stale.

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_change_proposals.py -q
```

- [ ] **Step 3: Implement `ArtifactHealthService`**

Health values are exactly:

```text
current
needs_review
stale_evidence
superseded
```

The service stores health separately from artifact content. Creating a new current Snapshot marks the prior Snapshot health `superseded` but never updates its content.

- [ ] **Step 4: Implement deterministic dependency traversal and material-change rule**

`ImpactResolver` performs SQL traversal only:

```text
claim_id -> decision_claim_links -> confirmed decisions
          -> snapshot_decision_links / artifact_dependencies
          -> artifact_health
```

LLM is optional only for `summary`, `reason`, and `suggested_changes` prose. Dependency existence and materiality follow Spec §12.6–12.7 deterministic rules. Add `SnapshotService.derive_project_state(project_id) -> Literal["exploring", "executable", "reconfirm_required"]`; it computes presentation state from current Snapshot, open material proposals, and artifact health and never persists a workflow enum to `projects.status`.

- [ ] **Step 5: Implement accepted Change Proposal as one transaction**

Validate that `from_snapshot_id == projects.current_snapshot_id` at commit time. Then in one transaction:

1. mark proposal accepted;
2. create superseding formal decision/claim rows if payload requires them;
3. create Snapshot vN+1 with `snapshot_origin='change_proposal'`;
4. create Snapshot relation rows;
5. update current pointer;
6. mark old/current artifact health correctly;
7. project Canvas;
8. audit.

Reject/defer only change proposal status/audit.

- [ ] **Step 6: Add change-proposal routes**

```text
GET  /api/projects/{project_id}/change-proposals
POST /api/change-proposals/{proposal_id}/accept
POST /api/change-proposals/{proposal_id}/reject
POST /api/change-proposals/{proposal_id}/defer
```

- [ ] **Step 7: Complete direct Canvas reconciliation behavior from Task 6**

Replace Task 6's temporary `SNAPSHOT_MANAGED_CANVAS` rejection. A direct Canvas edit on a 3.0 project now completes the compatibility Canvas write, sets current Snapshot health `needs_review`, and creates exactly one open `snapshot_canvas_reconciliation` proposal for that Canvas version, all in one transaction.

- [ ] **Step 8: Run proposal/Snapshot regression tests**

```bash
pytest tests/test_v3_change_proposals.py tests/test_v3_snapshot_transaction.py -q
```

- [ ] **Step 9: Commit Impact/Change Proposal engine**

```bash
git add app/services/artifact_health.py app/services/impact.py app/services/change_proposals.py app/services/snapshots.py app/main.py tests/test_v3_change_proposals.py
git commit -m "feat: add evidence impact and change proposals"
```

---

### Task 10: Add source archive/restore propagation as one atomic lifecycle operation

**Files:**
- Modify: `app/services/sources.py:11-160`
- Modify: `app/services/project_claims.py`
- Modify: `app/services/impact.py`
- Modify: `app/main.py:239-293`
- Create: `tests/test_v3_source_lifecycle.py`

**Interfaces:**
- Consumes: SourceService, project claim evidence links, ImpactResolver.
- Produces:
  - `SourceService.archive(project_id, source_id, actor) -> dict`
  - `SourceService.restore(project_id, source_id, actor) -> dict`
  - API routes from Spec §13.

- [ ] **Step 1: Write failing atomic archive/restore tests**

Required assertions:

- wrong project/source pairing fails closed;
- archive sets `sources.status='archived'`;
- all dependent `project_claim_evidence_links.active=0` in the same transaction;
- claim status recomputes to `stale`, `limited_support`, `supported`, or `contradicted` using remaining active evidence;
- critical material change creates a proposal;
- dependent artifacts become `stale_evidence`/`needs_review` without content mutation;
- restore revalidates source/chunk integrity before reactivating links;
- failure injection during propagation rolls back source status and links.

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_source_lifecycle.py -q
```

- [ ] **Step 3: Implement archive transaction**

Within one DB transaction:

```text
validate project/source scope
→ source.status='archived'
→ evidence links active=0
→ recompute affected claims
→ resolve impacts/artifact health
→ create material Change Proposal if required
→ audit
```

Do not delete source chunks or historical document claim links.

- [ ] **Step 4: Implement restore transaction with revalidation**

Before reactivating each project-level evidence link, verify source SHA identity, chunk ownership/content, and exact evidence span under the same rules as Task 8. Invalid old links remain inactive and are reported.

- [ ] **Step 5: Add archive/restore HTTP routes**

```text
POST /api/projects/{project_id}/sources/{source_id}/archive
POST /api/projects/{project_id}/sources/{source_id}/restore
```

Return impact summary: affected claims, proposal IDs, artifact health changes.

- [ ] **Step 6: Run source/retrieval regression tests**

```bash
pytest tests/test_v3_source_lifecycle.py tests/test_ingestion.py tests/test_retrieval.py tests/test_v2_source_guidance.py -q
```

- [ ] **Step 7: Commit source propagation**

```bash
git add app/services/sources.py app/services/project_claims.py app/services/impact.py app/main.py tests/test_v3_source_lifecycle.py
git commit -m "feat: propagate source archive and restore impacts"
```

---

### Task 11: Make PRD/TechDoc generation Snapshot-aware and add document health + confirmation alias

**Files:**
- Modify: `app/services/generation.py`
- Modify: `app/services/loop.py`
- Modify: `app/services/document_versions.py`
- Modify: `app/tools.py:93-400`
- Modify: `app/main.py:337-468`
- Modify: `app/schemas.py`
- Create: `tests/test_v3_document_health.py`

**Interfaces:**
- Consumes: current confirmed Snapshot, project Claims, active admissible Evidence, Canvas projection, ArtifactHealthService.
- Produces:
  - preferred `POST /api/projects/{project_id}/documents/generate`
  - `POST /api/document-versions/{version_id}/confirm`
  - deprecated approve alias with identical gate/audit semantics;
  - document dependency rows/health records.

- [ ] **Step 1: Write failing document input/health/confirmation tests**

Tests must prove:

- 3.0 generation fails when no current confirmed Snapshot exists;
- generated version records dependencies on current Snapshot and cited project Claims/evidence where applicable;
- confirming a checked version requires explicit human confirmation;
- `/approve` and `/confirm` call the same service semantics but user-facing audit action uses confirmation language;
- after a supporting source is archived, historical content/approval timestamp stay unchanged while `artifact_health='stale_evidence'`;
- current UI/API never reports stale PRD as healthy merely because `validation_status='passed'`.

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_document_health.py -q
```

- [ ] **Step 3: Build a Snapshot-aware document context adapter**

Do not rewrite the whole existing generator. Before `DocumentLoop.run()`, assemble:

```python
context = {
    "snapshot": current_snapshot,
    "project_claims": active_project_claims,
    "evidence": admissible_evidence,
    "canvas": compatibility_canvas,
}
```

Keep existing citation validation and bounded max-two-round loop.

- [ ] **Step 4: Remove silent LLM→local document fallback when runtime is explicitly `llm_structured`**

Refactor `LLMDocumentGenerator.generate()` and `build_generator()` so an LLM contract failure is surfaced in metadata/error unless the host explicitly chose `deterministic_demo`. Do not catch all exceptions and silently return `LocalDocumentGenerator` as equivalent semantic behavior.

- [ ] **Step 5: Persist artifact dependencies/health when document versions are created/confirmed**

At minimum link each version to:

```text
dependency_type = snapshot, dependency_id = current_snapshot_id
dependency_type = claim, dependency_id = each project claim used
dependency_type = source, dependency_id = each current source cited
```

Create/refresh `artifact_health='current'` only when all current dependencies are active and validated.

- [ ] **Step 6: Add preferred generation/confirmation endpoints and deprecated alias**

Implement exact routes:

```text
POST /api/projects/{project_id}/documents/generate
POST /api/document-versions/{version_id}/confirm
POST /api/documents/{version_id}/approve   # deprecated alias
```

Both confirmation paths require the same `human_confirmed=true` gate. Do not introduce organizational approver roles.

- [ ] **Step 7: Run document loop/claim/export regressions**

```bash
pytest tests/test_v3_document_health.py tests/test_generation_loop.py tests/test_v2_document_lifecycle.py tests/test_v2_claim_ledger.py tests/test_exports_and_mcp.py -q
```

- [ ] **Step 8: Commit Snapshot-aware documents**

```bash
git add app/services/generation.py app/services/loop.py app/services/document_versions.py app/tools.py app/main.py app/schemas.py tests/test_v3_document_health.py
git commit -m "feat: bind documents to current Snapshot and evidence health"
```

---

### Task 12: Enforce healthy Snapshot/PRD/TechDoc handoff and align Function Calling/MCP

**Files:**
- Modify: `app/services/handoff.py:38-220`
- Modify: `app/tools.py`
- Modify: `app/mcp_functions.py`
- Modify: `app/mcp_server.py`
- Create: `tests/test_v3_handoff_and_tools.py`

**Interfaces:**
- Consumes: current Snapshot pointer, ArtifactHealthService, confirmed current PRD/TechDoc.
- Produces:
  - fail-closed handoff readiness from Spec §20.9;
  - 3.0 L0/L1/L2 Function Calling surface;
  - exact P0 MCP resources/tools from Spec §19.

- [ ] **Step 1: Write failing handoff health tests**

Cover:

- no current Snapshot → not ready;
- healthy Snapshot but missing PRD/TechDoc → not ready;
- historical confirmed PRD with stale evidence → not ready;
- all three current formal artifacts confirmed + healthy → ready;
- archive after a previously ready handoff causes readiness to fail closed.

- [ ] **Step 2: Write failing Tool Registry risk-boundary tests**

Expected registered 3.0 tools include:

```text
L0: get_current_snapshot, get_project_claims, retrieve_project_evidence,
    get_solution_candidates, get_document_version
L1: create_solution_proposal, create_evidence_relation_proposal,
    create_change_proposal, create_document_draft
L2: confirm_solution_decision, accept_change_proposal, confirm_document_version
```

Assert destructive operations and external publication remain absent. Assert every L2 call fails without host `human_confirmed=True`.

- [ ] **Step 3: Run failing tests**

```bash
pytest tests/test_v3_handoff_and_tools.py -q
```

- [ ] **Step 4: Refactor `HandoffService.readiness()` around formal artifact health**

Replace the old Canvas-as-primary readiness rule. New required formal artifacts:

```text
current confirmed healthy Snapshot
current confirmed healthy PRD
current confirmed healthy TechDoc
```

Canvas may remain in the package for compatibility but cannot make readiness pass by itself.

- [ ] **Step 5: Update handoff package semantics**

Add Snapshot-derived content at the front of the package:

```text
PROJECT_SNAPSHOT.json
MVP_SCOPE.md
UNRESOLVED_RISKS.md
```

Retain useful historical files such as source manifest, retrieval trace, PRD/TechDoc, claim ledger, implementation tasks, acceptance tests, AGENTS.md, manifest and hashes. Rename user-facing `APPROVED_CONTEXT.md` to `CONFIRMED_CONTEXT.md` for newly built 3.0 packages while preserving old package readability.

- [ ] **Step 6: Align Tool Registry with 3.0 risk model**

Use application-owned handlers only. The LLM never sets `human_confirmed=true`; the host passes it separately to `execute()` exactly as the existing L2 gate does.

- [ ] **Step 7: Restrict MCP to exact P0 resources/tools**

Expose only:

```text
insightforge://projects/{project_id}/snapshot/current
insightforge://projects/{project_id}/documents/prd/current
insightforge://projects/{project_id}/documents/techdoc/current
insightforge://projects/{project_id}/mvp-scope
insightforge://projects/{project_id}/unresolved-risks
```

and tools:

```text
get_current_project_context
build_handoff_manifest
```

Do not add binary ZIP write, remote auth, or multi-client synchronization.

- [ ] **Step 8: Run handoff/tool/MCP regressions**

```bash
pytest tests/test_v3_handoff_and_tools.py tests/test_tools.py tests/test_exports_and_mcp.py tests/test_v2_handoff.py -q
```

- [ ] **Step 9: Commit handoff/control-plane alignment**

```bash
git add app/services/handoff.py app/tools.py app/mcp_functions.py app/mcp_server.py tests/test_v3_handoff_and_tools.py
git commit -m "feat: require healthy current artifacts for handoff"
```

---

### Task 13: Complete Evidence/Documents/Handoff UI and runtime-mode disclosure

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`
- Create: `tests/test_v3_ui_evidence_documents_handoff.py`

**Interfaces:**
- Consumes: Claims/Evidence/Impact/Change Proposal, document health, handoff readiness APIs.
- Produces: complete five-module 3.0 user journey with progressive disclosure.

- [ ] **Step 1: Write failing UI contract tests**

Assertions:

- Evidence has exactly the default tabs `关键判断`, `影响记录`, `资料库`;
- Source Library is secondary under Evidence;
- no primary navigation label `RAG` or `Claim Ledger`;
- demo mode disclosure exists and is visible when runtime metadata is `deterministic_demo`;
- Documents page uses `确认此版本`, not organizational approval copy;
- stale evidence warning contains affected sections/dependencies and does not overwrite content;
- Handoff starts with MVP scope/tasks/acceptance/risk before MCP controls;
- mobile breakpoint includes drawer/nav collapse and no globally fixed content width causing horizontal loss.

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/test_v3_ui_evidence_documents_handoff.py -q
```

- [ ] **Step 3: Implement Evidence default view as validation priorities, not file management**

Render each key claim with claim statement, qualitative evidence status, scope note, why it matters, and recommended evidence action. The primary evidence CTA is `验证这个判断` / `添加证据`, not `运行 RAG`.

- [ ] **Step 4: Implement Impact History and Change Proposal interaction**

For each source analysis show `被支持 / 被削弱 / 存在冲突 / 仍未解决`, affected decision/artifacts, then one proposal card with `接受修改 / 暂不修改 / 标记为冲突继续验证` mapped to accept/defer/reject semantics. Never auto-apply UI changes before the API confirms a new Snapshot version.

- [ ] **Step 5: Implement Documents page with health-first copy**

Show PRD and TechDoc on one page. A confirmed-but-stale version must read as historical confirmation plus current evidence warning. User action is `确认此版本`; internal loop states remain hidden in expandable technical details.

- [ ] **Step 6: Implement Handoff page around executable content**

Order content as:

```text
MVP in scope
explicit non-scope
implementation tasks
acceptance cases
confirmed PRD/TechDoc
unresolved risks
copy/export controls
advanced MCP
```

- [ ] **Step 7: Implement explicit runtime disclosure**

When response metadata says `deterministic_demo`, show a persistent but compact disclosure:

> 本地演示模式：当前结构化结果用于验证工作流，不代表真实模型已理解任意 Idea。

When `llm_structured` fails, show the failure and an explicit user action to enter demo mode; do not switch automatically.

- [ ] **Step 8: Run all UI contract tests**

```bash
pytest tests/test_v3_ui_quick_value_contract.py tests/test_v3_ui_evidence_documents_handoff.py tests/test_v2_ui_contract.py -q
```

- [ ] **Step 9: Commit complete 3.0 UI**

```bash
git add app/static/index.html app/static/app.js app/static/styles.css tests/test_v3_ui_evidence_documents_handoff.py
git commit -m "feat: complete evidence-aware five-module UI"
```

---

### Task 14: Migrate legacy 2.0.6 projects and retire Guided writes for new projects

**Files:**
- Create: `app/services/legacy_migration.py`
- Modify: `app/main.py:46-74,185-225`
- Modify: `app/services/guided_project.py`
- Modify: `app/services/example_projects.py`
- Create: `tests/test_v3_legacy_migration.py`

**Interfaces:**
- Consumes: latest legacy Canvas, selected `project_decisions`, existing PRD/TechDoc, audit/source traces.
- Produces:
  - `LegacyMigrationService.migrate_all() -> dict`
  - `migrate_project(project_id) -> ProjectSnapshot | None`
  - legacy-only Guided endpoint behavior from Spec §22.3.

- [ ] **Step 1: Write failing legacy migration tests against a real 2.0.6-format DB**

Use `tests/fixtures/v206_schema.sql`, insert one project with Canvas, one proposed/confirmed legacy decision, sources and a historical document. Assert:

- migration creates exactly one Snapshot with `snapshot_origin='legacy_migration'`;
- rerunning creates no duplicate Snapshot;
- no old source/chunk/document IDs change;
- no market-validated Claim is invented from historical document prose;
- ambiguous historical fields are `user_input` or `model_hypothesis` with `unverified` status;
- historical document claims remain untouched.

- [ ] **Step 2: Write Guided retirement tests**

```python
def test_new_quick_start_project_has_no_guided_session_and_guide_get_is_404(...): ...
def test_existing_legacy_guided_session_remains_readable_and_writable_in_3_0_release_line(...): ...
```

- [ ] **Step 3: Run failing tests**

```bash
pytest tests/test_v3_legacy_migration.py -q
```

- [ ] **Step 4: Implement idempotent legacy Snapshot migration**

Migration must only create claims where the origin is traceable. Never convert `simulated_research` or old document prose into real user validation. Link the generated Snapshot to the current project pointer only when no current 3.0 Snapshot exists.

- [ ] **Step 5: Run migration at application startup after schema initialization and seeding**

FastAPI lifespan order:

```text
db.init_schema()
→ optional seed legacy demo data
→ LegacyMigrationService(db).migrate_all()
→ construct 3.0 services
```

Migration must be safe on every startup.

- [ ] **Step 6: Stop new Guided session creation**

`GuidedProjectService.get_state()` must no longer auto-create a session for a project without an existing `guided_sessions` row. Instead raise `KeyError("legacy guided session not found")`. Keep respond/apply/reset/back only for projects that already own a legacy row; mark routes deprecated in OpenAPI.

- [ ] **Step 7: Update demo seed strategy**

Keep legacy examples for backward-compatibility tests, but add at least one 3.0-ready project seeded through the Quick Value path or fixture-backed migration. Do not claim its demo evidence is real user validation.

- [ ] **Step 8: Run migration, Guided, and seed regressions**

```bash
pytest tests/test_v3_legacy_migration.py tests/test_v2_guided_project.py tests/test_v2_solution_proposals.py tests/test_packaging.py -q
```

If old Guided tests expect automatic session creation for new projects, replace only those semantics with explicit legacy-session fixtures and explain the supersession in the test name/comment; preserve tests for historical Guided behavior.

- [ ] **Step 9: Commit migration/retirement**

```bash
git add app/services/legacy_migration.py app/main.py app/services/guided_project.py app/services/example_projects.py tests/test_v3_legacy_migration.py tests/test_v2_guided_project.py tests/test_v2_solution_proposals.py
git commit -m "feat: migrate legacy projects and retire new guided sessions"
```

---

### Task 15: Add frozen golden evaluation cases and end-to-end P0 acceptance tests

**Files:**
- Expand: `tests/fixtures/v3_golden_cases.json`
- Create: `tests/test_v3_golden_cases.py`
- Create: `tests/test_v3_end_to_end.py`

**Interfaces:**
- Consumes: complete 3.0 API/service flow.
- Produces: frozen engineering acceptance evidence for the 10 Spec cases; no user-effectiveness claims.

- [ ] **Step 1: Complete all ten frozen golden cases**

Fixture cases must cover:

1. convenience-store replenishment;
2. non-AI workflow problem where AI overengineering is rejected;
3. genuine ambiguity requiring one clarification;
4. only two materially different valid solutions;
5. conflicting real-user evidence;
6. simulated research cannot upgrade validation;
7. implementation evidence supports feasibility but not user value;
8. source archive causes stale artifact health;
9. cross-project evidence attack;
10. legacy 2.0.6 migration.

Each case stores expected structural outcomes, not an exact prose answer from a probabilistic model.

- [ ] **Step 2: Write failing end-to-end acceptance tests**

The convenience-store case must exercise:

```text
quick-start
→ confirm IdeaBrief
→ generate valid solutions
→ confirm solution
→ Snapshot v1
→ add source
→ analyze evidence
→ validated claim status change
→ material Change Proposal
→ accept
→ Snapshot v2
→ generate/confirm PRD + TechDoc
→ source archive
→ document health stale
→ handoff readiness false
```

The test must compare v1/v2 historical content hashes and prove v1 was not mutated.

- [ ] **Step 3: Run golden tests and fix only contract defects, not expected outputs post hoc**

```bash
pytest tests/test_v3_golden_cases.py tests/test_v3_end_to_end.py -q
```

Do not repeatedly tune a fixture expected outcome after seeing a failure from `llm_structured`. Engineering golden tests execute `deterministic_demo`; real model evaluation belongs to a separately frozen product-evaluation protocol.

- [ ] **Step 4: Add required engineering metric extraction to test output or a verification helper**

Report at minimum:

```text
legacy regression passed/total
new 3.0 passed/total
migration idempotency PASS/FAIL
cross-project leakage failures = 0
evidence-span invalid proposals blocked
historical artifact mutation failures = 0
silent runtime fallback count = 0
version-truth mismatch count = 0
```

- [ ] **Step 5: Commit golden P0 acceptance coverage**

```bash
git add tests/fixtures/v3_golden_cases.json tests/test_v3_golden_cases.py tests/test_v3_end_to_end.py
git commit -m "test: add frozen InsightForge 3.0 golden cases"
```

---

### Task 16: Update product/technical documentation and produce final verified release evidence

**Files:**
- Modify: `README.md`
- Modify: `RUN_ME_FIRST.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API.md`
- Modify: `docs/DESIGN_SPEC.md`
- Modify: `docs/CLAIM_BOUNDARY.md`
- Modify: `docs/FUNCTION_CALLING.md`
- Modify: `docs/MCP.md`
- Modify: `docs/TEST_MATRIX.md`
- Modify: `docs/USER_FEEDBACK_AND_ITERATION.md`
- Modify: `VERIFICATION_REPORT.md`
- Modify: `tests/test_v3_release_identity.py`
- Create: `docs/MIGRATION_2_0_6_TO_3_0.md`

**Interfaces:**
- Consumes: verified implementation/test output only.
- Produces: implementation-aligned 3.0 docs, migration guidance, exact final test counts, release-truth consistency.

- [ ] **Step 1: Run the complete suite before writing any success claims**

```bash
pytest -q
```

Record the exact passed/skipped/failed counts from this run. If any failure exists, do not write a “complete” verification report; fix the implementation task that owns the failure first.

- [ ] **Step 2: Run targeted integrity checks**

```bash
pytest tests/test_v3_schema_migration.py tests/test_v3_snapshot_transaction.py tests/test_v3_project_claim_evidence.py tests/test_v3_change_proposals.py tests/test_v3_source_lifecycle.py tests/test_v3_document_health.py tests/test_v3_handoff_and_tools.py tests/test_v3_legacy_migration.py tests/test_v3_end_to_end.py -q
```

Also run:

```bash
python -m compileall app tests
```

Expected: all commands return exit status 0.

- [ ] **Step 3: Rewrite docs to match the implemented five-module product, not the old Evidence Workspace IA**

Required documentation language:

- first value is Idea → 2–3 domain-specific solutions → Project Snapshot;
- Evidence visibly proposes changes through project Claims/Decisions/Change Proposals;
- Canvas/RAG/Claim Ledger/validator/Function Calling are infrastructure or advanced details, not default user tasks;
- single-user document action is “Confirm this version,” not organizational approval;
- deterministic demo mode is not proof of arbitrary semantic AI performance;
- implementation evidence is not product-market evidence.

- [ ] **Step 4: Write migration documentation with exact legacy behavior**

`docs/MIGRATION_2_0_6_TO_3_0.md` must state:

```text
legacy tables retained
new tables added additively
legacy guided sessions readable only when pre-existing
legacy Snapshot origin explicitly labeled
historical document/claim content immutable
no invented evidence links/market validation
Canvas preserved as compatibility projection
```

- [ ] **Step 5: Update `VERIFICATION_REPORT.md` from actual commands only**

Include:

- version `3.0.0`;
- exact total test count from Step 1;
- exact targeted test count from Step 2;
- baseline reference `2.0.6 untouched = 99 passed`;
- migration idempotency result;
- cross-project leakage test result;
- silent fallback result;
- historical mutation result;
- known limitations and claim boundary.

Do not claim real-user time-to-value, retention, productivity improvement, superiority to ChatGPT/ChatPRD, enterprise collaboration, GraphRAG, or production remote MCP.

- [ ] **Step 6: Strengthen release identity test to include verification docs**

Add:

```python
def test_verification_report_uses_current_release_identity():
    text = (ROOT / "VERIFICATION_REPORT.md").read_text(encoding="utf-8")
    assert "3.0.0" in text
    assert "2.0.0" not in text
```

Only keep historical `2.0.6` references where explicitly labeled as baseline; structure the test accordingly rather than banning `2.0.6`.

- [ ] **Step 7: Run final release verification**

```bash
pytest -q
python -m compileall app tests
```

Then optionally run the existing Uvicorn smoke command documented in `RUN_ME_FIRST.md` against a temporary database and verify:

```text
GET /api/health -> 200, version=3.0.0
POST /api/projects/quick-start -> 201
GET / -> 200
```

- [ ] **Step 8: Inspect Git diff for forbidden P0 scope expansion**

Run:

```bash
git diff --stat HEAD~1..HEAD
git grep -n -E "GraphRAG|multi-agent|remote MCP OAuth|enterprise RBAC|autonomous approval" -- app docs README.md
```

Any occurrence must either be an explicit non-goal/claim-boundary statement or be removed from implementation claims.

- [ ] **Step 9: Commit verified 3.0 documentation/release evidence**

```bash
git add README.md RUN_ME_FIRST.md docs VERIFICATION_REPORT.md tests/test_v3_release_identity.py
git commit -m "docs: align InsightForge 3.0 release evidence"
```

---

## Execution order and review gates

Run tasks strictly in order. Reviewer gates are intentionally placed at semantic boundaries:

1. **Tasks 1–2:** release identity + additive DB foundation. Do not proceed if old DB migration is not idempotent.
2. **Tasks 3–6:** first-value backend. Do not proceed if a formal Snapshot can be created without user confirmation or if convenience-store solutions remain generic InsightForge workflow templates.
3. **Task 7:** first-value UI. Do not proceed if Guided/Advanced dual mode remains the primary experience.
4. **Tasks 8–10:** Evidence Impact core. Do not proceed if LLM output can bypass exact source/chunk/span validation or if archive is non-atomic.
5. **Tasks 11–13:** document/handoff/control-plane + full UI. Do not proceed if stale evidence can still produce a ready handoff.
6. **Task 14:** legacy compatibility. Do not proceed if migration invents evidence or validation state.
7. **Tasks 15–16:** frozen engineering acceptance and release evidence. Do not write portfolio-effectiveness claims from engineering tests.

## Minimal rerun strategy during implementation

After each task, run that task's targeted tests. At the end of every review gate above, additionally run:

```bash
pytest -q
```

This intentionally catches semantic regressions early. Do not wait until Task 16 to discover that an old claim/retrieval/handoff contract was broken.

## Cache / generated-data invalidation

This package does not currently rely on a model-result cache for the tested local workflow. During execution:

- use a fresh temporary SQLite DB for schema/migration/transaction tests;
- do not reuse a seeded 2.0.6 DB as evidence that migration is rerunnable unless the test explicitly recreates that fixture;
- static browser cache must be invalidated by `?v=3.0.0` asset identity;
- any new deterministic demo fixture must be versioned by fixture content hash or `generator_version`; changing it invalidates golden outputs;
- LLM run traces store prompt/schema/generator versions and input/output SHA-256, so a changed prompt/model cannot be silently compared as the same run.

## Final P0 acceptance checklist

Implementation is not complete unless all are demonstrably true:

- [ ] Rough Idea can create a project without Canvas/source/Guided prerequisites.
- [ ] One blocking clarification is used only for decision-critical ambiguity.
- [ ] At least two materially different domain-specific solutions exist on frozen golden cases.
- [ ] A non-LLM/low-AI baseline is present unless user explicitly confirms `llm_core_required=true`.
- [ ] Formal solution selection requires user confirmation.
- [ ] Snapshot v1 is atomic, immutable, and becomes `projects.current_snapshot_id`.
- [ ] Canvas projection exactly matches the Spec mapping and cannot silently diverge.
- [ ] Project Claims separate provenance from verification state.
- [ ] Evidence relations are project-scoped and exact-span validated.
- [ ] `simulated_research` cannot upgrade real validation.
- [ ] `implementation_evidence` cannot validate user need/value.
- [ ] Claim status recomputation counts independent sources, not chunks.
- [ ] Material evidence changes create Change Proposals rather than formal auto-updates.
- [ ] Accept creates Snapshot vN+1; reject/defer preserve current Snapshot.
- [ ] Source archive/restore propagates atomically and preserves historical content.
- [ ] PRD/TechDoc health is separate from historical confirmation/content.
- [ ] Handoff fails closed on missing/unhealthy current formal artifacts.
- [ ] New UI has exactly five primary modules and one primary next action on Snapshot.
- [ ] RAG/Claim Ledger/Function Calling/MCP remain advanced/infrastructure concerns.
- [ ] `deterministic_demo` is disclosed and no silent runtime fallback occurs.
- [ ] Existing 2.0.6 projects migrate idempotently with no invented validation/evidence.
- [ ] Version identity is exactly `3.0.0` across runtime/package/static/docs.
- [ ] Full pytest suite is green and exact counts are recorded in `VERIFICATION_REPORT.md`.
