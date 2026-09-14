# Stage B Real Idea Evaluation Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved, evaluation-only three-sample Real Idea Batch with a user-origin internal wrapper, one-shot QuickStart and Solutions transport reservations, review gates, quality metrics, and fail-closed accounting without changing ordinary product behavior or public API shape.

**Architecture:** Extend the existing SQLite-backed service and Provider-ledger contracts with versioned evaluation tables and an internal orchestration layer. The wrapper owns only evaluation identity, redacted sample metadata, reservations, and state transitions; the existing QuickStart, confirmation, Solutions, DocumentLoop, Handoff, and Provider boundaries remain the execution contracts. Human review finalizes the Requirement Gold Set and all PASS/PARTIAL/FAIL decisions. Quality metrics are stored as versioned, integrity-checked evaluation payloads with normalized links to sample and artifact identities.

**Tech Stack:** Python 3.10-compatible application code, existing SQLite `Database`/transaction helpers, Pydantic schemas, FastAPI service boundaries, pytest, existing Provider adapter injection seam, existing dispatch ledger/permit controls, Node syntax checks, and the repository's current migration-compatible database initialization path.

**Spec:** `docs/superpowers/specs/2026-09-14-stage-b-real-idea-evaluation-batch-design.md`

Approved architecture source: `08114cd5193b9db43fe2a551067f555018ddf1cc`; original architecture source: `26f3e6b`. Production baseline: `16a12341dcb8911e897655e15caf398e68e8d8f8`.

## Planned File Structure

| Operation | Path | Primary responsibility |
| --- | --- | --- |
| CREATE | `app/migrations/real_idea_evaluation_v1.py` | Versioned evaluation schema migration |
| MODIFY | `app/db.py` | Register migration through existing initialization |
| CREATE | `app/services/real_idea_evaluation.py` | Internal wrapper, state machine, review gates |
| CREATE | `app/services/real_idea_budget.py` | Restricted credit and transport reservations |
| CREATE | `app/services/real_idea_metrics.py` | Gold set, annotations, quality metrics |
| CREATE | `app/services/real_idea_redaction.py` | Redaction, hashing, manifest safety |
| MODIFY | `app/schemas.py` | Internal evaluation models and brief completeness |
| MODIFY | `app/services/projects.py` | Internal user-origin/metrics-excluded creation |
| MODIFY | `app/services/quick_start.py` | Evaluation QuickStart one-shot flow |
| MODIFY | `app/services/hybrid_runtime.py` | Evaluation runtime policy propagation |
| MODIFY | `app/services/provider_adapters.py` | Lowest-boundary fake seam and permit propagation |
| MODIFY | `app/services/solution_design.py` | Evaluation Solutions one-shot policy |
| MODIFY | `app/services/stage_b_evaluation.py` | Durable context and linkage reuse |
| MODIFY | `app/services/provider_dispatch_ledger.py` | Restricted ledger linkage |
| MODIFY | `app/services/dispatch_control.py` | At-most-once dispatch/transport gate |
| MODIFY | `scripts/stage_b_evaluation_inspect.py` | Read-only Stage-B operator and inspector |
| CREATE | `tests/test_real_idea_evaluation_schema.py` | Migration and ledger tests |
| CREATE | `tests/test_real_idea_brief_completeness.py` | Semantic brief completeness tests |
| CREATE | `tests/test_real_idea_quickstart_one_shot.py` | QuickStart one-shot tests |
| CREATE | `tests/test_real_idea_budget_and_reservations.py` | Budget and reservation tests |
| CREATE | `tests/test_real_idea_batch_state.py` | State-machine and finalization tests |
| CREATE | `tests/test_real_idea_feedback_and_documents.py` | Review, acknowledgement, feedback tests |
| CREATE | `tests/test_real_idea_quality_metrics.py` | Quality metric tests |
| CREATE | `tests/test_real_idea_operator.py` | CLI and public-boundary tests |
| CREATE | `tests/test_real_idea_e2e.py` | Isolated three-sample fake E2E tests |

No `app/main.py` or frontend file is planned for modification.

## Global Constraints

- Do not call a real Provider or Search service in implementation tests or local E2E tests.
- Do not connect test execution to `/app/data` or any existing Stage B project.
- Do not change ordinary public project creation, QuickStart, Solutions, document, or Handoff API semantics.
- Do not expose evaluation identity controls through public request schemas or routes.
- Do not store user PII in evaluation records; retain only minimally redacted raw wording, a redaction version, and a SHA-256 fingerprint.
- Do not use direct SQL from an operator or service method for domain state changes; all writes go through repositories/services and the shared transaction boundary.
- Preserve Provider reservation ordering: reserve before dispatch, mark attempted before network, never release an attempted reservation, and enforce serial transports.
- The authorized restricted extension is `REAL_IDEA_BATCH_01_EXT_01`; the batch earmark is six transports and the maximum is two per sample, with QuickStart one and Solutions one.
- The public API and frontend remain unchanged. No deployment, push, Railway mutation, or real three-sample batch is part of this plan.

## File Responsibilities and Task Map

Create:

- `app/migrations/real_idea_evaluation_v1.py` — versioned schema migration for batch, sample, budget, reservation, feedback, and metric records using the existing database migration discipline.
- `app/services/real_idea_evaluation.py` — batch/sample state machine, internal wrapper, review gates, artifact binding, and finalization orchestration.
- `app/services/real_idea_budget.py` — restricted credit activation, batch earmark, historical ledger, and reservation accounting.
- `app/services/real_idea_metrics.py` — Requirement Gold Set, requirement mappings, claim annotations, decision/inheritance annotations, and metric calculations.
- `app/services/real_idea_redaction.py` — deterministic raw-idea redaction, hash, sample manifest validation, and PII rejection.
- `tests/test_real_idea_evaluation_schema.py` — migration, constraints, indexes, and evaluation-only ledger isolation.
- `tests/test_real_idea_brief_completeness.py` — substantive brief completeness and fail-closed semantics.
- `tests/test_real_idea_quickstart_one_shot.py` — QuickStart one-shot policy and fake transport outcomes.
- `tests/test_real_idea_budget_and_reservations.py` — extension, earmark, reservation, and at-most-once accounting.
- `tests/test_real_idea_batch_state.py` — batch/sample state transitions and atomicity.
- `tests/test_real_idea_feedback_and_documents.py` — human review, selection, document review, acknowledgement, and artifact bindings.
- `tests/test_real_idea_quality_metrics.py` — gold set, recall, factuality, differentiation, inheritance, contradiction, and reporting metrics.
- `tests/test_real_idea_operator.py` — CLI/inspector contracts and zero-call behavior.
- `tests/test_real_idea_e2e.py` — isolated fake three-sample partial/PASS flows and integrity-failure flows.

Modify:

- `app/db.py` — register and apply the versioned evaluation migration through the existing initialization path; do not create evaluation tables ad hoc at startup.
- `app/schemas.py` — add internal-only evaluation command/result models and substantive `IdeaBriefDraft` completeness helpers while retaining public request fields.
- `app/services/projects.py` — add an internal evaluation creation method that writes `project_origin='user'` and `exclude_from_beta_metrics=1` at insert time; keep `create_project` public defaults unchanged.
- `app/services/quick_start.py` — accept an internal evaluation context, enforce one-shot policy, persist the redacted source/fingerprint, and stop at `AWAITING_BRIEF_REVIEW` after a complete brief.
- `app/services/hybrid_runtime.py` — honor an injected one-shot evaluation policy without changing the normal runtime default.
- `app/services/provider_adapters.py` — preserve the adapter injection seam and route evaluation permits through the existing lowest transport boundary without adding retry/fallback behavior.
- `app/services/solution_design.py` — consume the evaluation execution policy and reservation; retain ordinary validation regeneration and existing ordinary route behavior.
- `app/services/stage_b_evaluation.py` — reuse durable evaluation context and dispatch linkage for Real Idea sample stages.
- `app/services/provider_dispatch_ledger.py` — record restricted-credit and sample-stage reservation linkage while preserving existing accounting.
- `app/services/dispatch_control.py` — enforce the evaluation permit's one-shot boundary at dispatch/transport time.
- `scripts/stage_b_evaluation_inspect.py` — add a Stage-B-only read-only operator for isolated fake evaluation inspection; no public HTTP route.

No `app/main.py` or frontend file is planned for modification. Existing ordinary-route tests will prove that boundary remains unchanged.

## Canonical Interfaces

The implementation tasks use these stable interfaces. Names may be adjusted only when the existing repository naming convention requires it; field semantics and invariants remain fixed.

```python
@dataclass(frozen=True)
class EvaluationExecutionPolicy:
    batch_id: str
    sample_id: str
    stage: Literal["QUICKSTART", "SOLUTIONS"]
    max_provider_transports: int = 1
    retry_allowed: bool = False
    regeneration_allowed: bool = False
    fallback_allowed: bool = False

@dataclass(frozen=True)
class ProviderTransportReservation:
    reservation_id: str
    batch_id: str
    sample_id: str
    stage: str
    ordinal: int
    state: Literal["RESERVED", "ATTEMPTED", "RELEASED"]

class RealIdeaEvaluationService:
    def start_batch(self, manifest: BatchManifest, actor: str) -> BatchRecord: ...
    def start_sample(self, batch_id: str, sample: SampleInput) -> SampleRecord: ...
    def run_quickstart(self, sample_id: str) -> BriefReviewRecord: ...
    def review_brief(self, sample_id: str, decision: BriefReviewDecision) -> SampleRecord: ...
    def run_solutions(self, sample_id: str) -> SolutionReviewRecord: ...
    def record_selection(self, sample_id: str, selection: SelectionDecision) -> SampleRecord: ...
    def review_documents(self, sample_id: str, review: DocumentReviewDecision) -> SampleRecord: ...
    def record_feedback(self, sample_id: str, feedback: FeedbackAttestation) -> SampleRecord: ...
    def finalize_batch(self, batch_id: str) -> BatchFinalization: ...
```

