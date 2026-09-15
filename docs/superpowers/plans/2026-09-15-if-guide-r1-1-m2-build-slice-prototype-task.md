# IF Guide R1.1 M2 Build Slice / Prototype Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the current IF Guide R1.1 project workspace with a bounded, rule-first M2 flow that turns a validated project and its current confirmed context into a user-confirmed Build Slice and an editable, evidence-bound Prototype Task. The flow ends at a confirmed implementation handoff description; it does not execute work, submit results, review completion, recover failed work, export a formal Handoff package, or perform external actions.

**Architecture:** Reuse the existing project, actor, intent, snapshot, migration, quality-evaluation, and frontend shell contracts. Add a project-scoped Build Slice aggregate and a Prototype Task aggregate with optimistic revisions and exact snapshot/intent bindings. Generate the first Prototype Task deterministically from confirmed user state and explicit scope. Extend the existing `ArtifactQualityEvaluation` subsystem for `BUILD_SLICE` and `PROTOTYPE_TASK`; do not create a second quality ledger. Keep the formal `HandoffService` unchanged and expose only a read-only readiness summary for the M2 boundary.

**Tech Stack:** Python 3.12 for verification, FastAPI, the existing SQLite `Database` abstraction, current migration registration in `app/db.py`, existing Pydantic schemas in `app/schemas.py`, existing `ProjectService`, `ProjectIntentService`, `SnapshotService`, `QualityEvaluationService`, `ArtifactHealthService`, vanilla frontend code in `app/static/app.js`, `app/static/index.html`, and the current pytest/Playwright-style local verification patterns.

**Spec:** `docs/mainline/IF_GUIDE_R1/WORKSPACE_MAP.md`, the IF Guide R1.1 M2 requirements in `Codex_REVIEW_FREEZE_IF_GUIDE_R1_1_M1_AND_PLAN_M2_20260915.md`, and the approved product/quality source documents supplied for IF Guide R1.1. The implementation must preserve the already-frozen M1 commit `c04ee034ad1d4e5ed35c909fd5cdd5be60cc322e` and must not revive the earlier Real Idea Batch work.

## Global Constraints

- M2 is limited to `validated/continued project -> BUILD_SLICE -> user confirmation -> PROTOTYPE_TASK -> inspect/edit/confirm -> explicit acceptance steps`.
- M2 must not implement ActionSubmission, ActionReview, a completed-work or blocked-work loop, Recovery, a decision engine, M4 experiments, public deployment automation, a general AI coding IDE, automatic GitHub or terminal actions, payments, subscriptions, or Real Idea Batch behavior.
- All writes are project-scoped and actor-scoped. Every read and mutation verifies the current project, the authoritative actor, current active status, and expected revision. A cross-account access attempt is denied without revealing another account's state.
- The current active snapshot and current M1 intent/action revision are the only valid upstream bindings. No latest-row heuristic, timestamp matching, global mutable context, or project-wide fallback may substitute for an exact binding.
- The initial implementation is rule-first and local. It makes zero Provider and zero Search calls. No Provider budget, dispatch ledger, transport reservation, or real Stage B state is touched by M2.
- A user-facing “ready to hand to a coding tool/user” state is descriptive only. It is not `HandoffService.build_zip`, `_build_v3_zip`, an export, a network action, a repository action, or a deployment.
- Do not weaken existing formal Handoff gates. M2 may call `HandoffService.readiness` only in a read-only compatibility check when the exact current contracts are available; it must not confirm documents, acknowledge unresolved items, or export artifacts.
- Do not claim that code was executed, tested, deployed, verified, or externally observed unless the corresponding evidence is stored as an allowed safe metadata field and actually exists. Unknown dependencies remain `UNKNOWN`.
- Use `apply_patch` for repository edits. Each task is implemented RED -> minimum GREEN -> targeted regression -> fresh review -> commit. Each commit must contain only the task's intended files.
- The final M2 implementation stops after Build Slice confirmation, Prototype Task creation/edit/save/reopen/confirmation, acceptance completeness, quality checks, and the browser happy path. It does not continue into M3.

## Current Source Mapping and Reuse Boundaries

The following mapping is the implementation authority for this plan. A task may refine an interface only after a RED test demonstrates that the mapped contract is insufficient; it must not create an overlapping subsystem.

