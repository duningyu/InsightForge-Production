# Stage B Phase 2 Local TechDoc and Handoff Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CLI-only, Stage-B-only Phase 2 canary path that confirms the existing PRD, generates and confirms a local TechDoc, acknowledges unresolved items through the existing formal acknowledgement contract, and assembles a local Handoff package. The path must be provider-free, search-free, idempotent, durable-observable, and fail closed on stale or unconfirmed artifacts.

**Architecture:** Reuse the existing `DocumentVersionService.confirm`, `DocumentLoop.run(..., "techdoc", require_snapshot=True)`, `LocalDocumentGenerator`, `HandoffService.readiness`, `HandoffService.acknowledge_unresolved`, and `HandoffService.build_zip`. Add only the Phase 2 operator orchestration and sanitized receipt metadata in `scripts/stage_b_evaluation_inspect.py`; do not add public routes, alter domain schemas, or change ordinary document/handoff behavior. Each canary operation creates a durable Stage-B evaluation before any product mutation, performs an independent pre-mutation readback, carries an explicit evaluation context, and records only identifiers, statuses, versions, counts, hashes, and safe failure classifications.

**Tech Stack:** Python 3.10-compatible application code, FastAPI route/service contracts, SQLite repositories, Pydantic schemas, existing `DocumentLoop`/`LocalDocumentGenerator`, `HandoffService`, `StageBEvaluationReceiptStore`, pytest, and the existing CLI operator.

**Spec:** Baseline `ff77fcfb5fc0fbe7c349bb678a34e381d0e1037d`; current synthetic project `project_seed_phase1a_synthetic`; selected solution `solution_6199e5ad886d47769e835c311f7d0ec6`; current PRD `version_086d648bfe404f689bc7512e88bd3d8f`, logical version 1, validation passed, active/draft. Phase 2 has zero real Provider transports and zero Search requests; its expected durable budget remains `6 -> 6` and safe ceiling `5 -> 5`.

## Global Constraints

- Use `superpowers:using-git-worktrees` before implementation and keep implementation work isolated from the deployment checkout.
- Use `superpowers:test-driven-development`: every task below is RED, verify RED, minimal GREEN, verify GREEN, then regression; do not write production code before its RED test fails for the intended reason.
- Use `superpowers:systematic-debugging` for failures and `superpowers:verification-before-completion` before claiming readiness.
- Use `superpowers:requesting-code-review` for a fresh whole-branch review before merge; the reviewer must inspect the diff and the evidence, not infer behavior from filenames.
- No real Provider, Search, AI Reference, Solutions generation, PRD regeneration, TechDoc generation, Handoff export, document confirmation, snapshot/version creation, Railway operation, public API change, migration, or mutation of the persistent Stage-B project during implementation and tests.
- Ordinary routes remain unchanged: `POST /api/projects/{project_id}/documents/generate`, `POST /api/document-versions/{version_id}/confirm`, Handoff readiness/acknowledgement/export routes, and their existing DTO/domain boundaries.
- Do not add a database migration. Required acknowledgement and handoff persistence already exists: `handoff_unresolved_acknowledgements`, `handoff_runs`, `documents`, `document_versions`, `generation_runs`, `artifact_dependencies`, and audit tables.
- Do not persist or print document text, prompts, Provider payloads, ZIP contents, previews, secrets, cookies, or private artifact bodies in ordinary receipts or test output.

---

## Task 1: Lock the Phase 2 operator contract and safe metadata

**Files:** `scripts/stage_b_evaluation_inspect.py`, `tests/test_stage_b_phase2_local_techdoc_handoff.py`

- [ ] **RED:** Add CLI contract tests for four commands in the existing operator module: `confirm-prd-canary`, `local-techdoc-canary`, `confirm-techdoc-canary`, and `handoff-canary`. Assert the commands are currently absent or return the current unsupported-command result, so the failure is specifically the missing Phase 2 contract.
- [ ] **Verify RED:** Run `python -m pytest tests/test_stage_b_phase2_local_techdoc_handoff.py -q`; record the expected command-contract failures and ensure no Provider/Search tripwire fired.
- [ ] Define exact argument contracts using the existing CLI conventions: required `--project-id`, optional idempotency key only where the existing operator supports it, no arbitrary document text, no Provider/model flags, and no public route. Help branches must execute before evaluation creation.
- [ ] Define operation names and sanitized receipt metadata: `PHASE2_PRD_CONFIRM`, `PHASE2_TECHDOC_GENERATE`, `PHASE2_TECHDOC_CONFIRM`, and `PHASE2_HANDOFF`; include project ID, selected solution ID, document/version IDs, snapshot ID, acknowledgement ID/content hash, handoff run ID/package hash, status, counts, and terminal stage only.
- [ ] Define idempotency keys deterministically from project ID plus operation name and current prerequisite identity. A repeated operation must reuse the matching successful/current result; ambiguous matching receipts must fail closed rather than select latest/first.
- [ ] **GREEN:** Add the command dispatch/help text and typed internal orchestration entry points, but keep all execution branches behind the later task implementations.
- [ ] **Verify GREEN:** Run the command help tests and assert help creates no evaluation, no product row, no artifact, no Provider dispatch, no Search request, and no budget change.
- [ ] Commit only the operator-contract test and implementation changes: `feat: define stage-b phase2 local canary operators`.

