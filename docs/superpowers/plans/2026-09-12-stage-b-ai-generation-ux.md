# Stage B AI Generation UX Implementation Plan

> **For the implementing agent:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Make every core AI surface show complete, readable, provenance-honest content with correct loading, success, failure, retry, selection, refresh, and persistence behavior.

**Architecture:** Frontend consumes L3/L4 allowlisted DTOs only. Each surface has explicit IDLE, GENERATING, SUCCEEDED, and FAILED state transitions. Renderers construct typed DOM nodes and never display API objects or provider strings. Existing local deterministic fixtures remain the primary test runtime.

**Tech Stack:** `app/static/app.js`, `app/static/index.html`, `app/static/styles.css`, Node harnesses, Chromium/Playwright, pytest API tests.

**Spec:** `STAGE_B_AI_SURFACE_MATRIX.md`; `tests/generation_recovery_behavior_harness.js`; `tests/ai_reference_no_source_browser.cjs`; `tests/document_evidence_ux_behavior_harness.js`.

## Global Constraints

- No visual redesign unrelated to generation correctness.
- No whole-page brace prohibition; assertions target AI-rendering containers.
- Chinese user messages are required; internal error codes remain operator/API fields only.
- Evidence remains optional and is never converted into a gate.

## Tasks

### 1. Add RED surface contract tests

Files: `tests/stage_b_generation_surface_harness.js` (new), `tests/ai_reference_no_source_browser.cjs`, `tests/generation_recovery_behavior_harness.js`, `tests/solution_detail_behavior_harness.js`.

Load `app/static/app.js` with fake DOM/API responses and assert success indicator plus actual visible body for AI reference, at least one complete Action Card, exactly three solution cards, document body, and Handoff references. Add fixtures for empty, malformed, wrong-schema, provider failure, duplicate solutions, wrong-solution PRD, and TechDoc scope drift. Assert the baseline fails a real completeness or stale-state assertion; save output to `artifacts/stage-b-red-ux.txt`.

Run Node harnesses before production changes. Commit: `test: reproduce stage-b generation ux failures`.

### 2. Implement typed frontend render and state contracts

Files: `app/static/app.js`, `app/static/index.html`, `app/static/styles.css`, `tests/stage_b_generation_surface_harness.js`, `tests/generation_recovery_behavior_harness.js`.

Add surface-specific allowlisted view-model adapters and render guards around `renderAIReference`, `renderEvidenceGuidance`, `renderSolutions`, `renderDocumentWorkspace`, and `renderHandoff`. Remove any user-visible path that writes whole API objects. Keep `JSON.stringify` only for non-rendered internal keys after tests prove it cannot enter the container. Ensure `generateAIReference`, `generateEvidenceGuidance`, `generateSolutions`, `pollSolutionGeneration`, and `generateDocument` clear stale error/loading/content state before retry and mark success only after complete DTO checks.

Run targeted Node harnesses and existing browser harnesses. Commit: `fix: harden ai generation rendering and state`.

### 3. Verify Action Card and AI reference quality contracts

Files: `app/services/ai_reference.py`, `app/services/evidence_coach.py`, `app/static/app.js`, `tests/test_ai_reference_no_source.py`, `tests/test_evidence_guidance.py`, `tests/ai_reference_no_source_browser.cjs`.

Require visible AI reference body and the explicit “AI参考/待验证” boundary. Require Action Cards to display what to confirm, who/where, steps, materials, template, decision impact, fallback, and limitation. Add fake fixtures with absent evidence and assert output uses suggestion/hypothesis semantics rather than research or market claims. Verify no source is created by AI reference or guidance generation.

Run backend and Chromium tests. Commit: `fix: enforce actionable ai guidance rendering`.

### 4. Verify solution differentiation and inheritance UX

Files: `app/services/solution_design.py`, `app/services/ai_runtime.py`, `app/static/app.js`, `tests/test_v3_solution_design.py`, `tests/test_v3_solution_api.py`, `tests/solution_detail_behavior_harness.js`, `tests/stage_b_generation_surface_harness.js`.

Use the current `_material_difference_count`, `validate_solution_set`, and `SolutionDesignService._brief_for_project` as the base. Add deterministic duplicate/near-identical fixtures and assert rejection. Assert each card visibly includes title, core idea, value, flow, MVP, and tradeoff. Select solution B and generate downstream documents through the fake/local path; assert selected identity, rationale, problem, target user, MVP scope, and flow persist through PRD, TechDoc, and Handoff.

Run targeted solution/document tests. Commit: `fix: preserve solution and document inheritance`.

### 5. Verify failure, retry, refresh, and layout behavior

Files: `app/static/app.js`, `app/static/styles.css`, `tests/generation_recovery_behavior_harness.js`, `tests/loading_progress_harness.js`, `tests/cancel_progress_harness.js`, `tests/document_evidence_ux_behavior_harness.js`, `tests/stage_b_generation_surface_harness.js`.

Cover 1366 and 1440 desktop viewport fixtures plus 125% and 150% equivalent layout settings through the existing Chromium harness mechanism. Assert solution cards, reference panel, Action Cards, generation modal/progress, PRD/TechDoc editor, and Handoff remain readable without overflow. Assert failed content is not appended on retry, old error banners disappear on success, loading disappears, and refresh reloads the persisted result.

Run browser harnesses with synthetic intercepted transport only. Commit: `test: add stage-b product acceptance harness`.

## Acceptance criteria

- AI reference, Action Cards, solutions, PRD, TechDoc, and Handoff each show actual non-empty user-visible content.
- Duplicate solutions fail the quality contract; selected solution identity survives downstream generation.
- User-visible failures state what happened, whether content was written, and whether retry is available.
- AI-rendering containers contain no raw JSON, provider wrapper, prompt, schema dump, or raw error object.
- Real Provider request count remains zero throughout B1/B2.
