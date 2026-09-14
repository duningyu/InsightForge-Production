# Stage B Real Idea Evaluation Batch — Architecture Specification

**Status:** Architecture specification only; implementation and execution are not approved by this document.
**Baseline source:** `16a12341dcb8911e897655e15caf398e68e8d8f8`
**Branch:** `deploy/railway-stage-b`
**Date:** 2026-09-14

## 1. Decision and scope

The approved three-sample Real Idea Evaluation Batch requires a new internal evaluation wrapper and bounded batch ledger. The current product flow is not yet ready for the batch: the normal QuickStart path consumes Provider transport and can make more than one attempt, while public project creation cannot set evaluation-only metrics exclusion at birth. Therefore this specification is a target architecture, not authorization to run the batch.

The implementation must preserve the formal product path for idea interpretation, validation, confirmation, Solutions generation, selection, documents, acknowledgement, and Handoff. The evaluation wrapper may control only evaluation identity, privacy handling, budget reservation, sample orchestration, and receipts. It must not fabricate a brief, bypass validation or confirmation, suppress a required product transition, or make synthetic-seed evidence count as real-user evidence.

Non-goals are production implementation, migrations, tests, deployment, real-user collection, Provider calls, Search, UI redesign, and changes to ordinary product semantics.

## 2. Current source facts

The following map was inspected against the baseline source. Names below are source locations, not proposed new interfaces.

| Concern | Current implementation | Current behavior | Architectural implication |
|---|---|---|---|
| Public project creation | `app/main.py` `POST /api/projects` → `ProjectService.create_project`; `app/schemas.py` `ProjectCreateRequest` | Public payload contains only `title` and `summary`; evaluation flags are not public inputs | Keep evaluation identity internal |
| Project transaction | `app/services/projects.py` `create_project`, `create_project_tx` | Internal transaction helper already accepts `project_origin` and `exclude_from_beta_metrics`; defaults are `user` and `false` | Wrapper can use a first-class internal create contract, but one does not yet exist |
| Project schema | `app/db.py` schema initialization | `project_origin` is constrained to `user`, `demo`, or `qa`; exclusion is an integer boolean | Real samples must be born `user` plus exclusion `true`, never mutate after creation |
| Raw idea entry | `app/main.py` `POST /api/projects/quick-start` → `QuickStartService.quick_start` | Raw idea is accepted with optional target-user/resources/priority | Batch input must retain redacted raw wording and avoid PRD rewriting |
| QuickStart runtime | `app/services/quick_start.py` → `interpret_idea`; `app/services/hybrid_runtime.py`; `app/services/ai_runtime.py` | Structured Provider generation is used; the profile runtime can retry while model rounds remain | Current normal path does not prove a one-transport hard maximum |
| Provider boundary | `app/services/provider_adapters.py` `ModelAdapter._request`; injected adapter/client and ledger/permit hooks | Transport failures are classified and recorded; adapter injection is the lowest practical fake seam | Future tests must replace only transport/adapter behavior |
| Brief persistence | `app/services/quick_start.py` `_insert_brief_tx` | Draft is persisted after QuickStart output; successful QuickStart uses inferred confirmation status | Batch must separately perform official confirmation |
| Brief confirmation | `app/services/quick_start.py` `confirm_brief`; public confirm route in `app/main.py` | Formal confirmation uses product service semantics and human confirmation | Wrapper must call this contract, never set a confirmation field directly |
| Brief model | `app/schemas.py` `IdeaBriefDraft` | Contains idea, target user, problem, desired outcome, resources, constraints, unknowns and clarification fields; current validation does not enforce substantive completeness | A versioned completeness contract is required for the batch |
| Solutions | `app/services/solution_design.py` `SolutionDesignService.generate` | Confirmed brief is required; Stage B canary already has one-shot/validation policy controls | Reuse the existing service and add the batch stage gate around it |
| Stage B accounting | `app/services/stage_b_evaluation.py`, `provider_dispatch_ledger.py`, `dispatch_control.py` | Durable evaluation context, dispatch linkage, permits, and safe receipts exist for Stage B | Extend the same concepts with batch/sample/stage reservation identity |
| Documents | `app/services/loop.py` `DocumentLoop`; `app/services/generation.py` `LocalDocumentGenerator`; `app/services/document_versions.py`; `app/services/document_workspace.py` | Local document generation/versioning is an existing product path | Batch pauses for review after generated documents; no Provider is added here |
| Handoff | `app/services/handoff.py` `HandoffService`, `_build_v3_zip` | Existing assembly/package path | Bind Handoff to exact snapshot and document versions |
| Synthetic seed | `app/services/stage_b_synthetic_seed.py` | Provider-free demo seed path | Explicitly excluded from Real Idea evidence |
| Operator | `scripts/stage_b_evaluation_inspect.py` | Stage B inspection/operators exist; no Real Idea Batch operator | A future operator must be internal/CLI-only and fail closed |
| Migration mechanism | `app/db.py` schema initialization plus existing legacy migration services; no `alembic/` directory or Alembic revision history exists | Current repository lacks the “existing Alembic” mechanism assumed by the approved design | Implementation must introduce a reviewable versioned schema-migration discipline using the actual application mechanism before deployment; this spec does not silently claim Alembic exists |

