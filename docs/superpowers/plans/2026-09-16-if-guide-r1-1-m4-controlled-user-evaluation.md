# IF Guide R1.1 M4 Controlled User Evaluation — Implementation Plan

> For implementation agents: use superpowers:executing-plans to implement this plan task by task. This plan is not authorization to recruit participants, call Provider/Search, mutate Stage B, or deploy.

## Goal

Add the smallest controlled-evaluation instrumentation needed to run the frozen IF Guide R1.1 M4 exploratory study after a separate approval. The implementation must record anonymized participant/session condition metadata, frozen experiment versions, human-confirmed Gold Set evidence, primary and secondary metrics, operational accounting, integrity gates, and safe per-participant reporting while preserving the M1–M3 product path.

The implementation stops before any participant is recruited or any M4 study is started. `STATIC_TEMPLATE` remains Provider/Search-free; `GENERAL_AI` has an explicit frozen call/cost contract; `INSIGHTFORGE_STATEFUL` binds to the exact deployed source/rubrics and reuses M1–M3 state.

## Architecture

The existing account-scoped project system remains the system of record for product state. M4 adds one ordered migration, `app/migrations/if_guide_m4.py`, registered by `app/db.py`, for experiment, participant, session, Gold Set, annotation, and operational metadata only. It does not create a second Project, Task, or quality ledger.

The M4 domain service in `app/services/if_guide_m4.py` owns experiment/session lifecycle and strict project/account binding. `app/services/if_guide_m4_assignment.py` owns frozen assignment rules. `app/services/if_guide_m4_quality.py` writes immutable quality evaluations through `app/services/real_idea_metrics.py` and reuses P0/P1/P2 semantics from `app/services/if_guide_m2_quality.py` and `app/services/if_guide_m3_quality.py`. `app/services/if_guide_m4_reporting.py` produces safe aggregates and `app/services/if_guide_m4_inspector.py` provides owner-scoped metadata readback.

The application routes in `app/main.py` are thin authenticated adapters. They pass actor identity from `app/accounts.py`, enforce project ownership and expected revisions in the service layer, and never accept a database path, account database, actor identity, workspace, or arbitrary condition configuration from the client. The existing frontend shell in `app/static/index.html`, `app/static/app.js`, and `app/static/styles.css` is incremented only after the service contracts are complete.

Quality evidence is append-only and safe: IDs, hashes, status, revision, rubric/version, evaluator role, numerator/denominator, and evidence references are allowed; raw transcripts, private files, credentials, full artifact bodies, and unnecessary PII are rejected. Existing `real_idea_quality_evaluations` remains the quality ledger. New M4 participant/session operational records are not a parallel quality ledger.

## Tech Stack

- Python 3.12 runtime and the current repository test harness.
- Existing SQLite schema/migration registration in `app/db.py` and `app/migrations/if_guide_m1.py` through `if_guide_m3.py`.
- Existing FastAPI routes and account ownership helpers in `app/main.py` and `app/accounts.py`.
- Existing M1–M3 services: `project_intent.py`, `build_slice.py`, `prototype_task.py`, `action_submission.py`, `action_review.py`, `recovery.py`, `m3_decision.py`.
- Existing immutable quality service and safe evidence contract in `app/services/real_idea_metrics.py`.
- Existing browser runners: `tests/m2_flow_browser.cjs`, `tests/run_m2_browser.py`, `tests/m3_flow_browser.cjs`, and `tests/run_m3_browser.py`.
- No new Provider/Search integration. Any General AI condition adapter is metadata/run-contract only in this slice and is capped by persisted policy before an execution task is authorized.

## Spec

Implement exactly the contracts in `docs/superpowers/specs/2026-09-16-if-guide-r1-1-m4-controlled-user-evaluation-design.md`. Preserve M1–M3 semantics and the existing Formal Handoff boundary in `app/services/handoff.py` and its routes. M4 does not implement ActionSubmission, ActionReview, Recovery, Decision, M4 experiments, or external execution a second time.

## Global Constraints