| Concern | Existing path and symbol | M2 use |
|---|---|---|
| Application construction and route registration | `app/main.py`, `create_app`, lifespan state, existing project routes | Register M2 services using the existing app factory and actor header convention; do not add a public deployment route. |
| Actor and project access | `app/services/projects.py`, `ProjectService`; project lookup/status checks in `app/services/project_intent.py` | Reuse project existence, active-state, and owner checks. M2 services must not infer ownership from title or client-provided metadata. |
| M1 intent and action | `app/services/project_intent.py`, `ProjectIntentService`; `project_intents`, `first_action_cards` | Read the latest confirmed M1 intent and action revision; preserve purpose-specific templates, raw idea, action revision, and M1 quality evidence. |
| M1 API validation | `app/schemas.py`, `ProjectIntentUpsertRequest`, `FirstActionUpdateRequest`, `FirstActionConfirmRequest` | Follow existing Pydantic validation and `ConflictError` -> HTTP 409 behavior for M2 requests. |
| Selected solution context | `app/services/snapshots.py`, `SnapshotService.confirm_initial_solution`, `get_current`, `get`, `list_versions` | When a project has a current snapshot, bind the Build Slice to its exact `snapshot_id` and version; include only safe structured fields required by the slice. |
| Local document generation | `app/services/loop.py`, `DocumentLoop` and `LocalDocumentGenerator` | Not used for M2 task generation. M2 is a rule-first scope/task transformation, not PRD/TechDoc generation. |
| Formal Handoff | `app/services/handoff.py`, `HandoffService.readiness`, `preview_manifest`, `build_zip`, `_build_v3_zip` | Preserve unchanged. M2 never exports or acknowledges; any readiness display is read-only and clearly separate from a formal Handoff. |
| Quality evaluation | `app/services/real_idea_metrics.py`, `ArtifactQualityEvaluation`, `QualityEvaluationService`, `RealIdeaMetricsService` | Extend artifact type validation and quality bindings for `BUILD_SLICE` and `PROTOTYPE_TASK`; keep immutable revisions, safe evidence, and P0/P1/P2 semantics. |
| Artifact health | `app/services/artifact_health.py` | Reuse conservative, deterministic health/event patterns where the M2 quality implementation needs status recomputation. |
| Migrations | `app/migrations/if_guide_m1.py`, `app/migrations/real_idea_evaluation_v1.py`, registration in `app/db.py` | Add one M2 migration with idempotent DDL and explicit registration. Do not alter the historical M1 migration. |
| Frontend shell | `app/static/app.js`, `app/static/index.html`, `app/static/styles.css` | Extend the existing project view incrementally; preserve current M1 behavior and refresh/reopen semantics. |
| Verification | `tests/test_if_guide_m1.py` and existing account/snapshot/document/Handoff suites | Add narrow M2 unit/API/browser coverage, then run the required regression matrix without Provider/Search. |

## Domain and Persistence Contract

### Build Slice

Create `BuildSliceService` as the authoritative project-scoped service. The aggregate represents the smallest user flow to implement now and carries:

- `slice_id`, `project_id`, `owner_actor`, `revision`, `status`, `created_at`, `updated_at`, `confirmed_at`;
- `snapshot_id` and `snapshot_version` when a current snapshot is used;
- `intent_revision` and `action_revision` from the confirmed M1 context;
- `purpose`, `confirmed_constraints`, and a safe result/evidence context reference;
- `scope_in`, `scope_out`, `inputs`, `expected_outputs`, `acceptance_steps`, `error_handling`, `unknowns`, `constraint_notes`;
- quality status and immutable quality-evaluation references through the existing quality subsystem, not copied evaluation logic.

The service interface is:

```text
BuildSliceService.get_current(project_id, actor) -> BuildSliceResponse | None
BuildSliceService.create_or_get(project_id, actor, expected_snapshot_id, expected_intent_revision) -> BuildSliceResponse
BuildSliceService.update(project_id, actor, slice_id, expected_revision, patch) -> BuildSliceResponse
BuildSliceService.confirm(project_id, actor, slice_id, expected_revision) -> BuildSliceResponse
BuildSliceService.evaluate_p0(project_id, actor, slice_id) -> QualityStatus
```

`create_or_get` is idempotent only for the same project, actor, exact upstream bindings, and current revision. A stale or mismatched binding fails closed; it never silently reuses a slice from another revision. `update` resets a prior confirmation and increments `revision`. `confirm` requires a final P0 PASS and the exact expected revision.

### Prototype Task

Create `PrototypeTaskService` as the authoritative task service. It consumes a confirmed Build Slice and produces a bounded implementation description. The aggregate carries:

- `task_id`, `project_id`, `slice_id`, `owner_actor`, `snapshot_id`, `slice_revision`, `revision`, `status`, `created_at`, `updated_at`, `confirmed_at`;
- `purpose`;
- `scope`, `inputs`, `expected_outputs`;
- `existing_behaviors_to_preserve`, `explicit_non_goals`, `known_technical_context`, `unknown_dependencies`;
- `implementation_tasks`, `acceptance_steps`, `failure_recovery_notes`, `required_return_evidence`, `permission_risk_notes`;
- safe quality status and immutable quality-evaluation references.

The service interface is:

```text
PrototypeTaskService.get_current(project_id, actor) -> PrototypeTaskResponse | None
PrototypeTaskService.generate_rule_first(project_id, actor, slice_id, expected_slice_revision) -> PrototypeTaskResponse
PrototypeTaskService.update(project_id, actor, task_id, expected_revision, patch) -> PrototypeTaskResponse
PrototypeTaskService.confirm(project_id, actor, task_id, expected_revision) -> PrototypeTaskResponse
PrototypeTaskService.evaluate_p0(project_id, actor, task_id) -> QualityStatus
```

Rule-first generation reads only the confirmed Build Slice, M1 purpose/constraints, and exact snapshot fields when bound. It may state an unknown dependency, but it must never invent a file, command, API, environment, test result, deployment result, or external verification. `PROTOTYPE_TASK` is not `FORMAL_HANDOFF`.

### Tables and bindings

Add `app/migrations/if_guide_m2.py` with idempotent DDL for `build_slices` and `prototype_tasks`. Both tables use project and actor ownership, monotonic revisions, explicit status checks, timestamps, and composite bindings. The slice has a unique current row per project/upstream revision; the task has a unique current row per slice revision. Foreign keys point to the project and, when used, the exact snapshot. The service still rechecks current snapshot and M1 intent/action values because a foreign key alone does not establish currentness.

Extend the existing `real_idea_quality_evaluations.artifact_type` contract in a new migration rather than creating another quality table. Add `BUILD_SLICE` and `PROTOTYPE_TASK` as allowed artifact types, preserving append-only revision triggers, evidence hashes, project/sample/binding fields, and P0/P1/P2 layers. The migration must be safe on a database that already has the four historical artifact types.

## Quality Contract

M2 uses the current `ArtifactQualityEvaluation` interface and its immutable revision model. The quality object must bind `project_id`, `owner_actor`, `artifact_type`, `artifact_id`, `artifact_revision`, `snapshot_id` when applicable, `intent_revision`, `slice_id`, and `slice_revision` when applicable. A revision stores only safe structured evidence and an evidence hash; it never stores raw idea text, full artifact bodies, Provider payloads, acknowledgement prose, or private project content.

### P0 deterministic gates

The P0 evaluator returns `PASS`, `PARTIAL`, or `FAIL` with machine-readable codes. The following are hard failures:

- project missing, inactive, wrong actor, or cross-project binding;
- stale intent, action, snapshot, slice, or task revision;
- missing or empty required scope-in, scope-out/non-goals, inputs, outputs, or acceptance steps;
- acceptance item missing precondition/input, user action, expected result, or failure interpretation;
- a statement that says executed, tested, deployed, externally verified, or observed without evidence;
- a wrong snapshot or selected-solution binding when a snapshot is required;
- a forbidden automatic external action or a formal Handoff export attempt;
- a fabricated technical dependency marked verified;
- a critical upstream constraint contradicted by the downstream artifact;
- any empty/non-substantive critical field.

P0 PASS is an integrity gate, not human acceptance and not proof of implementation success.

### P1 structured metrics

Store deterministic or structured review results as immutable revisions under the existing quality service:

- **Scope Recall:** confirmed in-scope requirements represented by the Prototype Task divided by confirmed in-scope requirements.
- **Scope Precision:** task items actually in approved scope divided by all task items.
- **Acceptance Coverage:** critical build items with explicit acceptance steps divided by critical build items.
- **Acceptance Testability:** each acceptance item has an input/precondition, user action, expected result, and failure interpretation; report item-level pass/fail and aggregate coverage.
- **Constraint Preservation:** existing behaviors, explicit non-goals, permission constraints, and confirmed M1 constraints retained without contradiction.
- **Dependency Clarity:** unknown dependencies remain `UNKNOWN`; no invented file, command, API, environment, or verification claim is treated as known.
- **Unsupported Claim Rate:** unverified technical/product statements presented as facts divided by factual statements. Clearly labelled hypotheses are not counted as factual errors.

P1 records metric definitions, rubric version, evaluator role, input revision IDs, and safe evidence references. It does not convert an n=1 or n=3 observation into a statistical claim.

### P2 human support

P2 is a structured audit record for the idea/project owner and an independent human reviewer. An LLM may propose mapping or claim candidates, but it is never the sole Ground Truth or final evaluator. P2 can return `PASS`, `PARTIAL`, or `FAIL` and must preserve reviewer role, review revision, selected evidence IDs, and a safe hash without persisting private content.

### Status and revision semantics

Quality statuses are `PASS`, `PARTIAL`, and `FAIL`. P0 failure blocks confirmation. P1/P2 evidence is append-only; corrections create a new revision linked to the prior revision and never overwrite it. Binding mismatch, stale revision, or cross-project reuse is a hard integrity failure even if content scores look good.

## State Machine and API Boundary

