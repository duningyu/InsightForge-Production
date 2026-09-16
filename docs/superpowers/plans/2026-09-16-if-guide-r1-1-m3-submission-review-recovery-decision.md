# IF Guide R1.1 M3: Submission, Review, Recovery, and Decision

> Implementation plan for the repository at the M2 frozen commit. This plan stops before M4 and contains no deployment or real Stage B operation.

## Goal

Extend the existing M1/M2 project page so a user can submit the result of the current Prototype Task as DONE or BLOCKED, receive an honest review with PASS, FAIL, UNKNOWN, or NOT_APPLICABLE, receive one minimal recovery action when the result needs more work, and confirm a separate project decision of CONTINUE, NARROW, CHANGE, STOP, or FINISH.

The implementation must preserve the existing M1 Purpose and First Action flow, the M2 Build Slice and Prototype Task flow, the existing ArtifactQualityEvaluation ledger, the Formal Handoff boundary, account isolation, revision checks, and history/reopen behavior. M3 remains rule-first and provider-free:

- Provider transports: 0
- Search requests: 0
- external execution: 0 by default
- M4 experiment work: not included

The M3 result state is not a claim that implementation happened, was tested, was deployed, or was externally verified. User statements, attached evidence, deterministic artifact checks, and any future authorized run remain separate evidence classes.

## Authority and current repository mapping

The synced authority is stored under docs/mainline/IF_GUIDE_R1/. The directly relevant authority files are:

- docs/mainline/IF_GUIDE_R1/MAINLINE_RULES.md
- docs/mainline/IF_GUIDE_R1/TECHNICAL_ROUTE.md
- docs/mainline/IF_GUIDE_R1/WORKSPACE_RULES_APPEND.md
- docs/mainline/IF_GUIDE_R1/CODEX_START.md
- docs/mainline/IF_GUIDE_R1/SOURCES.md
- docs/mainline/IF_GUIDE_R1/FULL_MAINLINE_AND_EVALUATION_R1_1.md
- docs/mainline/IF_GUIDE_R1/AI_OUTPUT_QUALITY_EVALUATION_R1_1.md
- docs/mainline/IF_GUIDE_R1/M0_M4_EVALUATION_MAP_R1_1.md
- docs/mainline/IF_GUIDE_R1/CODE_ARCHITECTURE_R1_1.md
- docs/mainline/IF_GUIDE_R1/CODEX_START_R1_1.md
- docs/mainline/IF_GUIDE_R1/WORKSPACE_MAP.md

The current M1/M2 implementation is:

| Capability | Existing repository location | M3 reuse contract |
| --- | --- | --- |
| account routing and actor binding | app/accounts.py, app/main.py | use the account selected by the authenticated workspace session; do not trust a client-selected database, workspace, or account |
| project intent | app/services/project_intent.py and app/migrations/if_guide_m1.py | use current intent owner and revision checks |
| ActionTask/GuidedAction equivalent | app/services/project_intent.py, first_action_cards in app/migrations/if_guide_m1.py | extend first_action_cards for execution state and RECOVERY kind; do not create a second task table |
| Build Slice | app/services/build_slice.py and app/migrations/if_guide_m2.py | require the current confirmed slice and its revision |
| Prototype Task | app/services/prototype_task.py and app/migrations/if_guide_m2.py | submit only the current confirmed task and bind task revision and snapshot |
| M2 quality | app/services/if_guide_m2_quality.py | preserve the M2 P0/P1 checks and call the shared quality ledger for M3 evidence |
| quality ledger | app/services/real_idea_metrics.py and real_idea_quality_evaluations | append immutable M3 evaluations through ArtifactQualityEvaluation and QualityEvaluationService; no parallel ledger |
| safe readback | app/services/if_guide_m2_inspector.py | extend safe metadata inspection without returning document or user-content bodies |
| revision conflicts | app/services/project_intent.py, app/services/build_slice.py, app/services/prototype_task.py, app/errors.py, app/main.py | use expected_revision and return the existing 409 conflict shape |
| frontend shell | app/static/index.html, app/static/app.js, app/static/styles.css | add M3 sections to the existing project page |
| migration registration | app/db.py and app/migrations/if_guide_m1.py, app/migrations/if_guide_m2.py | add one ordered if_guide_m3 migration and register it in Database initialization |
| formal Handoff | app/services/handoff.py and existing Handoff routes in app/main.py | leave HandoffService, _build_v3_zip, readiness, acknowledgement, and export semantics unchanged |