### Current feasibility conclusion

The previous isolated feasibility evidence established that the current normal path costs one QuickStart transport plus one Solutions transport on success, and that 503/timeout behavior can attempt two QuickStart transports under the current runtime. The current path therefore has minimum cost 2 and an unbounded-for-this-contract maximum greater than 1. It cannot satisfy the locked batch contract without the target changes in this specification.

## 3. Batch identity, privacy, and sample composition

The batch contains exactly three slots:

| Sample | Source type | Required identity |
|---|---|---|
| `REAL_IDEA_01` | project owner | real owner idea |
| `REAL_IDEA_02` | student/job-seeker | real student/job-seeker idea |
| `REAL_IDEA_03` | career-switcher/junior PM | real career-switcher/junior-PM idea |

Each sample project is created through an internal wrapper with `project_origin='user'` and `exclude_from_beta_metrics=true` at birth. The ordinary public API cannot request either evaluation control. No `user → demo` or later exclusion mutation is permitted.

The stored input is the original user wording after minimal privacy redaction, plus a SHA-256 fingerprint. No names, contact details, school identifiers, employer identifiers, or other PII are stored in Stage B. Redaction must not rewrite the idea into PRD language or add a target user, feature list, or conclusion. The raw wording and its hash are bound to the immutable batch manifest and sample record.

The synthetic seed project and any demo project are not eligible sample substitutes and must never be mixed into this batch.

## 4. Logical evaluation data model

Evaluation-only records are logically separate from product records while remaining in the same SQLite database. Ordinary product routes and product DTOs must not expose these tables.

### `real_idea_batches`

Required fields: `batch_id`, `batch_key`, `status`, `created_at`, `started_at`, `finished_at`, `finalized_at`, `manifest_sha256`, `source_commit`, `deployment_id`, `model`, `prompt_hash`, `schema_hash`, `completeness_contract_version`, `questionnaire_version`, `sample_count`, `search_allowed`, `provider_policy_version`, `batch_version_split`, `failure_classification`, and safe aggregate counts.

Constraints: `batch_key` is unique; `sample_count=3`; `search_allowed=false`; terminal timestamps are monotonic; a finalized batch cannot be edited.

### `real_idea_samples`

Required fields: `sample_id`, `batch_id`, `sample_key`, `source_type`, `project_id`, `raw_idea_sha256`, `redaction_version`, `state`, `withdrawal_reason`, `brief_version_id`, `solutions_evaluation_id`, `selected_solution_id`, `snapshot_id`, `prd_version_id`, `techdoc_version_id`, `handoff_run_id`, `sample_manifest_sha256`, `budget_allocation_id`, `created_at`, and terminal metadata.

Constraints: `(batch_id, sample_key)` is unique; `sample_key` is one of the three fixed keys; `source_type` is immutable after binding; a project belongs to at most one bound sample; no full raw idea is placed in ordinary evaluation receipts.

### `real_idea_feedback`

Required fields: `feedback_id`, `batch_id`, `sample_id`, `stage`, `submitted_by`, `submitted_at`, `accepted`, `score_payload`, `raw_feedback_text`, `feedback_attestation`, and `feedback_schema_version`.

`submitted_by` must be `idea_provider`; `feedback_attestation` must be true for a valid submission. Raw feedback is retained only under the approved privacy boundary and must not contain PII in the ordinary receipt. Feedback is immutable after submission.

Required scores are: `solution_difference_score`, `continuation_value_score`, `decision_helpfulness_score`, and final `idea_fidelity`, `selection_inheritance`, `workload_reduction`, `continued_use_intent`, each on the declared 1–5 scale where applicable, plus raw value and improvement points.