Build Slice lifecycle: `DRAFT -> READY -> CONFIRMED`. A mutation after confirmation creates a new revision and returns to `READY` after P0 evaluation. Prototype Task lifecycle: `DRAFT -> READY -> CONFIRMED`; generation requires a confirmed current Build Slice, and a slice revision change invalidates the prior task confirmation.

The API uses the existing project route and actor style:

```text
GET  /api/projects/{project_id}/build-slice
PUT  /api/projects/{project_id}/build-slice
POST /api/projects/{project_id}/build-slice/confirm
GET  /api/projects/{project_id}/prototype-task
PUT  /api/projects/{project_id}/prototype-task
POST /api/projects/{project_id}/prototype-task/confirm
GET  /api/projects/{project_id}/build-slice/quality
GET  /api/projects/{project_id}/prototype-task/quality
```

All writes accept `expected_revision` and return HTTP 409 through the established `ConflictError` mapping when stale. Schemas reject blank critical content and non-substantive filler. Response payloads expose safe structured fields, state, revision, binding IDs, quality status/codes, and unknowns; they do not expose Provider payloads, private artifacts, or full historical evidence bodies.

There is no M2 route for deployment, repository write, terminal execution, Handoff export, acknowledgement, ActionSubmission, or ActionReview.

## Incremental Frontend Contract

Extend the current project panel in `app/static/index.html`, `app/static/app.js`, and `app/static/styles.css`. The flow is:

```text
current action/project context
-> define minimal flow
-> review scope in/out
-> inspect Prototype Task
-> edit and save
-> confirm ready
```

The UI must visibly render: 本轮做什么, 本轮不做什么, 输入, 输出, 开发任务, 如何验收, 出错怎么办, 哪些信息还不知道, current revision, binding identity, and quality status. It must preserve M1 save/confirm behavior and show conflict responses without silently discarding server state. The UI must not include a generic editor, automatic coding action, deployment action, or formal Handoff export control.

## TDD Task Sequence

### Task 1 — Define M2 migration and shared domain contracts

- [ ] **Files:** add `app/migrations/if_guide_m2.py`; modify `app/db.py`; add focused schema/domain tests under `tests/test_if_guide_m2_migration.py` and `tests/test_if_guide_m2_contracts.py`.
- **Interfaces consumed:** `Database.init_schema`, `if_guide_m1` tables, `real_idea_quality_evaluations`, existing migration version patterns.
- **Interfaces produced:** idempotent M2 migration registration, table names/columns/constraints, status enums, safe response/patch models for Build Slice and Prototype Task.
- **RED:** run `py -3.12 -m pytest -q tests/test_if_guide_m2_migration.py tests/test_if_guide_m2_contracts.py`; expected failure is missing `if_guide_m2` tables or contracts.
- **Minimal implementation:** add only the two M2 aggregate tables and the quality artifact-type extension migration path; apply each DDL statement idempotently and preserve historical rows/triggers. Define Pydantic models with non-blank critical-field validation and no external-action fields.
- **GREEN:** rerun the same command; expect migration creation, second initialization without duplicate errors, foreign-key and status checks, and schema validation to pass.
- **Regression:** `py -3.12 -m pytest -q tests/test_if_guide_m1.py tests/test_open_accounts.py`; expect all existing M1/account tests to remain green.
- **Commit:** `feat: add IF Guide R1.1 M2 domain schema`

### Task 2 — Implement Build Slice draft/read/update with exact upstream bindings

- [ ] **Files:** add `app/services/build_slice.py`; modify `app/main.py` service wiring only if required; add `tests/test_build_slice_service.py`.
- **Interfaces consumed:** `ProjectService` project lookup, `ProjectIntentService.get_intent`, `SnapshotService.get_current`, M2 schemas, `Database` context.
- **Interfaces produced:** `BuildSliceService.get_current`, `create_or_get`, `update`; safe `BuildSliceResponse` with project/actor/snapshot/intent/action revision bindings.
- **RED:** `py -3.12 -m pytest -q tests/test_build_slice_service.py -k "create or update or binding"`; expected failure is missing service methods and no persisted Build Slice.
- **Minimal implementation:** require an active project and authoritative actor; read the current confirmed M1 intent/action and current snapshot when the project has one; persist a DRAFT/READY slice with exact IDs and revisions. Reject wrong project, inactive project, cross-actor access, and mismatched expected snapshot/intent revision.
- **GREEN:** rerun the focused command; expect a slice to round-trip with exact bindings and an upstream mismatch to fail closed.
- **Regression:** `py -3.12 -m pytest -q tests/test_if_guide_m1.py tests/test_v3_snapshot_transaction.py`.
- **Commit:** `feat: add project-bound Build Slice service`

### Task 3 — Add Build Slice editing, P0 checks, and confirmation

