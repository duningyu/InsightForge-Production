# Project History Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated searchable project-history center with filters, stable pagination, independent copies, trash, restore, and guarded permanent deletion.

**Architecture:** `ProjectHistoryService` builds parameterized SQLite queries and cursor pagination. `ProjectCopyService` performs a deep transactional copy with lineage; the new UI is a separate history view while the home page retains six recent cards.

**Tech Stack:** FastAPI, SQLite, vanilla JavaScript/CSS, existing project lifecycle routes.

**Spec:** `docs/superpowers/specs/2026-08-28-insightforge-guidance-models-documents-history-design.md`

## Global Constraints

- Search covers title and summary only; SQL remains parameterized.
- Sorting is stable and cursor-based.
- Copies have fresh IDs and no shared mutable rows.
- Permanent deletion is available only in trash after explicit confirmation.
- Current directory is not Git; commit steps apply only in a Git worktree.

---

### Task 1: Search, Filter, Sort, and Cursor API

**Files:** Create `app/services/project_history.py`; modify `app/services/projects.py app/main.py`; test `tests/test_project_history.py`.

**Interfaces:** `search(q, status, kind, sort, limit, cursor) -> {items,next_cursor}` where sort is `updated_desc|updated_asc|title_asc`.

- [ ] Write failing tests with literal projects for title/summary search, active/example/example-copy/trashed filters, three sorts, limit bounds, stable same-timestamp ordering, cursor continuation, and SQL-injection strings.
- [ ] Run test; expect unsupported query parameters/shape.
- [ ] Implement parameterized query construction and opaque base64url cursor containing sort value plus ID; validate cursor shape.
- [ ] Extend `GET /api/projects` while preserving the legacy unfiltered list response only if existing clients require it; otherwise update all callers atomically to `{items,next_cursor}`.
- [ ] Run history and existing API tests; if in Git, commit `feat: add project history query api`.

### Task 2: Deep Project Copy and Lineage

**Files:** Create `app/services/project_copies.py`; reuse/extend `project_relations` from Stage 2; modify `app/main.py`; test `tests/test_project_copy.py`.

**Interfaces:** `ProjectCopyService.copy(project_id, title, actor) -> dict`; `POST /api/projects/{project_id}/copies`.

- [ ] Write failing tests for fresh project/canvas/source/chunk/document/version/snapshot/claim/decision IDs, copied content, independent later edits, lineage, and rejection of trashed source projects.
- [ ] Run test; expect missing service/route.
- [ ] Implement one transaction with explicit old-to-new ID maps. Copy active artifacts only; do not copy audit events, generation/retrieval runs, trash state, handoff packages, model credentials, or tour progress.
- [ ] Run copy tests and foreign-key check; if in Git, commit `feat: add independent project copies`.

### Task 3: Dedicated History UI

**Files:** Create `app/static/history.js`; modify `app/static/index.html app/static/app.js app/static/styles.css`; test `tests/test_history_ui.py`.

**Interfaces:** Header/home history links open `history-view`; query state maps to API parameters; cards expose open/copy/trash or restore/delete based on lifecycle.

- [ ] Write failing UI tests for search, filters, sort, pagination/load-more, copy, trash entrance, restore, permanent-delete confirmation, empty/error states, and return-to-home.
- [ ] Run test; expect missing view/module.
- [ ] Implement a dedicated view matching approved layout A. Debounce search, cancel stale requests, retain filters when opening/returning, and update the home recent-six list after mutations.
- [ ] Ensure destructive actions identify the exact project and require confirmation; canonical examples cannot be trashed or copied through an unsafe mutation path.
- [ ] Run UI tests and `node --check app/static/history.js app/static/app.js`; if in Git, commit `feat: add project history center ui`.

### Task 4: Lifecycle and Full-System Verification

**Files:** Modify `tests/test_v2_project_lifecycle.py tests/test_v3_end_to_end.py`; create `tests/test_history_end_to_end.py`.

**Interfaces:** End-to-end flow: search -> copy -> open -> trash -> restore -> trash -> permanent delete.

- [ ] Write the end-to-end test with an isolated database and literal expected counts/IDs/statuses.
- [ ] Run it before any final adjustment; fix only contract mismatches revealed by the test.
- [ ] Run `python -m pytest -q`, `python -m compileall -q app tests`, and all JavaScript syntax checks.
- [ ] Start through `start.bat`; browser-test desktop/mobile history, search/filter/copy/trash, home recent cards, and console errors.
- [ ] Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on the migrated copy and formal local database; verify no credential sentinel exists in database/logs/exports.
- [ ] If in Git, commit `test: verify complete history lifecycle`.
