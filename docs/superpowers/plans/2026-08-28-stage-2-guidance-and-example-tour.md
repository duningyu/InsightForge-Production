# Guidance and Complete Example Tour Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give users one trustworthy next action and a copy-on-start walkthrough of two complete examples.

**Architecture:** `GuidanceService` maps persisted lifecycle state to one action code. `ExampleCopyService` transactionally clones immutable examples, while `TourService` stores progress and highlights the real workspace UI.

**Tech Stack:** FastAPI, SQLite, vanilla JavaScript/CSS, existing Snapshot/Claim/Document services.

**Spec:** `docs/superpowers/specs/2026-08-28-insightforge-guidance-models-documents-history-design.md`

## Global Constraints

- State, not model prose, selects the next action.
- Canonical examples remain immutable; walkthroughs run only on copies.
- Simulated sources remain labelled simulated and never become real-user evidence.
- Current directory is not Git; commit steps apply only in a Git worktree.

---

### Task 1: Guidance State Machine

**Files:** Create `app/services/guidance.py`; modify `app/main.py`; test `tests/test_next_action.py`.

**Interfaces:** `GuidanceService.home_next_action() -> dict`; `project_next_action(project_id) -> dict` returning `code`, `title`, `reason`, `view`, `control_id`.

- [ ] Write failing table-driven tests for every priority state: confirm brief, generate/select solution, validate claim, PRD, TechDoc, confirm versions, handoff, ready.
- [ ] Run `python -m pytest -q tests/test_next_action.py`; expect missing service/routes.
- [ ] Implement SQL/service checks using existing services; return exactly one action and stable literal action codes.
- [ ] Add `GET /api/home/next-action` and `GET /api/projects/{project_id}/next-action`.
- [ ] Run targeted tests; if in Git, commit `feat: add deterministic next actions`.

### Task 2: Example Copy and Lineage

**Files:** Modify `app/db.py`; create `app/services/example_copies.py`; modify `app/schemas.py app/main.py`; test `tests/test_example_copy.py`.

**Interfaces:** `ExampleCopyService.copy(example_id, actor) -> dict`; table `project_relations(parent_project_id, child_project_id, relation_type, created_at)`.

- [ ] Write failing tests proving new IDs, copied canvas/snapshot/claims/sources/documents, no shared mutable rows, preserved simulated labels, and canonical immutability.
- [ ] Run test; expect missing table/service.
- [ ] Add idempotent schema and a single copy transaction. Generate fresh IDs and rewrite internal foreign keys; record `example_copy` lineage.
- [ ] Add `GET /api/examples` and `POST /api/examples/{example_id}/copies`.
- [ ] Run targeted tests and migration tests; if in Git, commit `feat: add immutable example copies`.

### Task 3: Persisted Seven-Step Tour

**Files:** Modify `app/db.py`; create `app/services/tours.py`; modify `app/schemas.py app/main.py`; test `tests/test_project_tour.py`.

**Interfaces:** `TourService.get/update/restart`; steps are `idea`, `solutions`, `mvp`, `claims`, `evidence`, `documents`, `handoff`.

- [ ] Write failing tests for start-only-on-example-copy, next/back/skip/restart, invalid step rejection, and restart persistence.
- [ ] Run test; expect missing routes.
- [ ] Add `project_tour_progress` schema, strict update request, and GET/PATCH routes.
- [ ] Run targeted tests; if in Git, commit `feat: persist example walkthrough progress`.

### Task 4: Guidance and Tour UI

**Files:** Create `app/static/guidance.js app/static/tour.js`; modify `app/static/index.html app/static/app.js app/static/styles.css`; test `tests/test_guidance_tour_ui.py`.

**Interfaces:** Home/project action cards deep-link by `view` and `control_id`; tour overlay highlights existing controls.

- [ ] Write failing UI tests for one-action cards, two examples, start-tour button, seven step labels, skip/back/next/restart, and accessible focus handling.
- [ ] Run tests; expect missing markup/modules.
- [ ] Implement the home card and project card. Implement tour as an overlay anchored to real DOM controls; never duplicate workspace content.
- [ ] Run UI tests and `node --check` on all three JS files.
- [ ] Browser-test desktop/mobile, refresh persistence, skipped tour, canonical example unchanged, then run full pytest/compile/SQLite integrity checks.
- [ ] If in Git, commit `feat: add next-step guidance and example tour`.