- Work in a clean branch and use TDD. Every task below has one focused RED command, a minimal GREEN change, an affected regression, and a commit.
- Do not create a second Project system, Task system, authentication/storage model, or quality ledger.
- Do not read or store unnecessary PII. Safe evidence references and hashes are mandatory for exports.
- Provider/Search calls are zero during schema/service/UI verification. A future General AI run must be separately authorized, versioned, capped, and accounted for; it is not executed by this plan.
- Do not access real Stage B data, the Real Idea Batch extension, Railway, public deployment, or production credentials.
- Hard integrity failures are never softened into diagnostic metrics: cross-project leakage, false `AUTHORIZED_RUN`, unauthorized action, duplicate paid dispatch, wrong version binding, and severe unsupported verified facts fail the session/experiment.
- A P0/P1 result never claims P2 human review. LLM assistance can propose candidates only; participant and independent reviewer evidence remains authoritative.
- No task may use `TBD`, `TODO`, an unspecified file path, or an unbound “add validation” instruction.

## Task 1: Add the ordered M4 storage migration and safe schema contract

**Files**

- Modify `app/db.py` to register `app/migrations/if_guide_m4.py` after `if_guide_m3`.
- Create `app/migrations/if_guide_m4.py` using the ordered/idempotent migration shape of `app/migrations/if_guide_m3.py`.
- Create `tests/test_if_guide_m4_migration.py`.

**Interfaces consumed**

- Existing account/project identifiers and ownership conventions from `app/accounts.py` and M1–M3 migrations.
- Existing quality-evaluation table and binding fields from `app/services/real_idea_metrics.py`.

**Interfaces produced**

- `m4_experiments`: immutable experiment version, source/deployment, condition policy, metric/rubric hashes, assignment rule, assistance policy, and status.
- `m4_participants`: anonymous participant ID, purpose, coarse familiarity/experience/category, and outcome status; no contact/PII fields.
- `m4_sessions`: experiment/participant/condition/project binding, assignment, version split, lifecycle status, timing/edit/support/accounting metadata, and revision.
- `m4_requirement_gold_items`: participant-confirmed Gold Set items with importance, source, confirmer, and revision.
- `m4_quality_annotations`: human/LLM-assist annotation references and adjudication metadata; quality evaluations still use `real_idea_quality_evaluations`.

**RED test**

Write migration assertions for table/column names, unique constraints on experiment version, participant ID within experiment, session uniqueness, and absence of raw transcript/full artifact body columns.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_migration.py`

Expected failure: the M4 migration is not registered and the required tables/constraints do not exist.

**Minimal GREEN**

Implement only the ordered migration and registration. Use foreign keys/indexes needed for account/project/session binding, append-only revision fields, and idempotent reruns. Do not add routes or business behavior.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_migration.py`

**Relevant regression**

`python -m pytest -q tests/test_if_guide_m3_migration.py tests/test_if_guide_m2_migration.py`

**Commit**

`feat: add IF Guide R1.1 M4 evaluation storage`

## Task 2: Define experiment freeze, participant, and session lifecycle service

**Files**

- Create `app/services/if_guide_m4.py`.
- Create `tests/test_if_guide_m4_experiment.py`.

**Interfaces consumed**

- `app/accounts.py` actor identity and account scope.
- Existing project lookup/ownership patterns in `app/services/project_intent.py` and `app/services/build_slice.py`.
- M4 migration tables from Task 1.

**Interfaces produced**

- `create_experiment`, `freeze_experiment`, `create_participant`, `create_session`, `transition_session`, and safe `get_session` equivalents.
- Frozen experiment record containing spec version, source commit, deployment ID, condition definitions, prompt/model/call policy metadata, M1–M3 rubric versions, metric formulas, thresholds, assignment rule, and operator-assistance policy.
- Lifecycle states `CREATED`, `ASSIGNED`, `READY`, `IN_PROGRESS`, `COMPLETED`, `WITHDRAWN`, `OPERATIONAL_INCOMPLETE`, `QUALITY_INCOMPLETE`, and `FINALIZED` with explicit transition guards.