The service returns safe identifiers, statuses, counts, fingerprints, reservation states, and hashes; it never returns Provider secrets, raw Provider payloads, full document bodies, or unredacted user input from an ordinary receipt.

## Task 1: Add Versioned Evaluation Schema and Migration

Files:

- Create `app/migrations/real_idea_evaluation_v1.py`.
- Modify `app/db.py`.
- Create `tests/test_real_idea_evaluation_schema.py`.

Interfaces consumed/produced:

- Consume the existing `Database` connection/transaction helpers and current schema-version mechanism.
- Produce `real_idea_batches`, `real_idea_samples`, `real_idea_budget_allocations`, `real_idea_transport_reservations`, `real_idea_feedback`, and normalized annotation storage for requirement/claim/decision/inheritance records.
- Produce unique keys for `(batch_id, sample_id, stage, ordinal)`, foreign keys to projects/snapshots/document versions where the current schema supports them, and immutable audit fields.

RED test:

```python
def test_real_idea_schema_is_versioned_and_isolated(tmp_path):
    db = Database(tmp_path / "evaluation.sqlite")
    db.init_schema()
    assert db.schema_version() >= 1
    assert db.table_names() >= {
        "real_idea_batches", "real_idea_samples",
        "real_idea_budget_allocations", "real_idea_transport_reservations",
        "real_idea_feedback", "real_idea_annotations",
    }
    assert db.public_project_schema_has_no_evaluation_identity_input()
```

Run RED: `python -m pytest -q tests/test_real_idea_evaluation_schema.py::test_real_idea_schema_is_versioned_and_isolated`.

Expected RED reason: the current repository has no Real Idea evaluation tables or migration registration.

Minimum implementation: add one reviewable migration module and register it through `Database.init_schema`; use the existing version table/transaction style, preserve all existing tables, and make re-application idempotent. Store quality annotations in one normalized annotation table with typed `annotation_kind` plus validated JSON payload, rather than creating duplicate tables and JSON copies.

Run GREEN: `python -m pytest -q tests/test_real_idea_evaluation_schema.py`.

Regression: `python -m pytest -q tests/test_v3_schema_migration.py tests/test_v3_legacy_migration.py tests/test_stage_b_evaluation.py`.

Review: a fresh reviewer checks migration ordering, rollback behavior, foreign-key coverage, no public identity columns, no PII columns, and compatibility with existing databases.

Commit: `git add -- app/db.py app/migrations/real_idea_evaluation_v1.py tests/test_real_idea_evaluation_schema.py && git commit -m "feat: add real idea evaluation ledger schema"`.

## Task 2: Enforce Semantic IdeaBrief Completeness

Files:

- Modify `app/schemas.py`.
- Modify `app/services/quick_start.py`.
- Create `tests/test_real_idea_brief_completeness.py`.

Interfaces consumed/produced:

- Consume `IdeaBriefDraft`, existing QuickStart parsing/validation, and the evaluation policy.
- Produce `validate_substantive_completeness()` with explicit required semantic fields: non-empty idea, target user, problem, and desired outcome; clarification must be false for confirmation eligibility.

RED test:

```python
def test_real_idea_quickstart_rejects_schema_valid_semantically_incomplete_brief(real_idea_service):
    result = real_idea_service.fake_quickstart(
        IdeaBriefDraft(original_idea="x", target_user="", problem="", desired_outcome="")
    )
    assert result.status == "OPERATIONAL_INCOMPLETE"
    assert result.brief_confirmed is False
    assert result.provider_transport_count == 1
```

Run RED: `python -m pytest -q tests/test_real_idea_brief_completeness.py::test_real_idea_quickstart_rejects_schema_valid_semantically_incomplete_brief`.

Expected RED reason: the current model validates field shape but does not enforce substantive completeness.

Minimum implementation: add a pure completeness result with named missing fields; invoke it only under `EvaluationExecutionPolicy`, preserve ordinary QuickStart behavior, and make incomplete output terminal because the policy forbids repair/regeneration.

Run GREEN: `python -m pytest -q tests/test_real_idea_brief_completeness.py`.

Regression: `python -m pytest -q tests/test_quick_start.py tests/test_api_contract.py tests/test_stage_b_api_contract.py`.

Review: verify no synthetic seed, direct SQL, fake confirmation, or public request-field expansion is used.

Commit: `git add -- app/schemas.py app/services/quick_start.py tests/test_real_idea_brief_completeness.py && git commit -m "feat: enforce real idea brief completeness"`.

## Task 3: Implement QuickStart One-Shot Evaluation Policy

Files:

- Modify `app/services/quick_start.py`.
- Modify `app/services/hybrid_runtime.py`.
- Modify `app/services/provider_adapters.py`.
- Modify `app/services/dispatch_control.py`.
- Create `tests/test_real_idea_quickstart_one_shot.py`.

Interfaces consumed/produced:

- Consume `EvaluationExecutionPolicy`, existing adapter factory, runtime parser/validator, and dispatch permit.
- Produce QuickStart stage receipts with logical generation count, dispatch count, transport attempts, retry count, regeneration count, fallback count, final brief state, and reservation IDs.

RED tests:

```python
def test_quickstart_evaluation_allows_one_transport_and_no_repair(fake_evaluation):
    result = fake_evaluation.run_quickstart(successful_brief=True)
    assert result.transport_count == 1
    assert result.retry_count == 0
    assert result.regeneration_count == 0
    assert result.fallback_count == 0
    assert result.status == "AWAITING_BRIEF_REVIEW"

def test_quickstart_503_is_terminal_without_retry(fake_evaluation):
    result = fake_evaluation.run_quickstart(outcome="HTTP_503")
    assert result.transport_count == 1
    assert result.retry_count == 0
    assert result.status == "OPERATIONAL_INCOMPLETE"
```

Run RED: `python -m pytest -q tests/test_real_idea_quickstart_one_shot.py`.

Expected RED reason: the current Hybrid runtime permits multiple model rounds and no evaluation-specific permit reaches the transport boundary.

Minimum implementation: pass a one-shot policy through the real runtime and adapter path, reserve before dispatch, mark attempted before transport, reject a second attempt before network, and classify 503/timeout/incomplete output without retry or fallback. Keep ordinary `max_model_rounds=2` behavior untouched.

Run GREEN: `python -m pytest -q tests/test_real_idea_quickstart_one_shot.py`.

Regression: `python -m pytest -q tests/test_quick_start.py tests/test_provider_adapters.py tests/test_stage_b_provider_observability.py`.

Review: inspect that the policy cannot be selected by public callers and that every failed second attempt is a local gate failure with zero second transport.

Commit: `git add -- app/services/quick_start.py app/services/hybrid_runtime.py app/services/provider_adapters.py app/services/dispatch_control.py tests/test_real_idea_quickstart_one_shot.py && git commit -m "feat: bound real idea quickstart to one shot"`.

## Task 4: Add Restricted Credit, Earmark, and Reservation Accounting

Files:

- Create `app/services/real_idea_budget.py`.
- Modify `app/services/provider_dispatch_ledger.py`.
- Modify `app/services/stage_b_evaluation.py`.
- Create `tests/test_real_idea_budget_and_reservations.py`.

Interfaces consumed/produced:

- Consume existing durable budget and dispatch ledger records.
- Produce `activate_extension(extension_id, authorized_credits)`, `create_batch_earmark(batch_id, 6)`, `reserve_transport(...)`, `mark_attempted(...)`, `release_unattempted(...)`, and `reconcile_batch(...)`.

RED tests:

```python
def test_extension_is_restricted_and_batch_earmark_is_six(budget_service):
    budget_service.activate_extension("REAL_IDEA_BATCH_01_EXT_01", 3)
    allocation = budget_service.earmark_batch("batch-1", 6)
    assert allocation.authorized_total == 9
    assert allocation.general_spendable == 6
    assert allocation.batch_earmark == 6

def test_attempted_reservation_cannot_be_released(budget_service):
    reservation = budget_service.reserve("batch-1", "sample-1", "QUICKSTART", 1)
    budget_service.mark_attempted(reservation.reservation_id)
    with pytest.raises(ReservationStateError):
        budget_service.release(reservation.reservation_id)
```

Run RED: `python -m pytest -q tests/test_real_idea_budget_and_reservations.py`.

Expected RED reason: no restricted extension, batch earmark, or sample-stage idempotent reservation contract exists.

Minimum implementation: persist extension authorization separately from general spendable balance, enforce six earmarked credits and two-per-sample cap, serialize Provider attempts, and use unique batch/sample/stage/ordinal keys. Never decrement on reservation; decrement exactly once on attempted transport.

Run GREEN: `python -m pytest -q tests/test_real_idea_budget_and_reservations.py`.

Regression: `python -m pytest -q tests/test_provider_dispatch_ledger.py tests/test_stage_b_evaluation.py tests/test_stage_b_dry_observability.py`.

Review: verify no budget mutation is possible from help/inspection, no reservation is released after network start, and historical ledger entries remain immutable.

Commit: `git add -- app/services/real_idea_budget.py app/services/provider_dispatch_ledger.py app/services/stage_b_evaluation.py tests/test_real_idea_budget_and_reservations.py && git commit -m "feat: add bounded real idea transport reservations"`.

## Task 5: Add Atomic Batch and Sample State Machine

Files:

- Create `app/services/real_idea_evaluation.py`.
- Modify `app/services/projects.py`.
- Create `tests/test_real_idea_batch_state.py`.

Interfaces consumed/produced:

- Consume `ProjectService.create_project_tx`, `RealIdeaBudgetService`, `RealIdeaRedactionService`, and the migration tables.
- Produce internal `start_batch`, `start_sample`, and `rollback_sample_start` operations. A sample is born with `project_origin='user'`, `exclude_from_beta_metrics=1`, redacted raw idea hash, and no copied artifacts.

RED tests:

```python
def test_batch_start_is_atomic_and_internal_identity_is_set(evaluation_service):
    sample = evaluation_service.start_sample("batch-1", RAW_IDEA)
    project = evaluation_service.read_project(sample.project_id)
    assert project.project_origin == "user"
    assert project.exclude_from_beta_metrics is True
    assert sample.raw_idea_sha256
    assert sample.state == "QUICKSTART_PENDING"

def test_failed_sample_start_rolls_back_project_and_evaluation_rows(evaluation_service):
    with pytest.raises(ExpectedSeedFailure):
        evaluation_service.start_sample("batch-1", RAW_IDEA, fail_after_project=True)
    assert evaluation_service.count_projects() == 0
    assert evaluation_service.count_samples("batch-1") == 0
```

Run RED: `python -m pytest -q tests/test_real_idea_batch_state.py`.

Expected RED reason: the current QuickStart path creates user/metrics-included projects and has no Real Idea batch state machine.

Minimum implementation: add an internal-only project creation method with fixed identity values, perform sample row/project row/earmark linkage in one transaction, validate sample identity and isolation before commit, and implement `CREATED → RUNNING → COMPLETED/PARTIAL/FAILED/STOPPED → FINALIZED` plus operational-incomplete and withdrawn sample states.

Run GREEN: `python -m pytest -q tests/test_real_idea_batch_state.py`.

Regression: `python -m pytest -q tests/test_projects.py tests/test_stage_b_synthetic_project_seed.py tests/test_stage_b_product_flow_phase1a.py`.

Review: confirm public `POST /api/projects` still accepts only its existing fields and that the wrapper cannot target the known synthetic Stage B project or an arbitrary existing project.

Commit: `git add -- app/services/real_idea_evaluation.py app/services/projects.py tests/test_real_idea_batch_state.py && git commit -m "feat: add real idea batch state and isolated project wrapper"`.

## Task 6: Integrate Solutions One-Shot and Selection Review

Files:

- Modify `app/services/solution_design.py`.
- Modify `app/services/real_idea_evaluation.py`.
- Create `tests/test_real_idea_feedback_and_documents.py`.

Interfaces consumed/produced:

- Consume confirmed brief review, `SolutionDesignService.generate`, Stage B execution policy, and the reservation service.
- Produce exactly three persisted candidates, stable ordinals, `AWAITING_SOLUTION_REVIEW`, user-selected solution ID, and a 1–3 sentence selection reason without Provider access during selection.

RED tests:

```python
def test_solutions_review_requires_three_persisted_candidates(real_idea_service):
    result = real_idea_service.run_solutions("sample-1", fake_result_count=3)
    assert result.solution_count == 3
    assert result.transport_count == 1
    assert result.status == "AWAITING_SOLUTION_REVIEW"

def test_selection_is_user_bound_and_provider_free(real_idea_service):
    result = real_idea_service.record_selection("sample-1", selected_ordinal=2, reason="Fits the main workflow.")
    assert result.provider_transport_count == 0
    assert result.selected_solution_ordinal == 2
```

Run RED: `python -m pytest -q tests/test_real_idea_feedback_and_documents.py::test_solutions_review_requires_three_persisted_candidates tests/test_real_idea_feedback_and_documents.py::test_selection_is_user_bound_and_provider_free`.

Expected RED reason: the existing Solutions contract is not connected to the Real Idea sample state, review gate, or batch reservation.

Minimum implementation: invoke the existing generation service with `max_provider_transports=1`, `validation_regeneration_allowed=False`, and a sample-specific context; persist exactly three candidates; reject selection outside the persisted set; store only the user decision and safe rationale metadata.

Run GREEN: `python -m pytest -q tests/test_real_idea_feedback_and_documents.py::test_solutions_review_requires_three_persisted_candidates tests/test_real_idea_feedback_and_documents.py::test_selection_is_user_bound_and_provider_free`.

Regression: `python -m pytest -q tests/test_stage_b_product_flow_phase1a.py tests/test_stage_b_api_contract.py`.

Review: confirm ordinary Solutions generation keeps existing validation regeneration and that selection does not create a new Provider dispatch or alter candidate content.

Commit: `git add -- app/services/solution_design.py app/services/real_idea_evaluation.py tests/test_real_idea_feedback_and_documents.py && git commit -m "feat: add real idea solution review gate"`.

## Task 7: Add Document Review, Explicit Evidence Acknowledgement, and Feedback Attestation

Files:

- Modify `app/services/real_idea_evaluation.py`.
- Modify `app/services/document_workspace.py`.
- Modify `app/services/handoff.py`.
- Create `tests/test_real_idea_feedback_and_documents.py`.

Interfaces consumed/produced:

- Consume existing PRD/TechDoc review states, exact version IDs, snapshot binding, formal acknowledgement contract, and Handoff readiness checks.
- Produce `DocumentReviewDecision`, `EvidenceAcknowledgement`, and `FeedbackAttestation`; preserve `acknowledged != externally_verified`.

RED tests:

```python
def test_document_review_requires_exact_versions_and_explicit_ack(real_idea_service):
    with pytest.raises(ReviewGateError):
        real_idea_service.acknowledge_evidence("sample-1", explicit=False)
    ack = real_idea_service.acknowledge_evidence("sample-1", explicit=True)
    assert ack.confirmed is True
    assert ack.externally_verified is False
    assert ack.provider_transport_count == 0

def test_feedback_attestation_is_user_reported_not_ground_truth(real_idea_service):
    feedback = real_idea_service.record_feedback("sample-1", ratings={"idea_fidelity": 5})
    assert feedback.attested_by == "idea_provider"
    assert feedback.used_as_requirement_ground_truth is False
```