## Task 2: Implement PRD confirmation with durable preflight

**Files:** `scripts/stage_b_evaluation_inspect.py`, `tests/test_stage_b_phase2_local_techdoc_handoff.py`

- [ ] **RED:** Add isolated-database tests where the current PRD is validation-passed but unconfirmed. Assert `confirm-prd-canary` currently cannot produce the required durable-before-mutation receipt, explicit context, confirmation status, and idempotent result.
- [ ] **Verify RED:** Run only the new confirmation tests with a fake Provider adapter and Search client that raise if called; confirm the failure is orchestration absence, not a fixture or schema failure.
- [ ] Preflight project ownership/Stage-B identity, current snapshot, selected solution, active PRD, validation status, lifecycle, and version identity using existing repositories/services. Reject missing, stale, archived, or ambiguous prerequisites before mutation.
- [ ] Create and persist the Phase 2 evaluation with `StageBEvaluationReceiptStore` before calling `DocumentVersionService.confirm`; independently read back status, project ID, prerequisite version, dispatch/transport counters, and private artifact target.
- [ ] Invoke `DocumentVersionService.confirm(version_id, actor=<synthetic Phase2 operator>, note=<bounded operator note>, human_confirmed=True)` directly through the service contract. Do not call the public HTTP route from the operator and do not synthesize a confirmation row.
- [ ] Finalize a sanitized receipt containing confirmation status/version and audit linkage. On failure, record the terminal stage and leave the existing service transaction semantics in control; never retry.
- [ ] **GREEN:** Implement the smallest orchestration satisfying the tests; preserve the ordinary confirmation route and `DocumentVersionService.confirm` behavior.
- [ ] **Verify GREEN:** Assert PRD becomes approved/current exactly once, rerun is idempotent, stale/missing/invalid PRD fails closed, and Provider/Search/budget remain zero/unchanged.
- [ ] Commit: `feat: add stage-b phase2 prd confirmation canary`.

## Task 3: Implement local TechDoc generation and confirmation

**Files:** `scripts/stage_b_evaluation_inspect.py`, `tests/test_stage_b_phase2_local_techdoc_handoff.py`

- [ ] **RED:** Add isolated tests for `local-techdoc-canary` with a confirmed PRD and selected solution. Assert the current implementation lacks the required durable evaluation/readback, explicit context, safe receipt, and operator idempotency.
- [ ] **Verify RED:** Run the TechDoc tests with Provider, Search, and QuickStart tripwires; verify the RED failure occurs before any generation call and no product mutation remains.
- [ ] Preflight the exact current project, snapshot, selected solution, confirmed/current PRD, and absence of a conflicting current TechDoc. Bind the operation to the selected snapshot and PRD version; reject stale or mismatched inputs.
- [ ] Create the durable evaluation and independently read it back before invoking `DocumentLoop.run(project_id, "techdoc", idempotency_key=<deterministic key>, require_snapshot=True, competitor_snapshot_id=None, use_competitor_snapshot=False)`.
- [ ] Reuse the application’s existing `DocumentLoop` and `LocalDocumentGenerator` exactly; do not create a TechDoc Provider path, new generator, new schema, or new prompt. Preserve the existing local validation/repair semantics and record rounds/status without exposing content.
- [ ] After the loop returns, verify the persisted document/version is current, bound to the expected snapshot and confirmed PRD, and contains the selected-solution identity through existing dependency/metadata paths. Finalize safe receipt metadata and private artifact metadata only.
- [ ] Add `confirm-techdoc-canary` using the same durable preflight pattern and `DocumentVersionService.confirm`; it must reject unvalidated, stale, or unbound versions and be idempotent for an already approved current version.
- [ ] **GREEN:** Implement both commands with explicit context objects and fail-closed prerequisite checks; do not alter `DocumentLoop`, `LocalDocumentGenerator`, or ordinary route semantics.
- [ ] **Verify GREEN:** Assert one current TechDoc/version, selected-solution inheritance, PRD-version binding, local generator mode, no Provider/Search/QuickStart calls, no raw content in receipts, and idempotent reruns.
- [ ] Commit: `feat: add local techdoc phase2 canary path`.