**RED test**

Test that an unfrozen experiment cannot create a session, a frozen experiment cannot change condition/policy metadata, invalid transitions fail, account-owned project binding is enforced, and a second identical session is idempotently rejected.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_experiment.py`

Expected failure: no M4 service or lifecycle/freeze guards exist.

**Minimal GREEN**

Implement transactionally validated service methods with actor/account checks, expected revisions, immutable freeze metadata, and safe state transitions. Do not expose a public route yet.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_experiment.py`

**Relevant regression**

`python -m pytest -q tests/test_if_guide_m1.py tests/test_if_guide_m2_contracts.py tests/test_m3_negative_matrix.py`

**Commit**

`feat: add M4 experiment and session lifecycle`

## Task 3: Implement balanced condition assignment without post-hoc reassignment

**Files**

- Create `app/services/if_guide_m4_assignment.py`.
- Create `tests/test_if_guide_m4_assignment.py`.

**Interfaces consumed**

- Frozen experiment/session service from `app/services/if_guide_m4.py`.
- Purpose values and condition contracts from the M4 spec.

**Interfaces produced**

- Deterministic, auditable assignment function using experiment assignment seed/rule and purpose stratum.
- Assignment record with condition, purpose, rule version, deviation reason, and assignment timestamp.

**RED test**

Test all three purposes are accepted, only the three frozen conditions are assignable, balance is observable, reassignment is rejected after assignment, withdrawals remain recorded, and a participant cannot receive a second active session for the same experiment without an explicit protocol rule.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_assignment.py`

Expected failure: assignment service and frozen condition checks do not exist.

**Minimal GREEN**

Implement only the balanced-by-purpose assignment rule and auditable deviation/withdrawal handling. Do not optimize assignment based on outcomes.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_assignment.py`

**Relevant regression**

`python -m pytest -q tests/test_if_guide_m4_experiment.py tests/test_if_guide_m3_account_isolation.py`

**Commit**

`feat: add frozen M4 condition assignment`

## Task 4: Add condition contracts and Provider/cost accounting boundaries

**Files**

- Modify `app/services/if_guide_m4.py` for condition policy validation.
- Create `app/services/if_guide_m4_conditions.py`.
- Create `tests/test_if_guide_m4_conditions.py`.
- Create `tests/test_if_guide_m4_operational_accounting.py`.

**Interfaces consumed**

- Existing Provider accounting interfaces in `app/services/provider_dispatch_ledger.py`.
- Existing Provider runtime boundaries in `app/llm.py`, `app/services/provider_adapters.py`, `app/services/ai_runtime.py`, and `app/services/quick_start.py`.

**Interfaces produced**

- Frozen `STATIC_TEMPLATE` contract with calls/cost 0.
- Metadata-only `GENERAL_AI` contract requiring prompt/model/provider, schema, retry, timeout, max calls, and cost fields before a future run.
- `INSIGHTFORGE_STATEFUL` contract binding source/deployment/features/rubrics/migration and Provider/Search policy.
- Per-session accounting fields for calls, cost, retries, timeouts, severe errors, support minutes, edit count, and recovery attempts.

**RED test**

Test static condition rejects Provider calls, General AI policy rejects missing cap/retry/timeout/cost metadata and any observed call over the cap, IF condition rejects source/rubric mismatch, and no-Provider sessions record zero rather than missing.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_conditions.py tests/test_if_guide_m4_operational_accounting.py`

Expected failure: M4 condition policy and operational accounting contracts do not exist.

**Minimal GREEN**

Implement policy validation and ledger updates around existing accounting; do not add an LLM client, retry path, Search path, or external executor.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_conditions.py tests/test_if_guide_m4_operational_accounting.py`

**Relevant regression**

`python -m pytest -q tests/test_m3_provider_search_tripwires.py tests/test_real_idea_quality_provider_search_tripwires.py`

**Commit**

`feat: enforce M4 condition and cost contracts`