The legacy app/services/decisions.py DecisionService remains the solution-selection decision service. M3 result decisions must not be stored through its solution-selection contract. M3 uses a separate decision_records table and M3 decision service while sharing the existing account, project, and revision conventions.

## M3 domain and state contract

### Existing ActionTask extension

The migration adds execution-specific fields to first_action_cards without changing the existing M1 planning status contract:

- kind: FIRST_ACTION or RECOVERY
- parent_task_id: nullable first_action_cards.task_id for a recovery action
- source_submission_id: nullable reference validated by service logic
- source_review_id: nullable reference validated by service logic
- execution_state: DRAFT, READY, IN_PROGRESS, SUBMITTED, CLOSED, NEEDS_REVISION, or PAUSED
- execution_revision: positive integer for execution-state changes

Existing status, confirmed, card_revision, intent_revision, and project ownership fields remain intact. Existing rows are migrated deterministically to execution_state DRAFT or READY from their current M1 status and confirmation. A recovery action is an ordinary project-owned ActionTask row with kind RECOVERY, one parent task, one source review, one minimum next action, its own revision history, and no hidden reset of the original task.

The M3 transition rules are:

- DRAFT -> READY only after the task's planning content is complete and confirmed by the current M2 contract.
- READY -> IN_PROGRESS when the user begins the current action.
- READY or IN_PROGRESS -> SUBMITTED when a valid DONE or BLOCKED submission is persisted.
- SUBMITTED -> CLOSED only when the review result and required evidence satisfy the deterministic review contract.
- SUBMITTED -> NEEDS_REVISION for FAIL or a critical UNKNOWN that requires a revised task or recovery.
- SUBMITTED -> PAUSED for a BLOCKED result while a recovery action is available.
- A recovery task starts as DRAFT and can follow the normal task revision/confirmation path.

Decision is never encoded by changing execution_state. CLOSED is not FINISH, PASS is not FINISH, PASS is not market validation, STOP is not failure, and FINISH is not deployed.

### ActionSubmission

The new action_submissions table stores:

- submission_id
- project_id
- task_id
- task_revision
- submission_kind: DONE or BLOCKED
- description
- attachment_refs_json
- check_results_json
- execution_claim
- source_identity: USER_INPUT, MODEL_HYPOTHESIS, REAL_OBSERVATION, SIMULATION, or IMPLEMENTATION_EVIDENCE
- revision
- submitted_by
- created_at

The service requires the task to belong to the project and actor, binds the exact task revision, validates JSON shapes and source identity, and rejects stale or duplicate writes according to the current expected_revision convention. A submission is a user report or supplied evidence package; it is not automatic verification and cannot declare AUTHORIZED_RUN merely because a user wrote that execution occurred.

### ActionReview

The new action_reviews table stores:

- review_id
- project_id
- submission_id
- submission_revision
- task_revision
- check_items_json
- overall_status: PASS, FAIL, UNKNOWN, or NOT_APPLICABLE
- known_unknowns_json
- evidence_level: USER_REPORTED, ARTIFACT_CHECKED, or AUTHORIZED_RUN
- recommendation
- reviewer_role
- revision
- created_at
- evidence_hash

The service checks exact project, submission, task, and revision identity. AUTHORIZED_RUN is rejected unless a real authorized-run evidence record exists; the M3 default does not execute tools to upgrade evidence. NOT_APPLICABLE requires an explicit reason and a review item for which the status is applicable. P2 human review remains a hook/status and is not implied by P0 or P1 completion.

### Recovery

Recovery reuses first_action_cards with kind RECOVERY. RecoveryService creates exactly one minimal next action tied to the originating review and submission, binds it to the current project and owner, records the source references, and preserves the original ActionTask and submission. It must not reset the project, silently replace the original task, regenerate all artifacts, or run a hidden model loop.

### Decision

The new decision_records table stores:

- decision_id
- project_id
- source_submission_id
- source_review_id
- decision: CONTINUE, NARROW, CHANGE, STOP, or FINISH
- rationale
- confirmed_by
- revision
- created_at

M3DecisionService requires a valid current review, an explicit user confirmation action, project ownership, and expected revision. It records the recommendation and remaining unknowns separately from the user's confirmed decision. A decision without a source review or user confirmation is rejected.