## Task 4: Implement formal unresolved acknowledgement and local Handoff canary

**Files:** `scripts/stage_b_evaluation_inspect.py`, `tests/test_stage_b_phase2_local_techdoc_handoff.py`

- [ ] **RED:** Add tests showing `handoff-canary` currently lacks a CLI execution path even though `HandoffService.readiness`, `acknowledge_unresolved`, and `build_zip` already exist. Include cases for missing/unconfirmed/stale TechDoc, missing acknowledgement, and a valid fully prepared project.
- [ ] **Verify RED:** Run these tests with fake Provider/Search tripwires and assert failures occur before any Handoff mutation or ZIP assembly.
- [ ] Preflight current snapshot, selected solution, approved/current PRD and TechDoc, version/dependency bindings, validation and artifact health, and readiness. Refuse latest-row heuristics, stale versions, mismatched project IDs, or unresolved ambiguity.
- [ ] Create the durable `PHASE2_HANDOFF` evaluation and independently read it back before any acknowledgement or export mutation. Carry explicit project, snapshot, PRD, TechDoc, selected-solution, and evaluation identity through the call chain.
- [ ] If readiness requires acknowledgement, invoke `HandoffService.acknowledge_unresolved(project_id, actor=<synthetic Phase2 operator>, confirmed=True, note=<bounded note>)`. Reuse its existing `content_sha256`-based idempotency and `handoff_unresolved_acknowledgements` table; record only acknowledgement ID/hash/items count/source count.
- [ ] Re-read readiness after acknowledgement. Stop without export if readiness remains blocked; do not silently confirm documents or regenerate anything.
- [ ] Invoke `HandoffService.build_zip(project_id, target_client="generic", actor=<synthetic Phase2 operator>)` locally only after readiness passes. Record handoff run/package/artifact metadata and hash, never package contents.
- [ ] **GREEN:** Implement the handoff command as local assembly only. Preserve all public Handoff routes and existing acknowledgement validation. Do not add a Provider adapter, document generator, migration, or retry.
- [ ] **Verify GREEN:** Assert valid flow reaches a persisted Handoff run/package, acknowledgement is idempotent, stale or unconfirmed inputs fail closed, version mismatch never regenerates, and all Provider/Search counters remain zero.
- [ ] Commit: `feat: add local phase2 handoff canary path`.

## Task 5: Add cross-operation isolation, immutability, and safety regressions

**Files:** `tests/test_stage_b_phase2_local_techdoc_handoff.py`, `tests/test_stage_b_product_flow_phase1a.py`, `tests/test_v3_handoff_and_tools.py`, `tests/test_v3_document_health.py`

- [ ] **RED:** Add full-sequence isolated-fixture tests for `confirm-prd-canary -> local-techdoc-canary -> confirm-techdoc-canary -> handoff-canary`; assert the new operator does not yet satisfy all required counts, bindings, and receipt linkage.
- [ ] **Verify RED:** Run the sequence with independent evaluator IDs and assert the failing assertion is the missing Phase 2 behavior, while the existing Phase1A and V3 tests remain green.
- [ ] Verify cross-evaluation isolation: no latest-evaluation lookup, global mutable context, timestamp matching, or receipt reuse across different project/version/snapshot identities.
- [ ] Verify ordinary routes do not auto-create Phase 2 evaluations and retain existing DTO/domain responses; enumerate routes and assert no new public Phase 2 endpoint exists.
- [ ] Verify project/document immutability boundaries: no Solutions regeneration/reselection, no PRD regeneration, no snapshot creation, no source creation, no TechDoc/Handoff content in receipts, and no changes to unrelated AI surfaces.
- [ ] Verify failure-stop policy: PRD confirmation failure stops TechDoc; TechDoc failure or confirmation failure stops Handoff; readiness/version/acknowledgement failure prevents export; no automatic or manual retry is added.
- [ ] Verify safe metadata includes operation/evaluation IDs, binding IDs, statuses, counts, hashes, and terminal stages only; assert raw document text, prompts, Provider payloads, internal errors, and private artifact bodies are absent.
- [ ] **GREEN:** Complete only the missing assertions and narrowly scoped operator plumbing required by the preceding tasks.
- [ ] **Verify GREEN:** Run the isolated sequence and all existing V3/Phase1A regressions; assert project data changes only in the explicitly authorized future canary path and tests use temporary storage.
- [ ] Commit: `test: cover stage-b phase2 isolation and stop policy`.

