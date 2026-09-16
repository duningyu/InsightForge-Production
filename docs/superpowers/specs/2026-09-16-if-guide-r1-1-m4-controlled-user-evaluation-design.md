# IF Guide R1.1 M4 Controlled User Evaluation

Status: design-only specification. This document does not authorize M4 implementation, deployment, participant recruitment, Provider/Search calls, or mutation of Stage B data.

## 1. Purpose and research question

M4 is an exploratory real-user product-validation study. It is not a market-fit claim, a production-readiness certification, or evidence of statistical superiority.

The research question is:

> Does InsightForge stateful guidance help target users move from a vague idea or problem to a valid first action, a testable Build Slice, an executable Prototype Task, and an evidence-backed next Decision more effectively and reliably than simpler alternatives?

The study evaluates the complete user-facing path only to the extent needed by the frozen experiment. It does not expand M3 into M4 automation, commercial rollout, or an analytics platform.

## 2. Participants and privacy

Recruit 8–12 real target users, covering the three purpose strata:

- `LEARNING`
- `PERSONAL_USE`
- `FOR_OTHERS`

Store only an anonymous participant ID, purpose, coarse prior AI familiarity, coarse prior product-building experience, coarse idea/task category, and completion or withdrawal status. Raw contact details, unnecessary transcripts, private files, credentials, and full private artifacts are out of scope for the evaluation ledger. Evidence is represented by safe references, hashes, status, and timestamps.

Participants bring a real idea, problem, or unfinished project. The study records the participant's confirmed purpose, requirements, constraints, non-goals, and fidelity feedback; it does not silently rewrite participant intent into PRD language.

## 3. Conditions

All condition definitions are frozen before execution.

### 3.1 `STATIC_TEMPLATE`

A frozen static action and acceptance template with no adaptive stateful guidance. Provider calls and Search calls are zero.

### 3.2 `GENERAL_AI`

A frozen clear prompt executed by the selected general AI configuration. The freeze record includes prompt version and hash, model/provider identity, output schema, retry policy, timeout, maximum calls, and cost accounting. Any call, retry, timeout, or fallback is recorded per session.

### 3.3 `INSIGHTFORGE_STATEFUL`

The frozen R1.1 path:

`Purpose → First Action → Build Slice → Prototype Task → Submission/Review → Recovery/Decision`.

The freeze record includes source commit, deployment ID, feature flags, M1–M3 rubric/quality versions, migration identity, Provider/Search policy, and the current artifact/version binding rules. The condition reuses project ownership, revision, history/reopen, and the existing `ArtifactQualityEvaluation` equivalent.

## 4. Assignment and task standardization

Use exploratory balanced assignment by purpose as the default. The assignment record contains the rule, assigned condition, purpose stratum, deviations, withdrawals, and incomplete sessions. No participant is post-hoc reassigned to improve an outcome. The study must not be called a randomized controlled trial unless assignment was actually randomized and the analysis is appropriate for that design.

Freeze a time budget, allowed tools, operator/support policy, evidence requirements, completion window, and condition instructions. Classify idea/task complexity coarsely and report it; do not pretend that unrelated user tasks are identical.

## 5. Human-confirmed Requirement Gold Set

Before content-quality scoring, finalize a per-participant Requirement Gold Set from the participant-confirmed purpose and brief review. It contains critical requirements, secondary requirements, constraints, and explicit non-goals. Each item has at least:

`requirement_id`, `participant_id`, `project_id` when a project exists, `canonical_text`, `importance` (`CRITICAL` or `SECONDARY`), `source`, `confirmed_by`, and `revision`.

The participant is the authority for intent, acceptance/edit decisions, and fidelity. An independent human reviewer audits mappings and annotations. LLM assistance may extract candidates or propose matches, but no LLM output is Ground Truth or the sole final evaluator.

## 6. Primary product metrics

Metrics are calculated per participant/session first. Incomplete denominators are reported explicitly rather than silently converted to zero.

### 6.1 First Valid Action Rate

`sessions with a participant-completed, checkable first action within the agreed window / sessions that entered a condition`.

Withdrawn sessions are excluded from the completed numerator and reported separately. An operationally incomplete session remains in the denominator only when it entered the condition and no valid exclusion rule applies.

### 6.2 First Usable Flow Completion Rate

`projects entering Build Slice stage whose agreed minimal flow was completed and passed its acceptance steps / projects entering Build Slice stage`.

Report the overall funnel separately, including projects that never reached Build Slice, so the conditional rate is not mistaken for an end-to-end rate.

### 6.3 Independent Acceptance Rate

`completed acceptance assessments where the participant independently classified pass/fail consistently with the frozen acceptance rubric / completed acceptance assessments attempted by participants`.

Operator-performed checks do not count as independent acceptance. Missing assessment evidence is reported as missing and does not become a pass.

### 6.4 Evidence-backed Decision Rate

`decisions linked to an exact submission, review, check/evidence reference, and rationale / decisions recorded in the condition`.

An unconfirmed recommendation, a user claim without review, or an attachment without a checked evidence reference does not count.