## Quality contract

M3 quality uses app/services/real_idea_metrics.py and its append-only real_idea_quality_evaluations ledger. app/services/if_guide_m3_quality.py provides the M3 rubric and produces immutable evidence records bound to project_id, artifact type/id/revision, source submission/review, and the relevant task revision.

P0 deterministic gates:

- project and actor ownership
- current task exists and is M2-ready
- exact task revision and project binding
- valid submission kind and source identity
- valid review status and evidence-level structure
- PASS has required check evidence
- AUTHORIZED_RUN is never asserted without authorized-run evidence
- review and decision references are exact
- user confirmation is present before decision persistence
- no forbidden external action
- no false executed, tested, deployed, or verified claim

P1 metrics:

- Evidence Sufficiency: critical PASS items with evidence matching the declared level divided by critical PASS items
- Review Accuracy: fixture/adjudication agreement for supported PASS, real FAIL, real UNKNOWN, and justified NOT_APPLICABLE
- Result-to-Decision Traceability: decisions with exact valid submission and review evidence divided by all decisions
- Unsupported Conclusion Rate: unsupported conclusions divided by review/decision conclusions; disclosed hypotheses and unknowns are not factual errors
- Recovery Specificity: recovery actions that contain one concrete, minimal, blocker-linked next action divided by recovery actions
- UNKNOWN preservation/status distribution for review outputs

P2 exposes reviewer role, review status, adjudication hook, and final fidelity fields through the existing quality evaluation mechanism. P0/P1 PASS never changes P2 to reviewed without a real reviewer record.

## Implementation sequence

### Task 1: Add the M3 migration and execution-state model

Files to create or modify:

- app/migrations/if_guide_m3.py
- app/db.py
- tests/test_if_guide_m3_migration.py

Interfaces consumed:

- Database initialization and ordered migration registration in app/db.py
- first_action_cards schema from app/migrations/if_guide_m1.py
- build_slices and prototype_tasks foreign-key conventions from app/migrations/if_guide_m2.py
- sqlite row and timestamp conventions in app/db.py

Interfaces produced:

- action_submissions, action_reviews, decision_records tables
- M3 columns on first_action_cards for kind, recovery linkage, execution_state, and execution_revision
- idempotent migration registration

RED test:

1. Add tests for fresh schema creation, upgrade of a database containing M1/M2 rows, exact status checks, foreign-key behavior, append-only review/decision rows, and migration idempotency.
2. Run:

   python -m pytest -q tests/test_if_guide_m3_migration.py

Expected RED:

- the M3 migration module and registration are absent;
- action_submissions, action_reviews, and decision_records cannot be opened;
- existing first_action_cards rows have no execution-state columns.

Minimal GREEN:

- implement the ordered if_guide_m3 migration following the savepoint/transaction style of if_guide_m2;
- add only the fields and tables in the M3 domain contract;
- preserve existing M1/M2 rows and map their current planning state deterministically;
- register the migration once in app/db.py;
- add uniqueness and check constraints for fixed enum values and exact project/task bindings where supported by the current SQLite style.

GREEN command:

   python -m pytest -q tests/test_if_guide_m3_migration.py

Affected regression:

   python -m pytest -q tests/test_if_guide_m1.py tests/test_if_guide_m2_migration.py tests/test_m2_routes.py

Commit:

   feat: add IF Guide M3 persistence schema

### Task 2: Implement ActionSubmissionService with ownership and revision binding

Files to create or modify:

- app/services/action_submission.py
- app/schemas.py
- tests/test_action_submission_service.py

Interfaces consumed:

- Database and row access conventions from app/db.py
- project ownership and current actor conventions from app/services/project_intent.py, app/services/build_slice.py, and app/accounts.py
- current PrototypeTaskService.get_current and evaluate_p0 in app/services/prototype_task.py
- ConflictError from app/errors.py

Interfaces produced:

- ActionSubmissionService.submit
- ActionSubmissionService.get
- ActionSubmissionService.list_for_task
- Pydantic request/response models for DONE and BLOCKED submissions

RED test:

Run:

   python -m pytest -q tests/test_action_submission_service.py

Expected RED:

- ActionSubmissionService and its models do not exist;
- valid DONE/BLOCKED persistence, stale revision rejection, cross-account denial, source identity preservation, and duplicate idempotency cannot be exercised.

