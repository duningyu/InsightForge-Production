# InsightForge 2.0 Guided Evidence Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a novice-first guided workflow with transparent provenance, replayable retrieval, structured claim evidence, and a concrete AI coding handoff while preserving the existing advanced workspace and safety gates.

**Architecture:** Extend the existing FastAPI + SQLite domain services with additive migrations and focused services for guided coaching, source guidance, retrieval trace, claims, and handoff. Replace the single technical dashboard with a default three-column Guided Mode and a switchable Advanced Workspace; existing APIs stay compatible.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, SQLite, vanilla HTML/CSS/JavaScript, python-docx, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-guided-evidence-workspace-design.md`

## Global Constraints

- Default application version is `2.0.0`.
- Guided Mode is the default UI; Advanced Workspace is reachable from a top-right switch.
- Existing 1.1.0 HTTP endpoints and 37 baseline tests remain compatible.
- Retrieval weights remain BM25 `0.55`, TF-IDF cosine `0.30`, authority `0.15` and are labelled as a manual baseline, not an optimized result.
- No new mandatory cloud dependency is introduced.
- The coach, generator, tools, and MCP cannot approve, publish, delete, or overwrite approved artifacts.
- Every new persistence change is additive and idempotent for SQLite.
- PRD statements distinguish implemented behavior, user feedback, hypotheses, and future work.

---

### Task 1: Add additive schema migrations and central retrieval profiles

**Files:**
- Modify: `app/config.py`
- Modify: `app/db.py`
- Create: `app/retrieval_profiles.py`
- Test: `tests/test_v2_schema_and_profiles.py`

**Interfaces:**
- Produces: `get_retrieval_profile(profile_id: str) -> RetrievalProfile`
- Produces: `list_retrieval_profiles() -> list[dict[str, Any]]`
- Adds SQLite tables/columns from the design specification.

- [x] Write failing tests proving a fresh database contains all new tables, an old minimal 1.1.0 schema upgrades without data loss, and profile IDs/top-K/weights are centralized.
- [x] Run `pytest tests/test_v2_schema_and_profiles.py -q` and verify failure because migrations/profiles do not exist.
- [x] Implement `RetrievalProfile`, four profiles, `Settings.app_version=2.0.0`, and idempotent `Database._migrate_schema()` helpers.
- [x] Re-run the targeted tests and the baseline database tests.
- [x] Commit `feat: add v2 schema and retrieval profiles`.

### Task 2: Persist retrieval runs and expose trace APIs

**Files:**
- Modify: `app/services/retrieval_service.py`
- Modify: `app/tools.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Test: `tests/test_v2_retrieval_trace.py`

**Interfaces:**
- Produces: `ProjectRetrievalService.execute_retrieval(...) -> dict[str, Any]`
- Produces HTTP profile/run endpoints.
- Existing `retrieve_project_sources(...) -> list[dict[str, Any]]` remains compatible.

- [x] Write failing tests for trace persistence, profile explanation, hit scores, project isolation, and the new HTTP endpoints.
- [x] Run the targeted tests and verify missing methods/endpoints fail.
- [x] Implement trace storage and API responses; have the tool registry return the full run payload.
- [x] Run targeted tests plus `tests/test_retrieval.py` and `tests/test_tools.py`.
- [x] Commit `feat: add replayable retrieval traces`.

### Task 3: Add novice source guidance and provenance metadata

**Files:**
- Create: `app/services/source_guidance.py`
- Modify: `app/services/sources.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Test: `tests/test_v2_source_guidance.py`

**Interfaces:**
- Produces: `SourceGuidanceService.describe_categories() -> list[dict[str, Any]]`
- Produces: `SourceGuidanceService.classify(origin_kind, ...) -> dict[str, Any]`
- Produces guided source creation HTTP endpoint.

- [x] Write failing tests for category explanations, transparent mapping, authority basis, allowed-claim boundaries, URL/publisher persistence, and advanced endpoint compatibility.
- [x] Verify RED with the targeted test file.
- [x] Implement the service, schemas, metadata persistence, and APIs.
- [x] Run targeted tests plus ingestion/API baseline tests.
- [x] Commit `feat: add guided source provenance`.

### Task 4: Build the bounded PM Coach and Canvas confirmation flow

**Files:**
- Create: `app/services/guided_project.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Modify: `app/services/projects.py`
- Test: `tests/test_v2_guided_project.py`

**Interfaces:**
- Produces: `GuidedProjectService.get_state(project_id)`
- Produces: `GuidedProjectService.respond(project_id, answer, choice_id, actor)`
- Produces: `GuidedProjectService.apply_canvas(project_id, actor)`
- Produces: `GuidedProjectService.reset(project_id, actor)`

- [x] Write failing tests for initial state, one-question progression, “why/examples/choices”, suggestion-vs-confirmation separation, three solution alternatives, Canvas proposal, apply, reset, and audit events.
- [x] Verify RED.
- [x] Implement the deterministic state machine and APIs; initialize it in app lifespan.
- [x] Run targeted tests plus project/API baseline tests.
- [x] Commit `feat: add transparent guided PM coach`.