### `real_idea_budget_allocations`

Required fields: `allocation_id`, `batch_id`, `authorized_total`, `batch_earmark`, `sample_cap`, `quickstart_cap`, `solutions_cap`, `purpose`, `state`, `created_at`, `released_at`, and `release_count`.

The allocation is purpose-restricted to this batch and cannot become general spendable budget. `release_count` is at most one.

### `real_idea_transport_reservations`

Required fields: `reservation_id`, `batch_id`, `sample_id`, `stage`, `ordinal`, `idempotency_key`, `state`, `reserved_at`, `attempted_at`, `dispatch_id`, `transport_id`, `released_at`, and safe failure classification.

Unique key: `batch_id + sample_id + stage + ordinal`; ordinal is `1`. States are `RESERVED`, `ATTEMPTED`, and `RELEASED`. A reservation is never reused, and `ATTEMPTED` is never returned to the pool.

## 5. Schema and transaction strategy

The current repository has no Alembic directory or revision chain. The implementation must therefore use a versioned, reviewable migration discipline built on the repository’s actual `app/db.py` initialization/migration mechanism, or add an equivalent explicit migration mechanism before the feature is deployed. It must not use ad-hoc startup table creation without a recorded schema version, direct production SQL from an operator, or silent destructive alteration. This specification intentionally leaves the current absence visible rather than claiming a nonexistent Alembic setup.

Batch creation is one transaction:

1. validate fixed manifest and sample source types;
2. create the purpose-restricted extension `REAL_IDEA_BATCH_01_EXT_01` (+3);
3. bind the extension and batch earmark atomically;
4. create the `real_idea_batches` row and exactly three sample slots;
5. commit.

If any step fails, no batch, extension binding, or sample slot is visible.

Sample project creation and initial raw-input registration are separate from batch creation but each must be atomic. The wrapper creates the project directly as `user` with metrics exclusion true, then invokes the formal QuickStart/brief path. No direct SQL is allowed in the wrapper.

Budget gate and reservation creation are one transaction. The durable `ATTEMPTED` reservation must be persisted before network transport. A process crash after that point is an operational incomplete, not permission to retry.

## 6. Immutable batch manifest and version control

The manifest must include:

- source commit and deployment identity;
- model `qwen3.7-flash`;
- prompt hash and structured schema hash;
- completeness contract version;
- questionnaire and feedback schema versions;
- sample count and sample source types;
- QuickStart and Solutions one-shot policy;
- global, batch, sample, and stage transport caps;
- Search disabled;
- document/acknowledgement semantics;
- privacy/redaction version.

The manifest is immutable after the first sample binds. Any code, prompt, schema, model, completeness, product behavior, or policy change mid-batch sets `batch_version_split=true` and caps the outcome at `PARTIAL`; it must not be silently mixed into one result.

## 7. State machines and forced pauses

Batch states:

`CREATED → RUNNING → COMPLETED | PARTIAL | FAILED | STOPPED → FINALIZED`.

Sample states:

`SLOT_CREATED → PROJECT_CREATED → BRIEF_PENDING → AWAITING_BRIEF_REVIEW → BRIEF_CONFIRMED → SOLUTIONS_GENERATED → AWAITING_SOLUTION_SELECTION → SOLUTION_SELECTED → DOCUMENTS_GENERATED → AWAITING_DOCUMENT_REVIEW → EVIDENCE_ACK_PENDING → HANDOFF_READY → FEEDBACK_PENDING → COMPLETED`.

Allowed terminal alternatives are `SAMPLE_WITHDRAWN`, `OPERATIONAL_INCOMPLETE`, and `FAILED`. A sample cannot skip a review state, and a failure cannot transition back to an earlier state.

The provider choices are explicit:

- Brief: `ACCEPT_AS_IS`, `EDIT_AND_ACCEPT`, `REJECT`.
- Solutions: original idea provider selects one persisted solution and supplies a 1–3 sentence reason plus the three solution scores.
- Documents: batch one allows only `ACCEPT` or `REJECT`; edit-and-continue is out of scope.
- Evidence: explicit acknowledgement is required where unresolved/zero-source state remains.
- Final feedback: required scores and raw value/improvement points.

## 8. QuickStart and brief contract

The target flow is:

`redacted raw idea → internal user-origin evaluation project → formal QuickStart → structured parse → substantive completeness validation → AWAITING_BRIEF_REVIEW → official confirmation → Solutions preflight`.