Minimal GREEN:

- require a current confirmed Prototype Task, exact task revision, project owner, trusted actor, and valid submission payload;
- persist only the submission fields listed in the contract;
- keep attachment references and check results as safe structured metadata;
- preserve USER_INPUT, MODEL_HYPOTHESIS, REAL_OBSERVATION, SIMULATION, and IMPLEMENTATION_EVIDENCE without upgrade;
- increment execution_revision and transition the task to SUBMITTED in one transaction;
- return the existing conflict error shape for stale writes and reject AUTHORIZED_RUN claims at this service boundary.

GREEN command:

   python -m pytest -q tests/test_action_submission_service.py

Affected regression:

   python -m pytest -q tests/test_m2_routes.py tests/test_prototype_task_generation.py tests/test_prototype_task_lifecycle.py

Commit:

   feat: add M3 action submission domain service

### Task 3: Add submission API routes without expanding public identity controls

Files to create or modify:

- app/main.py
- tests/test_action_submission_routes.py

Interfaces consumed:

- ActionSubmissionService from app/services/action_submission.py
- current FastAPI route/exception patterns and ConflictError handlers in app/main.py
- account routing in app/accounts.py

Interfaces produced:

- POST /api/projects/{project_id}/actions/{task_id}/submissions
- GET /api/projects/{project_id}/actions/{task_id}/submissions
- GET /api/projects/{project_id}/submissions/{submission_id}

RED test:

Run:

   python -m pytest -q tests/test_action_submission_routes.py

Expected RED:

- the route names return 404;
- valid DONE/BLOCKED submissions cannot be created or reopened;
- cross-account and stale-revision requests do not yet produce the required 403/409 responses.

Minimal GREEN:

- add thin routes that obtain the trusted actor from the current account routing contract and pass it to ActionSubmissionService;
- do not accept database path, account database, workspace, or actor identity as client-controlled fields;
- preserve the current single-account test convention while ensuring accounts-enabled routing strips externally supplied identity headers;
- serialize safe metadata only and use existing error response shapes.

GREEN command:

   python -m pytest -q tests/test_action_submission_routes.py

Affected regression:

   python -m pytest -q tests/test_if_guide_m1.py tests/test_m2_routes.py tests/test_open_accounts.py

Commit:

   feat: expose M3 action submission routes

### Task 4: Implement ActionReviewService and deterministic review statuses

Files to create or modify:

- app/services/action_review.py
- app/schemas.py
- tests/test_action_review_service.py

Interfaces consumed:

- action_submissions schema and ActionSubmissionService
- PrototypeTaskService.evaluate_p0 and current M2 quality checks
- exact task/project ownership and revision conventions
- existing timestamp and hash helpers in app/services/real_idea_metrics.py

Interfaces produced:

- ActionReviewService.review_submission
- ActionReviewService.get
- ActionReviewService.list_for_submission
- review request/response models for check items, statuses, unknowns, evidence level, recommendation, and reviewer role

RED test:

Run:

   python -m pytest -q tests/test_action_review_service.py

Expected RED:

- no service can produce PASS, FAIL, UNKNOWN, or justified NOT_APPLICABLE;
- exact submission/task revision binding, required PASS evidence, and reviewer metadata are missing.

Minimal GREEN:

- verify exact project, submission, task, and task revision;
- derive deterministic check results from the submission and current M2 task contract;
- preserve user-reported evidence and unknowns;
- require a NOT_APPLICABLE reason;
- reject PASS without critical check evidence;
- reject AUTHORIZED_RUN without a separately recorded authorized-run evidence reference;
- append an immutable review row and transition SUBMITTED to CLOSED, NEEDS_REVISION, or PAUSED according to the review result.

GREEN command:

   python -m pytest -q tests/test_action_review_service.py

Affected regression:

   python -m pytest -q tests/test_action_submission_service.py tests/test_m2_quality_metrics.py tests/test_m2_quality_bindings.py

Commit:

   feat: add M3 action review service

### Task 5: Add evidence-level, source-identity, and fail-closed guards

Files to create or modify:

- app/services/if_guide_m3_guards.py
- app/services/action_submission.py
- app/services/action_review.py
- tests/test_m3_evidence_guards.py

Interfaces consumed:

- ActionSubmissionService and ActionReviewService
- current source identity vocabulary in docs/mainline/IF_GUIDE_R1/TECHNICAL_ROUTE.md
- ConflictError and existing validation error conventions

Interfaces produced:

- provider-free guard functions for submission claims, review evidence level, source identity, and forbidden actions
- a single guard result shape consumed by submission and review services

RED test:

Run:

   python -m pytest -q tests/test_m3_evidence_guards.py

Expected RED:

- a user claim can currently be mistaken for independent verification;
- false AUTHORIZED_RUN, fabricated dependency, unsupported executed/tested/deployed claims, and forbidden external actions are not rejected by an M3 implementation.

Minimal GREEN:

- reject source identity values outside the five approved values;
- keep USER_REPORTED distinct from ARTIFACT_CHECKED and AUTHORIZED_RUN;
- require a concrete evidence reference for ARTIFACT_CHECKED;
- require an authorized-run record for AUTHORIZED_RUN and never create that record in default M3 flow;
- classify unsupported conclusions as UNKNOWN or reject them according to the P0 contract;
- ensure no guard calls Provider, Search, QuickStart, terminal, GitHub, or deployment services.

GREEN command:

   python -m pytest -q tests/test_m3_evidence_guards.py

Affected regression:

   python -m pytest -q tests/test_action_submission_service.py tests/test_action_review_service.py tests/test_v3_handoff_and_tools.py

Commit:

   feat: enforce M3 evidence boundaries

### Task 6: Record M3 P0/P1/P2 quality through the existing ledger

Files to create or modify:

- app/services/if_guide_m3_quality.py
- app/services/real_idea_metrics.py only where the existing artifact-type or payload contract requires a backward-compatible extension
- tests/test_m3_quality_metrics.py

Interfaces consumed:

- ArtifactQualityEvaluation and QualityEvaluationService in app/services/real_idea_metrics.py
- M2 rubric structure in app/services/if_guide_m2_quality.py
- action submission and review read models

Interfaces produced:

- M3 P0 evaluation result
- P1 metrics: evidence_sufficiency, review_accuracy, result_decision_traceability, unsupported_conclusion_rate, recovery_specificity, and unknown_status_distribution
- P2 reviewer hook/status
- immutable evaluation payload bound to project, task, submission, review, revision, and rubric version

RED test:

Run:

   python -m pytest -q tests/test_m3_quality_metrics.py

Expected RED:

- the shared quality service has no M3 rubric;
- M3 quality rows cannot be recovered with exact artifact/revision/source bindings;
- P0/P1 cannot be distinguished from P2 human review.

Minimal GREEN:

- implement provider-free deterministic P0 checks;
- calculate P1 metrics from structured submission/review/recovery/decision records, with explicit denominators and empty-denominator semantics;
- store the result using the existing immutable quality ledger and current hash/revision pattern;
- expose P2 as unreviewed until a real reviewer record is persisted;
- never label a user report as verified and never include full private evidence bodies in the quality receipt.

GREEN command:

   python -m pytest -q tests/test_m3_quality_metrics.py

Affected regression:

   python -m pytest -q tests/test_m2_quality_metrics.py tests/test_m2_quality_bindings.py tests/test_real_idea_quality_metrics.py tests/test_real_idea_artifact_quality.py tests/test_m2_inspector.py

Commit:

   feat: add M3 evidence quality metrics

### Task 7: Implement recovery as a revisioned ActionTask

Files to create or modify:

- app/services/recovery.py
- app/services/action_review.py
- app/services/project_intent.py only for the shared ActionTask row helper if a non-breaking extraction is required
- tests/test_recovery_service.py

Interfaces consumed:

- first_action_cards extension from Task 1
- ActionReviewService
- current ownership, expected_revision, and confirm_action conventions in app/services/project_intent.py

Interfaces produced:

- RecoveryService.create_from_review
- RecoveryService.get_current
- RecoveryService.update
- RecoveryService.confirm

RED test:

Run:

   python -m pytest -q tests/test_recovery_service.py

Expected RED:

- a BLOCKED/FAIL/critical UNKNOWN review cannot create a recovery ActionTask;
- the original task is not preserved with a linked minimal next action;
- recovery ownership, revision, and reopen behavior are absent.

Minimal GREEN:

- allow recovery only for BLOCKED, FAIL, or critical UNKNOWN reviews that identify a blocker;
- create one RECOVERY first_action_cards row in the same project and owner scope;
- store one source review/submission linkage, one concrete next action, and a new revision history;
- transition the original task to PAUSED or NEEDS_REVISION without deleting or overwriting it;
- reuse the existing action edit/confirm semantics and do not call any model or external execution path.

GREEN command:

   python -m pytest -q tests/test_recovery_service.py

Affected regression:

   python -m pytest -q tests/test_if_guide_m1.py tests/test_m2_routes.py

Commit:

   feat: add revisioned M3 recovery actions

### Task 8: Implement user-confirmed M3 decisions separately from Action state

Files to create or modify:

- app/services/m3_decision.py
- app/schemas.py
- tests/test_m3_decision_service.py

Interfaces consumed:

- ActionReviewService and recovery read models
- decision_records schema
- existing app/services/decisions.py only as a boundary reference; do not use its solution-selection method
- ConflictError and project ownership conventions

Interfaces produced:

- M3DecisionService.recommend
- M3DecisionService.confirm
- M3DecisionService.get_current
- decision request/response models for the five allowed decisions

RED test:

Run:

   python -m pytest -q tests/test_m3_decision_service.py

Expected RED:

- no M3 decision record exists;
- decision without a source review or user confirmation cannot be distinguished from a solution-selection decision;
- CLOSED, PASS, STOP, and FINISH semantic boundaries are not enforced.

Minimal GREEN:

- require exact source submission/review, project owner, current review revision, and a user confirmation call;
- allow only CONTINUE, NARROW, CHANGE, STOP, and FINISH;
- store rationale, recommendation, remaining unknowns, confirming actor, and revision;
- keep decision state separate from execution_state and never translate FINISH into deployment or PASS into market validation;
- preserve idempotent confirm behavior and stale-revision 409 responses.

GREEN command:

   python -m pytest -q tests/test_m3_decision_service.py

Affected regression:

   python -m pytest -q tests/test_v3_solution_api.py tests/test_if_guide_m1.py tests/test_m2_routes.py

Commit:

   feat: add user-confirmed M3 decisions

### Task 9: Add M3 API routes and safe inspector/history read models

Files to create or modify:

- app/main.py
- app/services/if_guide_m3_inspector.py
- app/services/if_guide_m2_inspector.py only for a shared safe project read helper
- tests/test_m3_routes.py
- tests/test_m3_history_isolation.py

Interfaces consumed:

- ActionReviewService, RecoveryService, and M3DecisionService
- existing M1/M2 route and conflict response patterns in app/main.py
- IFGuideM2Inspector safe metadata conventions
- account routing in app/accounts.py

Interfaces produced:

- POST /api/projects/{project_id}/submissions/{submission_id}/review
- GET /api/projects/{project_id}/submissions/{submission_id}/review
- POST /api/projects/{project_id}/actions/{task_id}/recovery
- GET /api/projects/{project_id}/actions/{task_id}/recovery
- POST /api/projects/{project_id}/decisions/recommend
- POST /api/projects/{project_id}/decisions/{decision_id}/confirm
- GET /api/projects/{project_id}/m3/history
- read-only M3 inspector metadata for submissions, reviews, recovery references, decisions, evidence level, source identity, revisions, and quality status

RED test:

Run:

   python -m pytest -q tests/test_m3_routes.py tests/test_m3_history_isolation.py

Expected RED:

- M3 API routes and history are absent;
- another account can reach a project or metadata in the new path;
- refresh/reopen and exact source bindings cannot yet be proven.

Minimal GREEN:

- add thin routes that call the domain services and existing ownership/error handling;
- return safe metadata and hashes, not submission descriptions, attachment bodies, full logs, private documents, or full project content;
- make history append-only and ordered by created_at/revision;
- enforce account isolation on every project-scoped read;
- keep Handoff routes and HandoffService untouched.

GREEN command:

   python -m pytest -q tests/test_m3_routes.py tests/test_m3_history_isolation.py

Affected regression:

   python -m pytest -q tests/test_open_accounts.py tests/test_if_guide_m1.py tests/test_m2_routes.py tests/test_v3_handoff_and_tools.py

Commit:

   feat: add M3 review recovery decision routes

### Task 10: Extend the existing project page with the M3 user flow

Files to create or modify:

- app/static/index.html
- app/static/app.js
- app/static/styles.css
- tests/test_m3_frontend_contract.py

