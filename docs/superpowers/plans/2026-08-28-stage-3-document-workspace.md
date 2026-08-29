# Document Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe Markdown editing, autosaved drafts, immutable formal versions, diffs, restore-as-new, and selected-version export for PRD and TechDoc.

**Architecture:** Mutable drafts are separate from immutable `document_versions`. Optimistic draft revisions prevent lost updates; formal saves and restores always append a version, while a focused diff service produces display blocks.

**Tech Stack:** FastAPI, SQLite, Python `difflib`, vanilla JavaScript Markdown editor/preview, existing exporters.

**Spec:** `docs/superpowers/specs/2026-08-28-insightforge-guidance-models-documents-history-design.md`

## Global Constraints

- Autosave never creates a formal version.
- Confirmed versions cannot be overwritten.
- Restore appends a new version with provenance.
- Existing MD/JSON/DOCX exports remain canonical.
- Current directory is not Git; commit steps apply only in a Git worktree.

---

### Task 1: Draft Schema and Optimistic Service

**Files:** Modify `app/db.py`; create `app/services/document_drafts.py`; test `tests/test_document_drafts.py`.

**Interfaces:** `get(project_id, doc_type)`; `save(project_id, doc_type, content, base_version_id, expected_revision, actor)` returning incremented `draft_revision`.

- [ ] Write failing tests for first draft, update, stale revision conflict, project/doc-type uniqueness, restart persistence, and no new `document_versions` row.
- [ ] Run test; expect missing table/service.
- [ ] Add `document_drafts` schema and transactional optimistic update; raise `ConflictError` on revision mismatch.
- [ ] Run tests and migration suite; if in Git, commit `feat: add document draft storage`.

### Task 2: Formal Save, Diff, and Restore

**Files:** Create `app/services/document_editor.py app/services/document_diff.py`; modify `app/services/document_versions.py`; test `tests/test_document_editor.py`.

**Interfaces:** `save_as_new_version(...)`; `diff(left_id, right_id) -> {blocks:[{kind,text}]}`; `restore_as_new(version_id, actor)`.

- [ ] Write failing tests proving monotonic versions, source draft revision provenance, confirmed immutability, literal added/deleted diff blocks, and restore creates rather than mutates.
- [ ] Run test; expect missing modules.
- [ ] Implement append-only version creation using the existing document row, `difflib.ndiff`/opcodes, and restore provenance in the audit payload.
- [ ] Run tests plus `tests/test_v2_document_lifecycle.py tests/test_v3_document_health.py`.
- [ ] If in Git, commit `feat: add immutable document editing operations`.

### Task 3: Draft/Diff APIs and Export Selection

**Files:** Modify `app/schemas.py app/main.py app/exporters.py`; test `tests/test_document_editor_api.py`.

**Interfaces:** Exact draft/version/diff/restore routes from the spec; existing `/api/documents/{version_id}/export` exports the selected ID.

- [ ] Write failing API tests for draft CRUD, 409 stale revision, explicit formal save, two-version diff, restore, and MD/JSON/DOCX response content.
- [ ] Run tests; expect 404 routes.
- [ ] Add strict request models and routes; require human confirmation for formal save/restore/export UI actions, without weakening existing API export semantics.
- [ ] Run API and exporter tests; if in Git, commit `feat: expose document workspace api`.

### Task 4: Online Editor, Version Panel, and Verification

**Files:** Create `app/static/document-editor.js`; modify `app/static/index.html app/static/app.js app/static/styles.css`; test `tests/test_document_editor_ui.py`.

**Interfaces:** PRD/TechDoc tabs, Markdown input, preview, autosave status, save-new-version action, two-version diff selectors, restore and export actions.

- [ ] Write failing UI tests for every control, active-tab blue state, draft status, explicit confirmation, diff semantics, and no direct confirmed-version edit.
- [ ] Run test; expect missing controls.
- [ ] Implement 800 ms debounced autosave with revision tokens; on 409 stop autosave and show reload/merge choices. Render Markdown safely without raw HTML execution.
- [ ] Implement diff and export controls; preserve existing document trash/recycle-bin functions.
- [ ] Run UI tests, `node --check`, full pytest/compile, browser desktop/mobile editing, SQLite integrity/foreign-key checks, and export-open smoke tests.
- [ ] If in Git, commit `feat: add online document workspace`.