### 6.5 Recovery Rate

`sessions entering BLOCKED, FAIL, or critical UNKNOWN that return to one executable next action / sessions entering BLOCKED, FAIL, or critical UNKNOWN`.

If no qualifying blocker occurs, the metric is `NOT_APPLICABLE`, not an artificial 100%.

## 7. Secondary content-quality metrics

Reuse the existing M1–M3 formulas and quality evidence model; do not create alternate M4 definitions:

- Critical Requirement Recall
- Overall Requirement Recall
- Alignment Precision
- Checkability Coverage
- Acceptance Coverage
- Acceptance Testability
- Unsupported Claim Rate
- Actionability
- Result→Decision Traceability

Each metric stores numerator, denominator, missing/incomplete handling, rubric version, evaluator role, source evidence references, and immutable evaluation revision. `Unsupported Claim Rate` counts factual or execution claims presented as verified without supporting evidence; disclosed hypotheses and user-reported claims are not silently counted as verified facts.

## 8. Optional cross-stage metrics

Only compute these where the corresponding artifact exists naturally:

- Purpose→Action Alignment
- Build Slice scope→Prototype Task inheritance
- Solution→PRD inheritance
- PRD→TechDoc traceability
- Handoff version binding

Do not force PRD, TechDoc, or Handoff generation solely to obtain a metric. Structural identity correctness (project, snapshot, and version IDs) is separate from semantic content quality.

## 9. Operational metrics and accounting

Record elapsed time, time to first valid action, time to first usable flow, user edit count, operator/support minutes, Provider calls, Provider cost, retries, timeouts, severe errors, and recovery attempts. A no-Provider condition records calls and cost as zero, not missing. Provider and Search accounting is per condition and session; duplicate paid dispatch, hidden retry, and unrecorded fallback are integrity failures.

## 10. Human review roles

The participant confirms purpose, requirements/constraints, intent fidelity, usefulness, and user-reported outcomes. An independent reviewer checks requirement mappings, claim classes, checkability, actionability, review accuracy, and decision traceability. For a practical subset, two independent reviewers may annotate the same evidence; retain disagreement and adjudication metadata. LLM-as-Judge can propose candidate extraction or disagreement queues only and cannot be sole Ground Truth.

## 11. Hard gates and success semantics

Freeze integrity gates before observing M4 outcomes. The following are hard failures when applicable:

- cross-account or cross-project leakage greater than zero;
- false `AUTHORIZED_RUN` evidence greater than zero;
- unauthorized external action greater than zero;
- duplicate paid Provider dispatch greater than zero;
- wrong exact version binding greater than zero;
- severe unsupported verified-fact assertion greater than zero where the rubric defines it.

Product metrics are diagnostic for Batch 01. Use a pre-registered modest threshold only when justified by prior evidence; otherwise mark the criterion `BASELINE_ONLY`. Do not invent a universal “95% accuracy” gate. Hard integrity gates and diagnostic quality metrics are reported separately.

## 12. Outcome taxonomy

Each session/project ends in exactly one primary outcome:

- `WITHDRAWN`: participant voluntarily stops;
- `OPERATIONAL_INCOMPLETE`: time/tool/system operation prevents completion;
- `QUALITY_INCOMPLETE`: required evidence or review is insufficient for a quality conclusion;
- `COMPLETED`: frozen completion and evidence requirements are satisfied;
- `INTEGRITY_FAIL`: a hard integrity gate fails.

Incomplete and withdrawn participants are not replaced post-hoc to improve results.

## 13. Freeze and version splits

Before the first session, freeze experiment-spec version, source commit, deployment ID, condition definitions, General AI prompt/model/retry/call cap, InsightForge feature/rubric versions, metric formulas, thresholds, assignment rule, and allowed operator assistance. Any product, prompt, schema, model, rubric, or behavior change creates `experiment_version_split = true`; sessions from different versions are not silently pooled.

## 14. Reporting

Report each participant first, then descriptive aggregates by condition and purpose. Include completion/outcome taxonomy, primary and secondary metrics, failures, edit counts, support time, Provider calls/cost, qualitative comments, missingness, and version splits. With n=8–12, do not claim statistical significance, broad market superiority, or general accuracy. Any comparison is exploratory and bounded by the observed sample and frozen protocol.

## 15. Reuse and implementation boundary

Future implementation must reuse the current project/account isolation, M1–M3 state, `ArtifactQualityEvaluation`/quality service, safe evidence and annotation support where available, P0/P1/P2 boundaries, Provider accounting, and history/reopen. It must not create a second Project system, second Task system, second quality ledger, generalized experimentation platform, analytics warehouse, payment system, CRM, or public-release automation.

The existing M3 distinction remains binding: `CLOSED != FINISH`, `PASS != FINISH`, `PASS != market validation`, `STOP != failure`, `FINISH != deployed`, and `USER_REPORTED != AUTHORIZED_RUN`.

This specification ends at design. The next legal work is review/approval of this spec and the implementation plan, followed by a separately authorized implementation and deployment preparation. No participant, project, artifact, Provider call, Search call, or M4 session is created by this document.