Interfaces consumed:

- current M2 render/load/save/confirm functions in app/static/app.js
- M3 route contracts from Task 9
- existing project page anchors in app/static/index.html

Interfaces produced:

- M3 current-action panel showing the current task and revision
- DONE form: what was done, result, evidence references, check outcomes, notes
- BLOCKED form: blocked step, observed result, attempted action, safe evidence references
- review panel distinguishing USER_REPORTED, ARTIFACT_CHECKED, and AUTHORIZED_RUN
- recovery panel showing one minimum next action
- decision panel showing recommendation, evidence source, unknowns, and explicit confirmation
- refresh/reopen rendering from API read models

RED test:

Run:

   python -m pytest -q tests/test_m3_frontend_contract.py

Expected RED:

- the existing page has no M3 controls, route calls, or state rendering;
- the browser contract cannot submit DONE/BLOCKED, inspect review status, recover, or confirm a decision.

Minimal GREEN:

- add M3 sections to the existing page without creating a second product shell;
- use the current fetch/error/revision handling conventions;
- preserve local draft input when a 409 conflict is returned;
- render evidence levels and semantic boundaries in plain language;
- never invoke Provider, Search, terminal, GitHub, deployment, or automatic verification from page load or form submission.

GREEN command:

   python -m pytest -q tests/test_m3_frontend_contract.py

Affected regression:

   python -m pytest -q tests/test_m2_browser_flow.py tests/test_m2_routes.py

Commit:

   feat: add IF Guide M3 project page flow

### Task 11: Add browser E2E, account isolation, and reopen coverage

Files to create or modify:

- tests/run_m3_browser.py
- tests/m3_flow_browser.cjs
- tests/test_m3_browser_contract.py

Interfaces consumed:

- existing browser harness pattern in tests/run_m2_browser.py and tests/m2_flow_browser.cjs
- app/accounts.py account/session routing
- M3 API and existing M1/M2 project page

Interfaces produced:

- isolated browser test application with network disabled at the transport layer
- business-path coverage for login, M2-ready project, DONE and BLOCKED branches, review, recovery, decision confirmation, refresh/reopen, and account switching

RED test:

Run:

   python -m pytest -q tests/test_m3_browser_contract.py

Then, after the browser runner is introduced, run:

   python tests/run_m3_browser.py

Expected RED:

- the existing browser harness cannot find M3 controls;
- persisted submission/review/recovery/decision state cannot be recovered after refresh;
- a second account isolation check is not yet available.

Minimal GREEN:

- follow the existing M2 temporary account app and browser harness;
- exercise actual UI actions rather than direct database writes;
- cover DONE with a review, BLOCKED with a minimal recovery, and a user-confirmed decision;
- reload and reopen the project, then switch accounts and verify denial;
- include stale task revision conflict behavior and verify local form data remains visible;
- assert network calls remain local and Provider/Search tripwires stay at zero.

GREEN command:

   python tests/run_m3_browser.py

Affected regression:

   python tests/run_m2_browser.py

Commit:

   test: cover M3 browser submission and decision flow

### Task 12: Add compatibility, negative integrity matrix, and final M3 verification

Files to create or modify:

- tests/test_m3_compatibility.py
- tests/test_m3_negative_matrix.py
- tests/test_m3_provider_search_tripwires.py

Interfaces consumed:

- all M3 services/routes/read models
- existing M1/M2 and Handoff interfaces
- existing quality ledger

Interfaces produced:

- full M3 negative/integrity test matrix
- final evidence that M1, M2, history/reopen, Solutions/Documents/Handoff navigation, and Formal Handoff remain compatible

RED test:

Run:

   python -m pytest -q tests/test_m3_compatibility.py tests/test_m3_negative_matrix.py tests/test_m3_provider_search_tripwires.py

Expected RED:

- at least one M3 route/service, negative guard, or compatibility assertion is absent before the preceding tasks are complete.

Minimal GREEN:

- cover submission/review failures, stale revisions, cross-account access, wrong task/project/review binding, invalid statuses, false AUTHORIZED_RUN, source-identity upgrade, PASS without evidence, decision without review, decision without confirmation, forbidden external action, recovery overwrite, and P2 false-approval claims;
- assert no Provider/Search call, no hidden external execution, no public Handoff semantic change, no second task system, and no second quality ledger;
- verify existing M1 Purpose/First Action, M2 Build Slice/Prototype Task, project history, Solutions/Documents navigation, and Formal Handoff routes;
- run final checks once on the candidate implementation after all task commits:

   python -m pytest -q tests/test_if_guide_m3_migration.py tests/test_action_submission_service.py tests/test_action_submission_routes.py tests/test_action_review_service.py tests/test_m3_evidence_guards.py tests/test_m3_quality_metrics.py tests/test_recovery_service.py tests/test_m3_decision_service.py tests/test_m3_routes.py tests/test_m3_history_isolation.py tests/test_m3_compatibility.py tests/test_m3_negative_matrix.py tests/test_m3_provider_search_tripwires.py
   python tests/run_m3_browser.py
   python tests/run_m2_browser.py
   python -m pytest -q tests/test_if_guide_m1.py tests/test_m2_routes.py tests/test_v3_handoff_and_tools.py
   python -m compileall -q app/services/action_submission.py app/services/action_review.py app/services/if_guide_m3_guards.py app/services/if_guide_m3_quality.py app/services/recovery.py app/services/m3_decision.py app/services/if_guide_m3_inspector.py app/migrations/if_guide_m3.py app/main.py
   node --check tests/m3_flow_browser.cjs
   git diff --check

   The full backend regression is run once after the final M3 implementation commit, using the repository's established full-backend command; known pre-existing failures must be compared by node ID and signature, and the new-failure delta must be zero.

GREEN command:

   python -m pytest -q tests/test_if_guide_m3_migration.py tests/test_action_submission_service.py tests/test_action_submission_routes.py tests/test_action_review_service.py tests/test_m3_evidence_guards.py tests/test_m3_quality_metrics.py tests/test_recovery_service.py tests/test_m3_decision_service.py tests/test_m3_routes.py tests/test_m3_history_isolation.py tests/test_m3_compatibility.py tests/test_m3_negative_matrix.py tests/test_m3_provider_search_tripwires.py

Affected regression:

   python -m pytest -q tests/test_if_guide_m1.py tests/test_m2_routes.py tests/test_v3_handoff_and_tools.py

Commit:

   test: verify IF Guide R1.1 M3 integrity and compatibility

## Verification matrix

The implementation is complete only when every item below has fresh evidence:

| Area | Required evidence | Failure classification |
| --- | --- | --- |
| storage | one ordered migration, existing rows preserved, M3 tables/columns recoverable | implementation failure |
| submission | DONE and BLOCKED persist with exact task revision and source identity | implementation failure |
| review | PASS, FAIL, UNKNOWN, and justified NOT_APPLICABLE persist with exact bindings | implementation failure |
| evidence | USER_REPORTED, ARTIFACT_CHECKED, and AUTHORIZED_RUN stay distinct; no false upgrade | integrity failure |
| recovery | one minimal RECOVERY task is linked and original task remains | integrity failure |
| decision | all five decisions require source review and user confirmation | integrity failure |
| quality | P0, P1, and P2 states are recoverable; P0/P1 do not imply P2 | evaluation failure |
| ownership | cross-account reads and writes are denied | security failure |
| revision | stale task/submission/review/decision writes return 409 and preserve local draft | concurrency failure |
| honesty | no unsupported executed/tested/deployed/verified conclusion is accepted | integrity failure |
| compatibility | M1/M2/history/Handoff behavior remains reachable and unchanged in semantics | regression failure |
| isolation | browser and service tests use isolated temporary data | safety failure |
| external calls | Provider, Search, terminal, GitHub, and deployment calls are zero | boundary failure |

No metric threshold is promoted to a broad product claim from a single M3 run. M3 quality evidence is diagnostic unless the authority documents later define a validated threshold. Human review remains separate from deterministic P0 and structured P1 evaluation.

## Implementation stop condition

Stop after the final M3 verification. At that point the repository supports:

- DONE and BLOCKED submissions
- honest review with PASS, FAIL, UNKNOWN, and NOT_APPLICABLE
- source/evidence-level preservation
- one minimal recovery action
- explicit user-confirmed decision
- append-only history/reopen and account isolation
- recoverable M3 quality metrics
- Provider/Search equal to zero

Do not implement Submission, Recovery result loops beyond this contract, M4 experiments, participant recruitment, payment, deployment automation, terminal/GitHub execution, or full PRD/TechDoc/Handoff quality expansion.