## Task 6: Run targeted and whole-branch verification

**Files:** no production changes expected; review `scripts/stage_b_evaluation_inspect.py`, `tests/test_stage_b_phase2_local_techdoc_handoff.py`, and the commits above.

- [ ] **RED:** Run the fresh targeted suite before any final cleanup and record any failure by test node and signature; do not classify an unrelated baseline failure as a Phase 2 defect.
- [ ] **Verify RED:** Confirm the test environment is isolated and all Provider/Search tripwires are still zero.
- [ ] Run targeted tests: `python -m pytest tests/test_stage_b_phase2_local_techdoc_handoff.py tests/test_stage_b_product_flow_phase1a.py tests/test_v3_handoff_and_tools.py tests/test_v3_document_health.py tests/test_v3_document_lifecycle.py -q`.
- [ ] Run full backend tests with the established baseline comparison; preserve the known 12 pre-existing failures by node/signature and require `new_failure_delta=0`.
- [ ] Run available frontend/relevant harness tests, `python -m compileall app scripts tests`, JavaScript syntax checks for changed frontend-adjacent assets if applicable, `git diff --check`, and the repository secret scan. Do not run deployment, Railway SSH, a real operator, Search, or any Provider-connected test.
- [ ] Inspect the final diff for only Phase 2 CLI/orchestration/tests/docs, no domain schema changes, no migrations, no route additions, no transport/retry/fallback/budget changes, and no unrelated AI-surface modifications.
- [ ] Request a fresh whole-branch review. The reviewer must explicitly verify local TechDoc mode, formal acknowledgement reuse, Handoff local assembly, version binding, stop policy, safe receipts, ordinary-route compatibility, and zero Provider/Search behavior.
- [ ] Apply only review-confirmed plan-scope fixes with a new RED test first; rerun the affected targeted tests and whole regression.
- [ ] **GREEN:** Mark the plan implementation candidate ready only when targeted tests pass, new failure delta is zero, review passes, worktree contains only intended implementation commits, and no external state was touched.
- [ ] Commit any final test-only/review-confirmed change with a scoped message; never amend or hide unrelated changes.

## Acceptance Evidence and Future Canary Contract

- [ ] Future Phase 2 authorization must use the four existing-operator commands in this order and may execute only on the proven synthetic Stage-B project. The plan implementation itself must not execute them.
- [ ] Expected future Provider transport count is `0`; expected Search count is `0`; expected durable budget is `6 -> 6`; expected safe ceiling is `5 -> 5`.
- [ ] Future success evidence: PRD approved/current and version ID; TechDoc generation run/document/version IDs, snapshot and PRD dependency IDs, selected-solution identity, validation/health state; TechDoc approval status; Handoff readiness before/after acknowledgement; acknowledgement ID/content hash; Handoff run/package hash and persistence status.
- [ ] Future failure evidence: durable receipt before the failing mutation, explicit terminal stage, prerequisite/version mismatch, no downstream step after failure, no raw content, and zero Provider/Search counters.
- [ ] Future browser verification is read-only only after the operator proves the corresponding page load does not auto-generate. If that cannot be proven from source, omit browser verification and report it as blocked to prevent mutation.
- [ ] No real Phase 2 canary is authorized by this plan. A separate explicit authorization is required after implementation review and deployment readiness.

## Final Self-Review Checklist

- [ ] Every planned production change has an exact file, symbol/contract, RED test, GREEN implementation, and verification command.
- [ ] Existing `DocumentLoop`, `LocalDocumentGenerator`, `DocumentVersionService.confirm`, `HandoffService.readiness`, `HandoffService.acknowledge_unresolved`, and `HandoffService.build_zip` are reused without semantic changes.
- [ ] No new database migration, public route, Provider/Search path, retry, fallback, budget rule, or frontend behavior is planned.
- [ ] Acknowledgement persistence is explicitly tied to `handoff_unresolved_acknowledgements` and its `(project_id, content_sha256)` uniqueness contract.
- [ ] The plan distinguishes local document generation/assembly from real AI generation and never treats synthetic evidence as real research.
- [ ] The final implementation must be run through `superpowers:verification-before-completion` and a fresh code review before any deployment or real-canary authorization.