## Task 5: Add participant-confirmed Gold Set and human/LLM annotation boundary

**Files**

- Create `app/services/if_guide_m4_gold_set.py`.
- Create `tests/test_if_guide_m4_gold_set.py`.
- Create `tests/test_if_guide_m4_annotation_boundaries.py`.

**Interfaces consumed**

- Participant/session ownership from `app/services/if_guide_m4.py`.
- Existing safe-evidence validation and immutable evaluation binding from `app/services/real_idea_metrics.py`.

**Interfaces produced**

- Participant-confirmed Gold Set create/revise/finalize operations for purpose, critical/secondary requirements, constraints, and explicit non-goals.
- Annotation records with requirement/claim/checkability/actionability/contradiction targets, evaluator role, source identity, evidence reference, disagreement, and adjudication state.

**RED test**

Test that Gold Set finalization requires participant confirmation, revisions are append-only, LLM role cannot finalize Ground Truth, independent reviewer annotations preserve disagreement, unsafe raw bodies/transcripts/PII are rejected, and Gold Set binds exact participant/project/session revision.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_gold_set.py tests/test_if_guide_m4_annotation_boundaries.py`

Expected failure: Gold Set and annotation boundary interfaces do not exist.

**Minimal GREEN**

Implement role-aware, revisioned Gold Set and annotation services using safe metadata/evidence references. Reuse the existing quality ledger for quality evaluation rows; do not create a parallel metric ledger.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_gold_set.py tests/test_if_guide_m4_annotation_boundaries.py`

**Relevant regression**

`python -m pytest -q tests/test_real_idea_quality_ledger.py tests/test_real_idea_quality_safety.py`

**Commit**

`feat: add M4 participant-confirmed gold sets`

## Task 6: Add primary and secondary quality metric evaluation through the existing ledger

**Files**

- Create `app/services/if_guide_m4_quality.py`.
- Create `tests/test_if_guide_m4_metrics.py`.
- Create `tests/test_if_guide_m4_quality_hard_gates.py`.

**Interfaces consumed**

- `QualityEvaluationService` and `ArtifactQualityEvaluation` in `app/services/real_idea_metrics.py`.
- P0/P1/P2 semantics in `app/services/if_guide_m2_quality.py` and `app/services/if_guide_m3_quality.py`.
- Gold Set and annotations from Task 5.

**Interfaces produced**

- Per-session metrics with exact numerator/denominator and missing/incomplete handling: First Valid Action Rate, First Usable Flow Completion Rate, Independent Acceptance Rate, Evidence-backed Decision Rate, and Recovery Rate.
- Reused secondary formulas: Critical Requirement Recall, Overall Requirement Recall, Alignment Precision, Checkability Coverage, Acceptance Coverage, Acceptance Testability, Unsupported Claim Rate, Actionability, and Result→Decision Traceability.
- P0 integrity status, P1 diagnostic metrics, and P2 reviewer status where P2 is `NOT_REVIEWED` until human review exists.

**RED test**

Use isolated fixtures to assert conditional denominators, `NOT_APPLICABLE` for no qualifying blocker, missing evidence not becoming pass, zero-provider accounting as zero, unsupported verified claims failing P0, leakage/version-binding failures failing P0, and LLM-only annotations never becoming Ground Truth.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_metrics.py tests/test_if_guide_m4_quality_hard_gates.py`

Expected failure: M4 primary metrics and quality gate evaluator do not exist.

**Minimal GREEN**

Implement formula evaluation and immutable ledger writes by calling existing quality service APIs. Separate structural identity checks from semantic metrics and preserve participant/reviewer/LLM roles.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_metrics.py tests/test_if_guide_m4_quality_hard_gates.py`

**Relevant regression**

`python -m pytest -q tests/test_if_guide_m2_quality.py tests/test_if_guide_m3_quality.py tests/test_real_idea_quality_ledger.py`

**Commit**

`feat: add M4 quality metrics and integrity gates`

## Task 7: Add version-split and outcome finalization rules

**Files**