- [ ] **Files:** modify `app/services/build_slice.py`; add `app/services/if_guide_m2_quality.py`; modify `app/schemas.py`; add `tests/test_build_slice_confirmation.py`.
- **Interfaces consumed:** Task 2 service, existing `ConflictError`, `QualityEvaluationService` P0 pattern, M1 revision fields.
- **Interfaces produced:** `BuildSliceService.update`, `confirm`, `evaluate_p0`; machine-readable P0 codes for missing scope, non-goals, acceptance, false execution claims, and stale bindings.
- **RED:** `py -3.12 -m pytest -q tests/test_build_slice_confirmation.py`; expected failure is absent 409 handling, absent hard-gate status, or confirmation of incomplete scope.
- **Minimal implementation:** validate explicit in-scope, out-of-scope, inputs, outputs, acceptance steps, error handling, and unknowns; increment revisions on edit; require the exact expected revision and P0 PASS before confirmation. Treat executed/tested/deployed assertions without evidence as hard failures.
- **GREEN:** rerun the focused command; expect complete scope to confirm, incomplete scope to fail, and stale updates/confirmation to return 409.
- **Regression:** `py -3.12 -m pytest -q tests/test_build_slice_service.py tests/test_if_guide_m1.py`.
- **Commit:** `feat: enforce Build Slice confirmation gates`

### Task 4 — Implement deterministic Prototype Task generation

- [ ] **Files:** add `app/services/prototype_task.py`; add `tests/test_prototype_task_generation.py`.
- **Interfaces consumed:** confirmed Build Slice service, M1 intent/action, exact Snapshot fields, M2 P0 evaluator.
- **Interfaces produced:** `PrototypeTaskService.generate_rule_first`, current task read model, deterministic task projection with required purpose/scope/inputs/outputs/non-goals/context/unknowns/tasks/acceptance/failure notes/evidence/risk fields.
- **RED:** `py -3.12 -m pytest -q tests/test_prototype_task_generation.py`; expected failure is no task generation and no confirmed-slice precondition.
- **Minimal implementation:** generate from approved fields only; preserve unknown dependencies as `UNKNOWN`; emit no Provider/Search calls and no claims of execution or deployment. Bind the task to exact project, actor, slice revision, and snapshot.
- **GREEN:** rerun the focused command; expect deterministic output for the same bound slice, correct purpose-specific differences, and rejection when the slice is not confirmed.
- **Regression:** `py -3.12 -m pytest -q tests/test_build_slice_confirmation.py tests/test_v3_snapshot_transaction.py`.
- **Commit:** `feat: add rule-first Prototype Task generation`

### Task 5 — Implement Prototype Task edit/save/confirm and stale invalidation

- [ ] **Files:** modify `app/services/prototype_task.py`; modify `app/schemas.py`; add `tests/test_prototype_task_lifecycle.py`.
- **Interfaces consumed:** Task 4 service, existing revision/conflict conventions, Build Slice revision.
- **Interfaces produced:** `PrototypeTaskService.update`, `confirm`, exact slice-revision invalidation, safe response with status/revision/quality state.
- **RED:** `py -3.12 -m pytest -q tests/test_prototype_task_lifecycle.py`; expected failure is missing edit persistence, stale 409, or confirmation of incomplete acceptance.
- **Minimal implementation:** apply actor/project checks, require expected task revision and current slice revision, reset confirmation on edit, and require complete acceptance contracts plus P0 PASS before confirmation.
- **GREEN:** rerun the focused command; expect edit/save/reopen, stale 409, cross-account denial, and successful confirmation only after complete acceptance.
- **Regression:** `py -3.12 -m pytest -q tests/test_prototype_task_generation.py tests/test_build_slice_confirmation.py tests/test_open_accounts.py`.
- **Commit:** `feat: add Prototype Task lifecycle controls`

### Task 6 — Extend existing quality evaluation for M2 artifact types