Run RED: `python -m pytest -q tests/test_real_idea_feedback_and_documents.py`.

Expected RED reason: existing document and Handoff contracts are not represented in Real Idea sample review state or final feedback.

Minimum implementation: require exact current PRD/TechDoc versions and snapshot IDs, route acknowledgement through the existing official contract, require explicit acknowledgement for unresolved/zero-source evidence, record safe hash/state/timestamp only, and gate final feedback after all required reviews.

Run GREEN: `python -m pytest -q tests/test_real_idea_feedback_and_documents.py`.

Regression: `python -m pytest -q tests/test_stage_b_phase2_local_techdoc_handoff.py tests/test_v3_schema_migration.py`.

Review: verify acknowledgement is never silently generated, never equated to external verification, and cannot bypass a non-acknowledgement blocker.

Commit: `git add -- app/services/real_idea_evaluation.py app/services/document_workspace.py app/services/handoff.py tests/test_real_idea_feedback_and_documents.py && git commit -m "feat: add real idea document review and attestation gates"`.

## Task 8: Implement Requirement Gold Set and Quality Metrics

Files:

- Create `app/services/real_idea_metrics.py`.
- Create `tests/test_real_idea_quality_metrics.py`.

Interfaces consumed/produced:

- Consume the redacted raw idea, reviewed complete brief, idea-provider decision (`ACCEPT_AS_IS` or `EDIT_AND_ACCEPT`), persisted solution set, selected solution, PRD/Snapshot/TechDoc/Handoff metadata, and human/LLM annotations.
- Produce immutable `RequirementGoldSet`, `RequirementMapping`, `ClaimAnnotation`, `DecisionAnnotation`, and `InheritanceAnnotation` payloads plus metric results.

RED tests:

```python
def test_gold_set_requires_post_review_provider_confirmation(metrics_service):
    with pytest.raises(GoldSetNotFinalError):
        metrics_service.finalize_gold_set("sample-1", source="llm_judge")
    gold = metrics_service.finalize_gold_set("sample-1", source="idea_provider")
    assert {item.confirmed_by for item in gold.items} == {"idea_provider"}

def test_recall_and_zero_source_factuality_metrics(metrics_service):
    metrics = metrics_service.evaluate(sample_id="sample-1")
    assert metrics.brief_critical_requirement_recall == pytest.approx(1.0)
    assert metrics.solution_set_recall >= 0.0
    assert metrics.unsupported_claim_rate == 0.0
    assert metrics.llm_judge_is_not_ground_truth is True
```

Run RED: `python -m pytest -q tests/test_real_idea_quality_metrics.py`.

Expected RED reason: no formal gold-set, requirement mapping, factuality, decision-dimension, contradiction, or semantic inheritance metric contract exists.

Minimum implementation: define critical/secondary requirements from raw idea plus reviewed brief; implement Brief Critical/Overall Requirement Recall, Solution Set/Critical Recall, Selected Solution/Critical Recall, Decision Dimension Coverage, Unsupported Claim Rate, Factual Precision, Solution→PRD, PRD/Snapshot→TechDoc, PRD+TechDoc→Handoff inheritance accuracy, and Critical Contradiction Rate. Store human classifications and LLM-assisted candidates with role metadata. Clearly disclosed hypotheses are not unsupported factual assertions; zero-source verified-fact assertions are a hard failure.

Run GREEN: `python -m pytest -q tests/test_real_idea_quality_metrics.py`.

Regression: `python -m pytest -q tests/test_stage_b_output_contract.py tests/test_stage_b_evaluation.py`.

Review: check that Requirement Recall is not named or calculated as retrieval Recall@K, no generic model accuracy is published, structural ID integrity is a hard invariant, and semantic metrics are diagnostic for Batch 01.

Commit: `git add -- app/services/real_idea_metrics.py tests/test_real_idea_quality_metrics.py && git commit -m "feat: add real idea quality evaluation metrics"`.

## Task 9: Add Batch Finalization and PASS/PARTIAL/FAIL Integrity Gates

Files:

- Modify `app/services/real_idea_evaluation.py`.
- Modify `app/services/real_idea_metrics.py`.
- Create `tests/test_real_idea_batch_state.py`.

Interfaces consumed/produced:

- Consume all sample terminal states, budget reconciliation, artifact bindings, review/feedback status, quality metrics, and integrity annotations.
- Produce `BatchFinalization(status, reasons, sample_results, budget_summary, integrity_summary)` with `PASS`, `PARTIAL`, or `FAIL`.

RED tests:

```python
def test_three_sample_batch_is_partial_when_one_operationally_incomplete(evaluation_service):
    result = evaluation_service.finalize_batch("batch-1")
    assert result.status == "PARTIAL"
    assert result.sample_statuses == {"REAL_IDEA_01": "COMPLETED", "REAL_IDEA_02": "COMPLETED", "REAL_IDEA_03": "OPERATIONAL_INCOMPLETE"}

@pytest.mark.parametrize("violation", ["cross_sample_binding", "wrong_version", "budget_overrun", "search_attempt", "silent_ack", "unsupported_verified_fact"])
def test_integrity_violation_is_fail(evaluation_service, violation):
    evaluation_service.inject_integrity_violation("batch-1", violation)
    assert evaluation_service.finalize_batch("batch-1").status == "FAIL"
```

Run RED: `python -m pytest -q tests/test_real_idea_batch_state.py`.

Expected RED reason: no batch finalization consumes sample outcomes, quality metrics, and hard integrity gates.

Minimum implementation: use the approved state machine, keep Batch 01 metric values descriptive rather than imposing new statistical thresholds, retain approved user-rating PASS gates, and make Provider/Search/budget violations, cross-sample contamination, wrong version/solution binding, silent acknowledgement, unsupported verified-fact assertions, and critical inheritance failures terminal FAIL reasons.

Run GREEN: `python -m pytest -q tests/test_real_idea_batch_state.py`.

Regression: `python -m pytest -q tests/test_real_idea_evaluation_schema.py tests/test_real_idea_budget_and_reservations.py tests/test_real_idea_quality_metrics.py`.

Review: verify PARTIAL cannot be reported as PASS and that a failed finalization does not rewrite historical receipts or release attempted reservations.

Commit: `git add -- app/services/real_idea_evaluation.py app/services/real_idea_metrics.py tests/test_real_idea_batch_state.py && git commit -m "feat: finalize real idea batches with integrity gates"`.

## Task 10: Add CLI/Inspector and Public Boundary Regression

Files:

- Modify `scripts/stage_b_evaluation_inspect.py`.
- Create `tests/test_real_idea_operator.py`.
- Add assertions to `tests/test_stage_b_api_contract.py` only if the existing route test is the repository's established boundary location.

Interfaces consumed/produced:

- Consume `RealIdeaEvaluationService` read-only projections and existing Stage-B CLI parser conventions.
- Produce `real-idea-batch --help`, `real-idea-inspect --help`, and read-only safe metadata output. No public FastAPI route is added.

RED tests:

```python
def test_real_idea_help_has_no_side_effects(cli_runner, isolated_stage_b_db):
    before = isolated_stage_b_db.safe_counts()
    result = cli_runner.invoke(["real-idea-batch", "--help"])
    assert result.exit_code == 0
    assert isolated_stage_b_db.safe_counts() == before
    assert result.provider_dispatches == 0
    assert result.provider_transports == 0

def test_public_project_route_does_not_expose_evaluation_identity(api_client):
    schema = api_client.openapi()["components"]["schemas"]["ProjectCreateRequest"]
    assert "project_origin" not in schema["properties"]
    assert "exclude_from_beta_metrics" not in schema["properties"]
```

Run RED: `python -m pytest -q tests/test_real_idea_operator.py tests/test_stage_b_api_contract.py`.

Expected RED reason: no Real Idea CLI projection exists and the required safe evaluation metadata fields are not exposed by the current inspector.

Minimum implementation: add help-only and read-only inspection commands using actual parser conventions; output operation/sample/project/snapshot/version IDs, counts, hashes, state, reservations, and metric summaries without raw idea text, claims, document bodies, Provider responses, or acknowledgement prose. Preserve the public route schema unchanged.

Run GREEN: `python -m pytest -q tests/test_real_idea_operator.py tests/test_stage_b_api_contract.py`.

Regression: `python -m pytest -q tests/test_stage_b_ai_reference_diagnostic_operator.py tests/test_stage_b_dry_observability.py`.

Review: verify help never creates a batch, reserves budget, confirms a document, or touches `/app/data`.

Commit: `git add -- scripts/stage_b_evaluation_inspect.py tests/test_real_idea_operator.py tests/test_stage_b_api_contract.py && git commit -m "feat: add safe real idea batch inspection"`.

## Task 11: Build Isolated Three-Sample Fake E2E and Failure Matrix

Files:

- Create `tests/test_real_idea_e2e.py`.
- Create `tests/fixtures/real_idea_batch_manifest.json` only if the existing fixture convention accepts static JSON fixtures.

Interfaces consumed/produced:

- Consume the complete `RealIdeaEvaluationService`, fake transport injection at the adapter boundary, temporary SQLite/filesystem roots, and fixed manifest identities `REAL_IDEA_01`, `REAL_IDEA_02`, `REAL_IDEA_03`.
- Produce no persistent Stage B changes and no real Provider/Search calls.

RED tests:

```python
def test_partial_batch_has_two_completed_samples_and_one_operational_incomplete(fake_batch):
    result = fake_batch.run(
        outcomes={"REAL_IDEA_01": "SUCCESS", "REAL_IDEA_02": "SUCCESS", "REAL_IDEA_03": "QUICKSTART_TIMEOUT"}
    )
    assert result.status == "PARTIAL"
    assert result.provider_transport_count == 4
    assert result.search_count == 0

def test_all_success_batch_is_pass(fake_batch):
    assert fake_batch.run_all_success().status == "PASS"

@pytest.mark.parametrize("violation", ["cross_sample_project", "wrong_solution_id", "wrong_prd_version", "budget_overrun", "search", "silent_ack", "unsupported_fact"])
def test_e2e_integrity_violation_fails_closed(fake_batch, violation):
    assert fake_batch.run_with_violation(violation).status == "FAIL"
```

Run RED: `python -m pytest -q tests/test_real_idea_e2e.py`.

Expected RED reason: no complete wrapper, review gates, sample manifest, or isolated fake E2E exists.

Minimum implementation: use three fresh temporary databases and filesystem roots, the same fixed raw idea substitution contract per sample, fake outcomes only at the lowest Provider transport boundary, and no direct SQL/domain-state bypass. Assert sample 03 stops after QuickStart timeout with no Solutions attempt, sample 01 and 02 each consume exactly two transports, selection differs, and every binding/integrity failure is terminal.

Run GREEN: `python -m pytest -q tests/test_real_idea_e2e.py`.

Regression: `python -m pytest -q tests/test_real_idea_*.py tests/test_stage_b_product_flow_phase1a.py tests/test_stage_b_phase2_local_techdoc_handoff.py`.

Review: verify raw ideas are redacted and hashed, each case is isolated, no test connects to `/app/data`, and test assertions distinguish logical generation, dispatch, transport, retry, regeneration, and fallback.

Commit: `git add -- tests/test_real_idea_e2e.py tests/fixtures/real_idea_batch_manifest.json && git commit -m "test: isolated real idea batch end to end"`.

## Task 12: Whole-Branch Review and Verification Gate

Files:

- No new production file is introduced in this task.
- Review all files changed by Tasks 1–11.

Interfaces consumed/produced:

- Consume the complete batch service, migration, tests, CLI, and existing ordinary product contracts.
- Produce a review record with schema version, migration result, test counts, fake E2E PASS/PARTIAL/FAIL results, and explicit zero-call/data-safety evidence.

Run the fresh verification commands:

```powershell
git status --short
python -m pytest -q tests/test_real_idea_evaluation_schema.py tests/test_real_idea_brief_completeness.py tests/test_real_idea_quickstart_one_shot.py tests/test_real_idea_budget_and_reservations.py tests/test_real_idea_batch_state.py tests/test_real_idea_feedback_and_documents.py tests/test_real_idea_quality_metrics.py tests/test_real_idea_operator.py tests/test_real_idea_e2e.py
python -m pytest -q tests/test_stage_b_api_contract.py tests/test_stage_b_evaluation.py tests/test_stage_b_product_flow_phase1a.py tests/test_stage_b_phase2_local_techdoc_handoff.py tests/test_v3_schema_migration.py tests/test_v3_legacy_migration.py
python -m pytest -q
python -m compileall app scripts
node --check tests/stage_b_generation_surface_harness.js
git diff --check
rg -n --hidden --glob '!*.pyc' --glob '!*.sqlite' "(sk-[A-Za-z0-9]{20,}|Authorization: Bearer|RAILWAY_TOKEN|api[_-]?key\s*=)" app scripts tests docs
git status --short
```

The full-suite comparison must record node IDs and signatures for the established twelve baseline failures; the implementation is acceptable only when the candidate adds no new failure and no collection error. The secret scan must distinguish test variable names from secret values and must not print environment variables or credential files.

Review checklist:

- [ ] Only planned files changed; no public route or frontend change exists.
- [ ] The migration is versioned, transactional, idempotent, and compatible with current SQLite initialization; no untracked startup table creation remains.
- [ ] `project_origin='user'` and metrics exclusion are written at birth through the internal wrapper; no origin mutation follows creation.
- [ ] QuickStart and Solutions each have exactly one reserved transport under evaluation policy; ordinary retry/regeneration behavior remains unchanged.
- [ ] Review and acknowledgement gates are explicit, acknowledgement is not verification, and failure recording cannot produce a false success.
- [ ] Requirement Gold Set finalization requires the idea provider; LLM judging is assistive only.
- [ ] Requirement recall is distinct from retrieval Recall@K; Batch 01 reports per-sample descriptive metrics and makes no statistical superiority claim at n=3.
- [ ] Structural binding is hard-fail for wrong project, solution, snapshot, or document version; semantic inheritance and contradiction metrics are recorded separately.
- [ ] The isolated fake E2E produces the approved PARTIAL scenario and an all-success PASS scenario without real calls or persistent data mutation.
- [ ] Historical budget, Provider, Search, ordinary-route, migration, and legacy receipt regressions pass.

Commit after review: `git add -- app scripts tests docs/superpowers/plans/2026-09-14-stage-b-real-idea-evaluation-batch.md; git commit -m "docs: plan stage-b real idea evaluation batch"`.

No command in this plan deploys, pushes, calls a real Provider/Search service, extends budget authorization, or executes the real three-sample batch. The legal endpoint after this plan is implementation authorization, not batch execution.