- Modify `app/services/if_guide_m4.py` for version comparison and finalization.
- Create `tests/test_if_guide_m4_version_split.py`.
- Create `tests/test_if_guide_m4_outcomes.py`.

**Interfaces consumed**

- Frozen experiment/session metadata from Tasks 2 and 4.
- M4 quality gate status from Task 6.

**Interfaces produced**

- Exact comparison of source, deployment, condition, prompt/model, rubric, schema, formula, threshold, assignment, and assistance versions.
- `experiment_version_split` marker and non-pooling rule.
- Outcome taxonomy: `WITHDRAWN`, `OPERATIONAL_INCOMPLETE`, `QUALITY_INCOMPLETE`, `COMPLETED`, and `INTEGRITY_FAIL`.

**RED test**

Test that any frozen behavior/version change marks a split, split sessions cannot be silently aggregated, hard integrity failure finalizes as `INTEGRITY_FAIL`, withdrawal is preserved, and missing quality evidence becomes `QUALITY_INCOMPLETE` rather than completed.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_version_split.py tests/test_if_guide_m4_outcomes.py`

Expected failure: version-split comparison and outcome finalization are absent.

**Minimal GREEN**

Implement append-only finalization and explicit split metadata. Do not add post-hoc participant replacement or outcome optimization.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_version_split.py tests/test_if_guide_m4_outcomes.py`

**Relevant regression**

`python -m pytest -q tests/test_if_guide_m3_inspector.py tests/test_m3_negative_matrix.py`

**Commit**

`feat: enforce M4 version splits and outcomes`

## Task 8: Add safe reporting and inspector readback

**Files**

- Create `app/services/if_guide_m4_reporting.py`.
- Create `app/services/if_guide_m4_inspector.py`.
- Create `tests/test_if_guide_m4_reporting.py`.
- Create `tests/test_if_guide_m4_inspector.py`.

**Interfaces consumed**

- M4 lifecycle, assignments, outcomes, accounting, Gold Set, and quality ledger services.
- Safe owner-scoped readback patterns in `app/services/if_guide_m2_inspector.py` and `app/services/if_guide_m3_inspector.py`.

**Interfaces produced**

- Per-participant report rows, followed by descriptive aggregates by condition and purpose.
- Report fields for completion/outcome, primary/secondary metrics, missingness, failures, edits, support time, Provider calls/cost, qualitative safe references, and version splits.
- Inspector output containing safe IDs/status/hashes/timestamps/revisions and no raw transcripts, private artifact bodies, or credentials.

**RED test**

Test per-participant-first ordering, descriptive-only aggregates, split separation, no-provider zero accounting, owner isolation, and rejection of unsafe report fields.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_reporting.py tests/test_if_guide_m4_inspector.py`

Expected failure: reporting and M4 inspector interfaces do not exist.

**Minimal GREEN**

Implement deterministic safe serialization and aggregation over existing records. Do not add an analytics warehouse or statistical-significance calculator.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_reporting.py tests/test_if_guide_m4_inspector.py`

**Relevant regression**

`python -m pytest -q tests/test_if_guide_m2_inspector.py tests/test_if_guide_m3_inspector.py tests/test_real_idea_quality_inspector.py`

**Commit**

`feat: add safe M4 evaluation reporting`

## Task 9: Expose authenticated M4 operator routes without public product expansion

**Files**

- Modify `app/schemas.py` with M4 request/response schemas that contain safe metadata only.
- Modify `app/main.py` with authenticated internal evaluation routes using existing account binding and expected-revision behavior.
- Create `tests/test_if_guide_m4_routes.py`.

**Interfaces consumed**

- M4 services from Tasks 2–8.
- Existing authentication/account helpers in `app/accounts.py` and route error handling in `app/errors.py`/`app/main.py`.

**Interfaces produced**

- Internal, explicitly scoped experiment/session/Gold Set/quality/report read/write routes as determined by the service contracts.
- No route accepts arbitrary database paths, actor IDs, public condition overrides, or direct quality state.

**RED test**