- [ ] **Files:** modify `app/services/real_idea_metrics.py`; modify the M2 migration from Task 1 only if its quality constraint requires a corrected migration; add `tests/test_m2_quality_bindings.py`.
- **Interfaces consumed:** `ArtifactQualityEvaluation`, `QualityEvaluationService.evaluate_p0`, `enqueue_p1`, `record_p2_review`, `revise`, immutable evidence sanitization.
- **Interfaces produced:** accepted artifact types `BUILD_SLICE` and `PROTOTYPE_TASK`, M2 binding fields, quality retrieval by exact artifact revision.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_quality_bindings.py -k "artifact_type or binding or immutable"`; expected failure is rejection of M2 artifact types or missing binding fields.
- **Minimal implementation:** extend the existing quality service and enum/check constraint without creating a second ledger. Keep P0/P1/P2 status semantics, append-only revisions, evidence hash, and sensitive-content rejection unchanged.
- **GREEN:** rerun the focused command; expect both M2 artifact types to persist safe metadata and a revision correction to append rather than overwrite.
- **Regression:** `py -3.12 -m pytest -q tests/test_real_idea_quality.py tests/test_m2_quality_bindings.py`.
- **Commit:** `feat: bind M2 artifacts to quality evaluations`

### Task 7 — Implement Scope Recall, Precision, Acceptance, Constraint, Dependency, and Claim metrics

- [ ] **Files:** modify `app/services/if_guide_m2_quality.py`; modify `app/services/real_idea_metrics.py` only for shared metric registration; add `tests/test_m2_quality_metrics.py`.
- **Interfaces consumed:** confirmed Build Slice/Prototype Task payloads, immutable quality service, P0 result codes.
- **Interfaces produced:** deterministic P1 metric result schema for Scope Recall, Scope Precision, Acceptance Coverage, Acceptance Testability, Constraint Preservation, Dependency Clarity, and Unsupported Claim Rate.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_quality_metrics.py`; expected failure is absent metric keys or incorrect denominators.
- **Minimal implementation:** use explicit rubric inputs and item IDs; distinguish structural identity from semantic content; label hypotheses separately from factual claims; persist rubric version and safe evidence IDs.
- **GREEN:** rerun the focused command; expect exact numerator/denominator calculations, failure on missing critical evidence, and no fabricated dependency classified as known.
- **Regression:** `py -3.12 -m pytest -q tests/test_m2_quality_bindings.py tests/test_real_idea_quality.py`.
- **Commit:** `feat: add M2 artifact quality metrics`

### Task 8 — Add P2 human-audit support and immutable quality revision checks

- [ ] **Files:** modify `app/services/if_guide_m2_quality.py`; modify `app/services/real_idea_metrics.py` only through shared interfaces; add `tests/test_m2_quality_audit.py`.
- **Interfaces consumed:** existing annotation roles and safe evidence sanitizer, `record_p2_review`, `revise`.
- **Interfaces produced:** P2 role-aware audit payloads for idea/project owner and independent human reviewer; LLM-assisted candidate annotations explicitly marked non-authoritative.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_quality_audit.py`; expected failure is missing role validation, mutable evidence, or acceptance of full artifact body.
- **Minimal implementation:** enforce reviewer role, rubric version, bound artifact revision, safe evidence IDs, and append-only corrections. Reject raw idea, full document body, Provider payload, acknowledgement prose, and private artifact content.
- **GREEN:** rerun the focused command; expect safe audit persistence, immutable prior revision, and rejection of unsafe evidence.
- **Regression:** `py -3.12 -m pytest -q tests/test_m2_quality_metrics.py tests/test_real_idea_quality.py`.
- **Commit:** `feat: add immutable M2 quality audit records`

### Task 9 — Expose M2 routes with actor isolation and conflict semantics

- [ ] **Files:** modify `app/main.py`; modify `app/schemas.py`; add route-level coverage in `tests/test_m2_routes.py`.
- **Interfaces consumed:** Tasks 2-8 services, `create_app` lifespan state, existing actor header and exception mappings.
- **Interfaces produced:** Build Slice and Prototype Task GET/PUT/confirm routes plus read-only quality routes listed above.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_routes.py`; expected failure is 404 for the new paths and absent 403/409 mapping.
- **Minimal implementation:** wire one service instance per app, pass actor and expected revisions, return safe response schemas, and map permission/conflict/validation errors using current conventions. Do not alter public project creation identity controls.
- **GREEN:** rerun the focused command; expect happy-path CRUD, cross-account 403, stale 409, validation 422, and no external-action route.
- **Regression:** `py -3.12 -m pytest -q tests/test_if_guide_m1.py tests/test_open_accounts.py tests/test_account_business_paths.py`.
- **Commit:** `feat: expose IF Guide R1.1 M2 project routes`

### Task 10 — Add Build Slice project UI