### Task 5: Replace citation rotation with a structured claim-evidence ledger

**Files:**
- Modify: `app/services/generation.py`
- Modify: `app/services/validation.py`
- Modify: `app/services/loop.py`
- Modify: `app/tools.py`
- Modify: `app/main.py`
- Test: `tests/test_v2_claim_ledger.py`

**Interfaces:**
- `generate(...)` additionally returns `claims`.
- Produces persisted `document_claims` and `claim_evidence_links`.
- Produces `GET /api/documents/{version_id}/claims`.

- [x] Write failing tests proving public comparison claims use `public_source`, implementation claims use `implementation_evidence`, simulated evidence is disclosed, Canvas claims are `user_confirmed`, invalid links fail validation, and claims can be read through API.
- [x] Verify RED.
- [x] Implement lexical/source-type evidence selection, structured claims, persistence, and optional claim-aware validation.
- [x] Run targeted tests plus generation-loop/export baseline tests.
- [x] Commit `fix: align document claims with evidence`.

### Task 6: Implement a real AI coding handoff package

**Files:**
- Create: `app/services/handoff.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Modify: `app/tools.py`
- Modify: `app/mcp_functions.py`
- Modify: `app/mcp_server.py`
- Test: `tests/test_v2_handoff.py`

**Interfaces:**
- Produces: `HandoffService.readiness(project_id) -> dict[str, Any]`
- Produces: `HandoffService.build_zip(project_id, target_client, actor) -> tuple[bytes, dict]`
- Produces readiness and export HTTP endpoints plus read-oriented MCP/tool access.

- [x] Write failing tests for fail-closed readiness, approved PRD/TechDoc requirements, ZIP file list, SHA-256 manifest validation, unresolved claim inclusion, audit, and MCP/tool risk boundaries.
- [x] Verify RED.
- [x] Implement readiness, deterministic package construction, HTTP response, tool, and MCP wrappers.
- [x] Run targeted tests plus MCP/export baseline tests.
- [x] Commit `feat: add versioned AI coding handoff`.

### Task 7: Redesign the browser UI

**Files:**
- Replace: `app/static/index.html`
- Replace: `app/static/styles.css`
- Replace: `app/static/app.js`
- Test: `tests/test_v2_ui_contract.py`

**Interfaces:**
- Consumes the guided, source guidance, retrieval trace, claims, documents, handoff, audit, and existing project APIs.
- Produces Guided Mode as default and Advanced Workspace as an explicit mode.

- [x] Write a failing static-contract test for the mode toggle, six-step rail, coach panel, evidence tabs, novice source wording, retrieval explanation, advanced views, and handoff UI.
- [x] Verify RED.
- [x] Implement semantic HTML, accessible controls, responsive three-column layout, stateful vanilla JS, and human-readable source/retrieval labels.
- [x] Run UI contract tests and the full API suite.
- [x] Launch Uvicorn, execute a browser/static smoke test, and inspect desktop/mobile screenshots if a local browser runtime is available.
- [x] Commit `feat: redesign guided and advanced workspace UI`.

### Task 8: Update product documentation and PRD

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API.md`
- Modify: `docs/RAG_AND_SOURCE_GOVERNANCE.md`
- Modify: `docs/CLAIM_BOUNDARY.md`
- Modify: `docs/FEATURE_CHECKLIST.md`
- Create: `docs/USER_FEEDBACK_AND_ITERATION.md`
- Replace: `docs/PRD_InsightForge.docx`
- Test: `tests/test_v2_documentation_contract.py`

**Interfaces:**
- Documents version `2.0`, user-feedback provenance, implemented/planned boundaries, new IA, APIs, data model, metrics, and rollout.

- [x] Write failing tests for required documentation phrases, version, user-feedback section, and claim boundaries.
- [x] Verify RED.
- [x] Update Markdown docs and generate the full v2.0 PRD DOCX with a revision table and diagrams.
- [x] Render the DOCX to page PNGs, inspect every page, fix layout defects, and re-render.
- [x] Run documentation tests.
- [x] Commit `docs: publish InsightForge 2.0 PRD and iteration record`.

### Task 9: Final verification and packaging

**Files:**
- Modify: `VERIFICATION_REPORT.md`
- Modify: `pyproject.toml`
- Modify: `RUN_ME_FIRST.md`
- Produce: final ZIP and SHA-256 sidecar outside the repository.

**Interfaces:**
- Produces a complete runnable package and verification evidence.

- [x] Run `pytest -q`, `python -m compileall -q app`, and packaging tests.
- [x] Run a fresh temporary-database API smoke covering guided flow, source addition, retrieval trace, document generation, approval, and handoff export.
- [x] Update verification counts and claim boundaries using observed output only.
- [x] Remove runtime caches/database files, create the ZIP, calculate SHA-256, extract into a fresh directory, and rerun tests there.
- [x] Commit `chore: verify and package InsightForge 2.0`.