Test unauthenticated denial, cross-account denial, stale revision `409`, route ownership, safe response fields, idempotency where required, and absence of a public participant-recruitment or unrestricted experiment route.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_routes.py`

Expected failure: M4 schemas/routes are not present.

**Minimal GREEN**

Add thin adapters only. Keep all transaction, ownership, revision, freeze, and quality checks in services. Preserve all existing M1–M3 and Formal Handoff routes.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_routes.py`

**Relevant regression**

`python -m pytest -q tests/test_if_guide_m1_routes.py tests/test_if_guide_m2_routes.py tests/test_m3_routes.py`

**Commit**

`feat: expose scoped M4 evaluation routes`

## Task 10: Add minimal frontend operator/reviewer surface

**Files**

- Modify `app/static/index.html` in the existing project-page shell.
- Modify `app/static/app.js` using the existing API/request and revision-conflict patterns.
- Modify `app/static/styles.css` only for the M4 evaluation panels.
- Create `tests/test_if_guide_m4_frontend_contract.py`.

**Interfaces consumed**

- Authenticated M4 routes from Task 9.
- Existing M1–M3 project page controls and local draft/conflict behavior in `app/static/app.js`.

**Interfaces produced**

- Operator/reviewer view for frozen experiment/session metadata, assignment, lifecycle, safe metric evidence, version splits, and outcome status.
- Clear display of user-reported versus artifact-checked versus authorized-run evidence, with no UI claim that M4 is market validation.

**RED test**

Test that the existing project page remains the shell, M4 labels distinguish conditions and evidence levels, P2 is not displayed as reviewed without status, unsafe body fields are not rendered, and stale save preserves the local draft.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_frontend_contract.py`

Expected failure: the M4 controls and safe rendering contract are absent.

**Minimal GREEN**

Add only the evaluation panels and existing request/reopen patterns. Do not add participant recruitment, public rollout, automatic execution, or a second application shell.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_frontend_contract.py`

**Relevant regression**

`python -m pytest -q tests/test_m2_frontend_contract.py tests/test_m3_frontend_contract.py`

**Commit**

`feat: add M4 evaluation controls to project page`

## Task 11: Add browser/operator rehearsal and negative integrity matrix

**Files**

- Create `tests/m4_flow_browser.cjs`.
- Create `tests/run_m4_browser.py`.
- Create `tests/test_if_guide_m4_browser_contract.py`.
- Create `tests/test_if_guide_m4_negative_matrix.py`.
- Create `tests/test_if_guide_m4_provider_search_tripwires.py`.

**Interfaces consumed**

- Existing browser harness conventions from `tests/m3_flow_browser.cjs` and `tests/run_m3_browser.py`.
- M4 routes, safe inspector, and state/revision services.

**Interfaces produced**

- A browser contract for login, opening an M2/M3-compatible project, reading frozen assignment/session state, reopening safe evidence/report metadata, and switching accounts.
- Negative coverage for cross-account/project leakage, false `AUTHORIZED_RUN`, wrong condition/version, duplicate session, unauthorized external action, split pooling, unsafe evidence, and hard-gate status.

**RED test**

Test the browser harness and negative matrix before the M4 surface is complete; assert that forbidden Provider/Search markers remain absent from the M4 path.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_browser_contract.py tests/test_if_guide_m4_negative_matrix.py tests/test_if_guide_m4_provider_search_tripwires.py`

Expected failure: M4 browser contract, negative cases, and tripwire assertions are not implemented.

**Minimal GREEN**

Implement only the rehearsal and isolated negative fixtures. The browser test must not recruit users, create real Stage B records, invoke external tools, or turn a user claim into authorized execution.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_browser_contract.py tests/test_if_guide_m4_negative_matrix.py tests/test_if_guide_m4_provider_search_tripwires.py`

**Relevant regression**

`python -m pytest -q tests/test_m2_browser_flow.py tests/test_m3_browser_contract.py tests/test_m3_negative_matrix.py`

**Commit**

`test: add M4 browser and integrity rehearsal`

