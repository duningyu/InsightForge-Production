# Stage B Product Flow Phase 1A Execution Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or **superpowers:executing-plans** to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, internal-only Stage B operator execution paths for one Solutions canary and one local PRD canary while preserving ordinary HTTP routes, product semantics, and the zero-real-provider boundary for this implementation task.

**Architecture:** Reuse `StageBEvaluationContext` and `StageBEvaluationReceiptStore` for durable pre-transport coordination. Extend the existing Solutions service/runtime call boundary with an explicit context and a strict execution policy. Add operator-only orchestration functions in `scripts/stage_b_evaluation_inspect.py`; the Solutions path uses the existing managed runtime and dispatch ledger, while the PRD path uses the existing `DocumentLoop` and `LocalDocumentGenerator` without provider access. No HTTP route or second generation implementation is introduced.

**Tech Stack:** Python 3.12 runtime, SQLite-backed `Database`, Pydantic/domain contracts, existing managed provider runtime and dispatch ledger, `pytest`, FastAPI route enumeration, and the existing operator script.

**Spec:** `IMPLEMENT_STAGE_B_PRODUCT_FLOW_PHASE1A_EXECUTION_PATHS`; baseline `3ea644845c975fbf1beae329b158a6a41e624f41`.

## Global Constraints

- Keep real Provider requests, Search requests, push, Railway deployment, and real canaries at zero.
- Do not modify prompts, AI Reference contracts, provider configuration, model selection, retry/fallback behavior, Stage A, or beta environments.
- Preserve normal Solutions regeneration and ordinary document routes.
- Use explicit evaluation context; never use global/latest/timestamp lookup.
- Durable evaluation creation, persistent readback, artifact target preparation, and strict Stage B guard must precede any Solutions provider dispatch.
- PRD execution must remain local and provider-free.
- All operator output and receipt metadata must remain sanitized; response bodies are private artifacts only.
- This repository has no callable subagent dispatcher in the current tool surface; execute the plan inline and record that review limitation in the progress ledger.

---

## Task 1: Establish red tests for missing Phase 1A paths

**Files:** `tests/test_stage_b_product_flow_phase1a.py`

- [ ] Add fixtures for isolated SQLite, fake managed runtime/adapter, fake receipt store, and synthetic project/snapshot/solution data using existing test factories.
- [ ] Add a RED test proving `solutions-canary` has no supported operator path that creates and independently reads a durable evaluation before runtime dispatch.
- [ ] Add a RED test proving evaluation-create failure produces zero dispatches, zero transports, and no provider adapter call.
- [ ] Add a RED test proving pre-transport readback failure produces zero dispatches and zero transports.
- [ ] Add a RED test proving an explicit evaluation context is required for deterministic evaluation→dispatch linkage and two interleaved evaluations cannot cross-link.
- [ ] Add a RED test proving the local PRD operator path is absent or cannot coordinate evaluation metadata, selected-solution precheck, inheritance evidence, and document persistence.
- [ ] Run only this new file and verify the failures are due to the missing execution paths, not an intentionally false assertion.

## Task 2: Add explicit Solutions execution policy and context propagation

**Files:** `app/services/stage_b_evaluation.py`, `app/services/ai_runtime.py`, `app/services/solution_design.py`

- [ ] Add a focused immutable policy type for canary coordination with `validation_regeneration_allowed` and `max_provider_transports`, retaining normal behavior as the default.
- [ ] Extend managed sync and async `design_solutions` signatures with optional `evaluation_context` and pass it explicitly into the existing `_call`/`_call_async` boundary.
- [ ] Extend `SolutionDesignService.generate` and its async counterpart with optional evaluation context and execution policy, preserving ordinary route defaults.
- [ ] Make validation regeneration policy explicit: normal calls retain existing one-regeneration behavior; the canary policy disables regeneration without changing the validator or adding retries.
- [ ] Ensure dispatch control is derived from the passed context and existing ledger linkage is reused; do not introduce latest-evaluation or module-global state.
- [ ] Run the focused context, policy, runtime, and ordinary Solutions tests.

## Task 3: Implement CLI-only Stage B Solutions canary

**Files:** `scripts/stage_b_evaluation_inspect.py`, `app/services/stage_b_evaluation.py`, `tests/test_stage_b_product_flow_phase1a.py`

- [ ] Add a `solutions-canary` operator command and safe help output without secret access, evaluation creation, budget consumption, Provider, or Search calls.
- [ ] Implement guard → project lookup → durable evaluation create → fresh repository readback → artifact target preparation → explicit context/policy → existing `SolutionDesignService` order.
- [ ] Finalize success/failure through the existing receipt store and private artifact contract with safe metadata only.
- [ ] Add a strict one-transport guard around the canary execution policy and preserve zero retry/fallback semantics.
- [ ] Record selected candidate IDs and deterministic ordering as metadata without persisting solution body values in ordinary receipts.
- [ ] Add fake success, fake validation failure, fake 503, linkage, cross-evaluation isolation, and persistence tests.

## Task 4: Implement CLI-only local PRD canary

**Files:** `scripts/stage_b_evaluation_inspect.py`, `app/services/stage_b_evaluation.py`, `tests/test_stage_b_product_flow_phase1a.py`

- [ ] Add a `local-prd-canary` command with explicit project and selected-solution identifiers and safe help behavior.
- [ ] Implement guard → project/selected-solution prechecks → durable evaluation create/readback → safe selected-solution metadata → existing `DocumentLoop.run` with local generator.
- [ ] Verify snapshot inheritance and document version persistence using the existing document tables and dependency records; do not create a new document generator.
- [ ] Ensure PRD path records provider dispatch/transport as zero and distinguishes pre-transport/application failures from document validation failures.
- [ ] Add idempotency, missing-selection, inheritance, persistence, cross-process readback, and zero-provider tests.

## Task 5: Regression, security, and route-boundary verification

**Files:** tests and progress ledger only unless a test exposes a bounded defect.

- [ ] Run targeted Phase 1A, Stage B evaluation, provider observability, Solutions, document lifecycle, idempotency, API leak, and route enumeration suites.
- [ ] Verify no new public diagnostic route and ordinary route behavior remains unchanged.
- [ ] Verify safe receipt metadata has no response values, previews, prompts, secrets, or private artifact body.
- [ ] Run compileall, JavaScript syntax checks where applicable, `git diff --check`, and fallback static secret scan.
- [ ] Run the full backend suite if feasible and compare only against the known baseline failures; require new failure delta zero.

## Task 6: Fresh review and completion gate

- [ ] Perform a fresh whole-branch review against the approved scope, explicitly checking context propagation, pre-readback fail-closed behavior, route boundary, no duplicate generation logic, and preserved normal regeneration.
- [ ] Update the progress ledger with exact commands, observed results, real-call counters, budget, and any known test baseline.
- [ ] Confirm worktree clean and create one local candidate commit only after all verification passes; do not push or deploy.
- [ ] Report `STAGE_B_PRODUCT_FLOW_PHASE1A_EXECUTION_PATHS_READY` only if all success-contract gates pass; otherwise report the confirmed blocker without claiming readiness.