QuickStart has a hard cap of exactly one Provider transport per sample. It must set retry, repair/regeneration, and fallback counts to zero for this evaluation policy. The four-layer gate is global → batch → sample → stage; every layer must authorize the same transport.

The brief completeness contract is versioned and requires substantive, non-placeholder values for `idea`, `target_user`, `problem`, and `desired_outcome`. Empty, placeholder, circular, or “to be decided” content is invalid. Completeness failure is terminal for that QuickStart attempt and cannot trigger a second Provider call. The validator must fail closed and must not invent missing fields.

The successful output remains `AWAITING_BRIEF_REVIEW`, not automatically confirmed. Manual edit-and-accept occurs through the official non-Provider confirmation/edit contract. `REJECT` stops the sample. No evaluation shortcut may set an inferred draft to confirmed.

This target completeness rule is not present at the required strength in the current `IdeaBriefDraft`; implementation must add and version it before batch execution. This document does not implement it.

## 9. Solutions, selection, and feedback

After confirmed brief and preflight, Solutions uses the existing `SolutionDesignService` under a separate hard cap of one Provider transport, exactly three persisted solutions, no validation regeneration, no retry, and no fallback. Stable ordering and persistence are required.

The idea provider selects personally. The selection record binds the selected solution, exact current snapshot, and original rationale. Selection itself is Provider-free. No second Solutions generation is allowed for a preference change.

The selection feedback contract records:

- `solution_difference_score`;
- `continuation_value_score`;
- `decision_helpfulness_score`;
- raw value and improvement points.

Each score is 1–5 and is not used to tune prompts or alter the current batch. A low score alone does not stop the batch; integrity, consent, or contract violations do.

## 10. Documents, acknowledgement, and Handoff

PRD, TechDoc, and Handoff reuse the current local product architecture: `DocumentLoop`, `LocalDocumentGenerator`, versioning/workspace services, and `HandoffService._build_v3_zip`. They do not add Provider transports to this batch.

After generation, each document enters `AWAITING_DOCUMENT_REVIEW`. Batch one supports only accept/reject. A rejected document makes the sample fail; there is no edit continuation in this design.

The Handoff input must explicitly bind project, selected solution context, exact snapshot, exact confirmed PRD version, exact confirmed TechDoc version, and the acknowledgement state. Latest-row lookup is prohibited.

For zero-source or unresolved content, the idea provider gives an explicit acknowledgement. The acknowledgement is evidence of acknowledgement only; `acknowledged != externally_verified`. It must never be represented as external verification, research validation, or factual correctness.

The final Handoff receipt stores safe state, IDs, hashes, timestamps, package SHA and byte count. It must not store full document bodies, raw Provider payloads, acknowledgement prose, or ZIP content in an ordinary receipt.

## 11. Budget extension, earmark, and reservation discipline

Current durable budget is 6 and current conservative safe ceiling is 5. Before the extension exists, the batch cannot claim additional capacity.

Create an independent auditable extension `REAL_IDEA_BATCH_01_EXT_01` for +3. After creation and binding, the authorized accounting view is:

```text
current available durable budget       = 6
purpose-restricted extension           = +3
authorized total for this batch        = 9
batch earmark                          = 6
sample hard cap                        = 2
QuickStart cap per sample              = 1
Solutions cap per sample               = 1
three-sample maximum                   = 3 × (1 + 1) = 6
general spendable budget                = 6, not 9
```

The +3 extension is an auditable authorization reserve, not a license to spend nine transports. The batch transaction binds the extension and earmarks six units atomically. Every sample has a total hard cap of two. The expected successful batch consumes six: one QuickStart plus one Solutions transport for each of three samples. Unused earmark is released exactly once only after a terminal batch state and finalization; `ATTEMPTED` reservations are never released.

Reservation idempotency key is `batch_id + sample_id + stage + ordinal`, with ordinal `1`. States move `RESERVED → ATTEMPTED` before network → `RELEASED` only for never-attempted unused reservations after finalization. There is no automatic reservation retry.

All real Provider transports are strictly serial. Samples may interleave only between completed stages, never concurrently at the Provider boundary. A global, batch, sample, and stage gate must all pass before a transport.

## 12. Failure, stop, and outcome policy

One-shot Provider 503 or timeout is `OPERATIONAL_INCOMPLETE`: the sample stops without retry; other samples may continue; the batch can finish only as `PARTIAL`.