## Task 12: Final verification, release-gate report, and Stage B preparation artifacts

**Files**

- Create `tests/test_if_guide_m4_release_gate.py`.
- Create `tests/test_if_guide_m4_compatibility.py`.
- Modify only the M4 inspector/reporting modules if final safe-field assertions identify an inconsistency.

**Interfaces consumed**

- All M4 services/routes/UI and current M1–M3 compatibility surfaces.
- Formal Handoff implementation in `app/services/handoff.py` and existing Solutions/Documents navigation.

**Interfaces produced**

- A deterministic release-gate report that separates hard integrity gates, P0/P1 diagnostics, P2 human-review status, and readiness for a separately authorized Stage B deployment.
- A deployment-preparation checklist binding source, migration identity, rubric versions, condition policies, Provider/Search policy, and safe data-root expectations without performing deployment.

**RED test**

Test that the release gate fails on leakage, false authorized execution, unauthorized action, duplicate paid dispatch, wrong version binding, severe unsupported verified claim, incomplete freeze, or missing human confirmation; test that passing P0/P1 does not claim P2 review or statistical superiority.

**RED command and expected RED**

`python -m pytest -q tests/test_if_guide_m4_release_gate.py tests/test_if_guide_m4_compatibility.py`

Expected failure: final M4 release-gate and compatibility contract is absent.

**Minimal GREEN**

Implement report assertions and isolated compatibility fixtures only. Do not run a full M4 study, call Provider/Search, deploy Railway, or mutate Stage B.

**GREEN command**

`python -m pytest -q tests/test_if_guide_m4_release_gate.py tests/test_if_guide_m4_compatibility.py`

**Relevant regression**

At final candidate, run once:

`python -m pytest -q tests/test_if_guide_m4_migration.py tests/test_if_guide_m4_experiment.py tests/test_if_guide_m4_assignment.py tests/test_if_guide_m4_conditions.py tests/test_if_guide_m4_operational_accounting.py tests/test_if_guide_m4_gold_set.py tests/test_if_guide_m4_annotation_boundaries.py tests/test_if_guide_m4_metrics.py tests/test_if_guide_m4_quality_hard_gates.py tests/test_if_guide_m4_version_split.py tests/test_if_guide_m4_outcomes.py tests/test_if_guide_m4_reporting.py tests/test_if_guide_m4_inspector.py tests/test_if_guide_m4_routes.py tests/test_if_guide_m4_frontend_contract.py tests/test_if_guide_m4_browser_contract.py tests/test_if_guide_m4_negative_matrix.py tests/test_if_guide_m4_provider_search_tripwires.py tests/test_if_guide_m4_release_gate.py tests/test_if_guide_m4_compatibility.py`

Then run the affected M1/M2/M3 compatibility and browser suites, Node syntax checks for `tests/m4_flow_browser.cjs`, changed-scope `compileall`, and `git diff --check`. Run the full backend only if the implementation changes shared core infrastructure broadly; if required, run it once on the final candidate and compare against the established baseline.

**Commit**

`test: verify IF Guide R1.1 M4 release gate`

## Final verification and stop boundary

Before any future implementation is considered ready, perform a fresh whole-diff review for M4-only scope, reuse of current project/task/quality/auth storage, safe evidence, exact condition/version binding, P0/P1/P2 separation, no hidden Provider/Search, no public rollout, no second quality ledger, and preserved Formal Handoff. Run the final targeted suites and browser rehearsal from Task 12, inspect the release-gate report, and leave the worktree clean.

The implementation is complete only when all three condition contracts are reproducible, assignment/version split/outcome rules are tested, Gold Set requires participant confirmation, LLM-as-Judge is not sole truth, metrics and accounting are recoverable, integrity negatives pass, browser/reopen/isolation compatibility passes, and no Provider/Search or real Stage B mutation occurred.

The next legal action after this plan is a separately authorized review of the M4 spec/plan, then a separately authorized implementation/deployment preparation. This plan does not start M4, recruit participants, create an experiment session in Stage B, or advance to a later product milestone.