- [ ] **Files:** modify `app/static/app.js`; modify `app/static/index.html`; modify `app/static/styles.css`; add `tests/test_m2_browser_flow.py`; reuse, without modifying, `tests/run_account_browser.py` and `tests/account_flow_browser.cjs` for the repository's established local-browser process pattern.
- **Interfaces consumed:** M2 Build Slice routes, existing M1 project panel state/render functions.
- **Interfaces produced:** incremental UI for current action context, in-scope/out-of-scope fields, inputs, outputs, acceptance steps, error handling, unknowns, revision, P0 status, save, and confirm.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_browser_flow.py -k "build_slice"`; expected failure is absent M2 selectors and no persisted scope display after reload.
- **Minimal implementation:** add a bounded panel to the existing project view, preserve M1 state, display 409 without clearing server data, and keep every external action absent.
- **GREEN:** rerun the focused browser test; expect create/edit/save/reload/confirm behavior and visible quality state.
- **Regression:** `node --check app/static/app.js` and `py -3.12 -m pytest -q tests/test_if_guide_m1.py`.
- **Commit:** `feat: add Build Slice project workspace panel`

### Task 11 — Add Prototype Task UI and acceptance evidence display

- [ ] **Files:** modify `app/static/app.js`; modify `app/static/index.html`; modify `app/static/styles.css`; extend `tests/test_m2_browser_flow.py`.
- **Interfaces consumed:** Prototype Task routes, quality routes, Build Slice confirmation state.
- **Interfaces produced:** inspect/edit/save/confirm UI showing purpose, scope, inputs, outputs, implementation tasks, acceptance steps, failure/recovery notes, unknown dependencies, permission/risk notes, revision, and quality status.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_browser_flow.py -k "prototype_task"`; expected failure is absent task view and no reopen persistence.
- **Minimal implementation:** render rule-first task fields and explicit acceptance structure; make confirmed status visible; do not provide Execute, Deploy, Export, GitHub, terminal, or formal Handoff controls.
- **GREEN:** rerun the focused browser test; expect task generation after slice confirmation, edit/save/reopen, and final confirmation after acceptance completion.
- **Regression:** `py -3.12 -m pytest -q tests/test_m2_browser_flow.py tests/test_if_guide_m1.py` and `node --check app/static/app.js`.
- **Commit:** `feat: add Prototype Task review panel`

### Task 12 — Add cross-artifact inheritance and stale-version integrity checks

- [ ] **Files:** modify `app/services/if_guide_m2_quality.py`; modify `app/services/build_slice.py` and `app/services/prototype_task.py` only where binding checks are centralized; add `tests/test_m2_inheritance_integrity.py`.
- **Interfaces consumed:** exact M1 intent/action, `SnapshotService.get_current`, Build Slice/Prototype Task bindings, quality evidence IDs.
- **Interfaces produced:** structural identity checks and semantic constraint-preservation checks for intent -> slice -> task; stale invalidation and contradiction codes.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_inheritance_integrity.py`; expected failure is acceptance of wrong snapshot, old slice revision, changed purpose, or contradictory non-goal.
- **Minimal implementation:** separate structural checks (project, actor, snapshot, intent/action, slice/task revision) from semantic checks (purpose, scope, non-goals, constraints). Invalidate downstream confirmation whenever an upstream bound revision changes.
- **GREEN:** rerun the focused command; expect correct bindings to pass and each wrong/stale/contradictory case to fail closed.
- **Regression:** `py -3.12 -m pytest -q tests/test_m2_quality_metrics.py tests/test_v3_snapshot_transaction.py tests/test_v3_handoff_and_tools.py`.
- **Commit:** `feat: enforce M2 inheritance and stale binding integrity`

### Task 13 — Complete negative and safety matrix

- [ ] **Files:** add `tests/test_m2_negative_matrix.py`; modify only the smallest affected M2 service/schema files when a test exposes a confirmed defect.
- **Interfaces consumed:** all M2 services/routes and current account/project test fixtures.
- **Interfaces produced:** explicit regression coverage for missing scope, missing acceptance, false execution claims, wrong project/actor, stale revision, wrong snapshot, forbidden external action, fabricated dependency, cross-project quality evidence, and formal Handoff bypass.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_negative_matrix.py`; expected failure is absent negative-case assertions for the matrix entries.
- **Minimal implementation:** make each negative case deterministic and fail closed; keep provider/search counters at zero and ensure no mutation is created after rejection.
- **GREEN:** rerun the focused command; expect every prohibited case to return the documented error/status and no partial downstream artifact.
- **Regression:** `py -3.12 -m pytest -q tests/test_m2_negative_matrix.py tests/test_m2_routes.py tests/test_if_guide_m1.py`.
- **Commit:** `test: cover IF Guide R1.1 M2 integrity failures`

### Task 14 — Add safe inspector and monitoring/reporting read models