Engineering or integrity hard failures stop the batch immediately: budget mismatch, Search activity, cross-sample receipt linkage, version binding failure, acknowledged-as-verified collapse, unbounded transport, or privacy/PII violation. A low user score alone does not stop or retune the batch.

Outcome classification:

- **PASS:** all 3 samples complete end to end, integrity is clean, and at least 2/3 samples have all three Solutions scores ≥4 plus E2E `idea_fidelity`, `selection_inheritance`, and `continued_use_intent` ≥4.
- **PARTIAL:** external Provider failure, user withdrawal, missing feedback, or version split without an integrity violation; report affected samples and do not impute success.
- **FAIL:** semantic completeness failure, brief/document rejection, core score threshold failure, budget/Search/cross-sample/version-binding violation, or any collapse of acknowledgement into external verification.

Failure recording must be fail closed. A secondary failure while writing `mark_failure` must still force the durable receipt to `FAILED`; it must not create a false success or a retry permission.

Sample replacement is permitted only before binding and must use the same `source_type`. After binding, withdrawal produces `SAMPLE_WITHDRAWN`; the sample is not silently replaced.

## 13. Inspector and operator requirements

The future operator is internal/CLI-only. No public route is added and ordinary APIs remain unaware of evaluation tables, budget reservations, sample manifests, or Provider diagnostics.

Safe inspector metadata must include operation, batch/sample/project IDs, stage, source type, state, snapshot ID, selected solution ID, document version IDs, reservation state, dispatch/transport IDs, failure classification, package SHA/byte count, and aggregate score values. It must not expose raw idea text, full feedback prose, document bodies, Provider payloads, secrets, or PII.

The operator must support read-only inspection and dry checks. Help mode creates no batch, sample, reservation, evaluation, confirmation, document, acknowledgement, or Provider activity.

## 14. Public boundary and ordinary compatibility

`POST /api/projects` remains title/summary-only and cannot accept evaluation origin, metrics exclusion, sample ID, budget, or batch controls. Existing QuickStart, confirmation, Solutions, document, and Handoff product routes retain their ordinary semantics. The wrapper is not a public debug route and is not reachable from frontend navigation.

`public_api_change_planned=false` for this architecture. Any implementation that changes public DTOs, exposes evaluation tables, or makes ordinary user flows one-shot by global configuration is out of scope and fails review.

## 15. Acceptance criteria before any real batch authorization

All of the following must be demonstrated in isolated tests and source review:

1. Internal project wrapper creates `user` plus metrics exclusion true at birth.
2. Raw idea is redacted/fingerprinted without semantic rewriting or PII storage.
3. Formal QuickStart path reaches an awaiting-review state and official confirmation; no fabricated brief is accepted.
4. Versioned completeness rejects substantive semantic omissions with zero repair transport.
5. QuickStart hard cap is one, with retry/repair/fallback all zero.
6. Solutions hard cap is one and exactly three solutions persist.
7. Four-layer gate and idempotent reservation prevent a second transport.
8. Budget gate and reservation are atomic; attempted reservations are never returned.
9. Local PRD/TechDoc/Handoff paths remain Provider-free and bind exact versions/snapshot.
10. Explicit acknowledgement is separate from external verification.
11. Batch/sample/feedback/ledger receipts recover across processes without content leakage.
12. Schema migration is versioned and reviewable using the repository’s actual mechanism; no silent untracked table creation is allowed.
13. Search remains structurally disabled.
14. Three isolated fake E2E samples prove PASS/PARTIAL/FAIL classification and no cross-sample contamination.
15. No real batch execution, deployment, or persistent Stage B mutation occurs until a separate authorization is issued.

## 16. Self-review and current blocker

This specification preserves the current source facts and does not claim that the current code already meets the target. Known blockers are explicit:

- no dedicated Real Idea Evaluation internal wrapper;
- public project creation does not expose evaluation identity, and the wrapper is absent;
- current QuickStart runtime can consume a Provider transport and may retry to a second attempt;
- current brief model lacks the required substantive completeness contract;
- repository has no existing Alembic revision chain, so migration discipline must be resolved through the actual database initialization/migration architecture;
- no Real Idea Batch tables, reservation ledger, immutable manifest, or batch operator currently exist.

No production code, test, migration, deployment, Provider request, Search request, project, receipt, or budget mutation is authorized by this document.

**Next legal action:** review and approve this architecture specification, then implement the smallest isolated wrapper/ledger/migration plan. Do not execute `REAL_IDEA_01`–`REAL_IDEA_03` yet.