- [ ] **Files:** modify the existing read-only inspector module identified by `WORKSPACE_MAP.md` or add `scripts/if_guide_m2_inspect.py` only if no current inspector supports project-local M2 metadata; modify `app/services/real_idea_metrics.py` only for shared monitoring aggregation; add `tests/test_m2_inspector.py`.
- **Interfaces consumed:** M2 aggregate rows, quality evaluation revisions, existing safe metadata sanitization and monitoring summary patterns.
- **Interfaces produced:** safe M2 metadata readback containing project ID, actor-safe ownership status, snapshot/intent/action/slice/task revision IDs, status, quality status/codes, metric summaries, unknown count, and evidence hashes. No body or private input output.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_inspector.py`; expected failure is missing M2 readback and missing sensitive-content rejection.
- **Minimal implementation:** reuse current inspector/monitoring patterns, return deterministic safe metadata, and support fresh-process readback. Do not create a generation receipt or invoke any Provider/Search path.
- **GREEN:** rerun the focused command; expect safe readback, stable hashes, no full content, and correct status after revisions.
- **Regression:** `py -3.12 -m pytest -q tests/test_m2_inspector.py tests/test_real_idea_quality.py tests/test_m2_negative_matrix.py`.
- **Commit:** `feat: add safe M2 quality inspection metadata`

### Task 15 — Finish M2 verification and browser acceptance evidence

- [ ] **Files:** update only M2 tests/docs needed to record the final evidence matrix; add or refine `tests/test_m2_end_to_end.py` and `tests/test_m2_browser_flow.py`; reuse, without modifying, `tests/run_account_browser.py` and `tests/account_flow_browser.cjs` for the established local-browser process pattern. No production feature expansion is allowed in this task.
- **Interfaces consumed:** all M2 routes/services, migration registration, quality/inspector read models, existing M1 browser flow.
- **Interfaces produced:** one isolated browser path proving `confirmed Build Slice -> Prototype Task -> edit/save/reopen -> acceptance-complete confirmation`, plus final zero-call and immutability evidence.
- **RED:** `py -3.12 -m pytest -q tests/test_m2_end_to_end.py`; expected failure is absence of the complete M2 state transition and evidence assertions.
- **Minimal implementation:** complete only the missing test fixtures or narrow defects revealed by the final path; do not add new product scope or external integrations.
- **GREEN:** run `py -3.12 -m pytest -q tests/test_m2_end_to_end.py` and the browser command implemented with `tests/run_account_browser.py` plus `tests/account_flow_browser.cjs`; expect project/actor/snapshot/revision bindings, quality status, refresh persistence, and zero Provider/Search.
- **Regression:** run the final matrix below exactly once on the final M2 candidate.
- **Commit:** `test: verify IF Guide R1.1 M2 end-to-end boundary`

## Final Verification Matrix

Run after Task 15 on Python 3.12 and a fresh temporary database/runtime root where applicable:

```text
py -3.12 -m pytest -q tests/test_if_guide_m1.py tests/test_if_guide_m2_migration.py tests/test_if_guide_m2_contracts.py tests/test_build_slice_service.py tests/test_build_slice_confirmation.py tests/test_prototype_task_generation.py tests/test_prototype_task_lifecycle.py tests/test_m2_quality_bindings.py tests/test_m2_quality_metrics.py tests/test_m2_quality_audit.py tests/test_m2_routes.py tests/test_m2_browser_flow.py tests/test_m2_inheritance_integrity.py tests/test_m2_negative_matrix.py tests/test_m2_inspector.py tests/test_m2_end_to_end.py
py -3.12 -m pytest -q tests/test_open_accounts.py tests/test_account_business_paths.py tests/test_account_workspace_lifecycle.py tests/test_v3_snapshot_transaction.py tests/test_v3_handoff_and_tools.py tests/test_v2_documentation_contract.py tests/test_v2_handoff.py tests/test_stage_b_phase2_local_techdoc_handoff.py
py -3.12 -m pytest -q
py -3.12 -m compileall -q app
node --check app/static/app.js
git diff --check
```

The final evidence must also show:

- Provider dispatch delta `0`, Provider transport delta `0`, Search `0`, and no budget mutation;
- M1 behavior and M1 browser persistence unchanged;
- scope in/out, acceptance, non-goals, purpose, inputs, outputs, error handling, unknowns, and risk notes visible in the browser path;
- exact project/actor/intent/action/snapshot/slice/task bindings and 409 stale conflict behavior;
- no false executed/tested/deployed claims and no fabricated dependency marked verified;
- P0 hard gates, P1 metrics, P2 role semantics, immutable quality evidence, and quality revision hashes recoverable from a fresh process;
- no ActionSubmission/Review, Recovery, M4, public deployment, external coding action, formal Handoff export, or public API identity expansion;
- frontend syntax, backend regression, migration idempotence, and a clean worktree.

## Review and Stop Boundary

Before declaring M2 implementation ready, perform a fresh review focused on transaction/ownership/revision correctness, exact snapshot binding, P0 hard-fail behavior, quality-evidence immutability, absence of Provider/Search, UI accidental mutation, and formal Handoff non-bypass. A separate reviewer subagent is preferred by the repository workflow; if unavailable, record a complete self-review against this plan and the final verification matrix.

M2 is complete only at:

```text
Build Slice confirmed
+ Prototype Task created
+ edit/save/reopen
+ acceptance contract complete
+ P0/P1/P2 quality checks
+ browser path verified
```

No M3 behavior is included. No deployment, push, Provider call, Search call, or real Stage B mutation is part of this plan.
