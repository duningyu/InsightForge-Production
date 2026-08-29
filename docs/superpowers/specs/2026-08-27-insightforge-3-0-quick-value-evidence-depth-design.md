# InsightForge 3.0 Design Specification

**Design name:** Quick Value → Evidence Depth  
**Date:** 2026-08-27  
**Target release:** 3.0.0  
**Baseline:** InsightForge 2.0.6 runnable package  
**Status:** Design approved in conversation; implementation not started  

## 1. Executive decision

InsightForge 3.0 will stop presenting itself primarily as an evidence-governance workspace and will become a single-path **Idea-to-MVP product design workspace** for AI product job seekers and junior/transitioning product managers.

The product promise is:

> Enter a rough product idea, receive 2–3 genuinely different ways to solve the current user problem, compare trade-offs, choose an MVP path, and obtain a usable Project Snapshot quickly. Add evidence only when the user wants to reduce uncertainty; new evidence must visibly show which claims, decisions, MVP elements, and documents it supports, weakens, contradicts, or leaves unresolved.

The architecture is governed by three invariants:

1. **AI proposes.**
2. **Deterministic code validates and propagates dependencies.**
3. **The user confirms any change to formal project decisions or formal artifacts.**

The current 2.0.6 evidence, versioning, retrieval, document validation, Function Calling, audit, and handoff capabilities remain valuable, but they move underneath the primary user journey rather than defining the journey.

---

## 2. Why this is a major-version redesign

The 2.0.6 baseline is stable: the untouched runnable package passes **99/99 pytest tests**. The problem is therefore not implementation completeness; it is product focus and semantic architecture.

The redesign changes all of the following contracts:

- primary persona;
- first-value flow;
- meaning of the three solution proposals;
- project source of truth;
- evidence-to-decision propagation;
- navigation and state presentation;
- document freshness semantics;
- LLM vs deterministic responsibility boundaries.

Because these are primary-flow and source-of-truth changes, the target version is 3.0.0 rather than a 2.0.x patch.

### 2.1 Baseline defects confirmed in 2.0.6

The current code has several product-semantic mismatches that 3.0 must correct:

1. `GuidedProjectService._build_solution_options()` returns fixed InsightForge product forms (`guided_workflow`, `evidence_first_workspace`, `focused_mvp`) instead of domain-specific ways to solve the user's idea.
2. `_build_idea_plan()` always emits a generic sequence (narrow scenario → clickable flow → trial → review), so the output is methodology rather than an idea-specific implementation path.
3. `guided_sessions` encodes a long audience → problem → constraints → evidence → success → solution flow before first substantive value.
4. `document_claims` are scoped to `document_versions`; they cannot represent project-level assumptions that exist before a PRD or TechDoc.
5. Source ingestion and claim citation exist, but there is no complete source → project claim → decision → artifact impact propagation model.
6. `sources.status` already supports active filtering, but there is no formal archive/restore propagation service that recomputes dependent claims and artifact health.
7. Package naming indicates 2.0.6 while `app/config.py`, `pyproject.toml`, and the historical verification report still identify 2.0.0. This version-truth inconsistency must be corrected as part of the release process.

---

## 3. Primary user and product boundary

### 3.1 Primary persona

**AI product job seekers + junior/transitioning PMs** who:

- already have a rough product idea;
- do not yet have a rigorous product definition;
- need to decide what to build first;
- need a project that is explainable in interviews or a portfolio;
- may later hand the result to AI Coding.

Typical job-to-be-done:

> “I have an idea, but I do not yet know which implementation is most sensible, what the MVP should contain, which assumptions are real versus guessed, what to validate next, or how to turn the result into a defensible PRD and implementation handoff.”

### 3.2 Secondary users

- independent developers who value rapid product definition;
- experienced PMs who want advanced evidence/history inspection.

They do not drive the default IA or onboarding.

### 3.3 Explicit non-targets

3.0 is not:

- an enterprise product portfolio platform;
- a real-time team collaboration suite;
- a general-purpose knowledge base;
- a full autonomous PM Agent;
- a GraphRAG/knowledge-graph product;
- a multi-agent orchestration showcase;
- an approval/permissions platform;
- a production remote MCP platform.

---

## 4. Product principles

1. **First value before governance.** A user should get a meaningful solution comparison before being asked to build a source library or understand evidence taxonomies.
2. **Solve the user's problem, not InsightForge's workflow.** Solution alternatives must differ in how the domain problem is solved.
3. **No forced AI.** If a rule, workflow, or simple statistical baseline is the right first MVP, at least one candidate must remain non-LLM/low-AI.
4. **Unknown is acceptable.** Missing information does not automatically block first-value output; it becomes an explicit validation target.
5. **Evidence changes recommendations visibly, not silently.** Evidence may produce a change proposal but cannot rewrite formal decisions or artifacts without user confirmation.
6. **Project state is a decision state, not a system-state dashboard.** Technical states remain internal.
7. **History is immutable; current usability is mutable.** Old snapshots and document versions are never rewritten after evidence changes.
8. **Evidence support is scoped.** A source can support a claim only within the source's provenance, directness, recency, and sample scope.
9. **No false precision.** Do not emit arbitrary 0–100 evidence scores or exact solution rankings that imply measurement not supported by data.
10. **YAGNI on orchestration.** One orchestrator plus bounded AI services is preferred to multi-agent architectures.

---

## 5. Primary user journey

### 5.1 First-value path

```text
Rough Idea
   ↓
Idea Brief
   ↓
Clarify only if ambiguity is decision-critical
   ↓
2–3 domain-specific Solution Candidates
   ↓
Transparent comparison + recommendation
   ↓
User selects / combines / accepts recommendation
   ↓
Project Snapshot v1
```

No mandatory Canvas, Source Library, RAG screen, Claim Ledger, validation state, approval state, or handoff step may precede Project Snapshot v1.

### 5.2 Evidence-depth path

```text
Project Snapshot v1
   ↓
Critical assumptions / unknowns
   ↓
Add source or evidence
   ↓
Evidence Analysis
   ↓
Project Claim relation validated
   ↓
Decision dependency impact
   ↓
Change Proposal (if material)
   ↓
User accept / reject / defer
   ↓
Project Snapshot v2 (only on accept)
   ↓
Dependent PRD / TechDoc health recomputed
```

### 5.3 Document and handoff path

```text
Current confirmed Snapshot
   ↓
PRD / TechDoc generation
   ↓
Deterministic quality checks + bounded repair
   ↓
User confirms version
   ↓
Implementation Handoff
```

---

## 6. First-value semantics

### 6.1 Idea input

The first screen asks one question:

> “What problem or product idea do you want to work on?”

Optional non-blocking fields:

- target user;
- available data/resources;
- preferred optimization: fastest MVP / lowest cost / strongest product value / strongest portfolio signal.

### 6.2 Idea Brief

`IdeaBrief` is the first structured artifact. It contains:

- original idea;
- target user;
- user problem;
- desired outcome;
- known resources;
- constraints;
- unknowns;
- per-field provenance.

User confirmation means only:

> “InsightForge understood my intended project correctly.”

It must **not** change `model_hypothesis` into validated market evidence.

### 6.3 Clarification policy

A clarification question is allowed only when at least one of the following is true:

1. the target domain/user cannot be inferred at all;
2. two plausible interpretations imply materially different products;
3. the user supplied a hard constraint whose value is required to generate feasible candidates.

Otherwise the system proceeds with explicit unknowns.

Maximum clarification budget for first value: **one blocking clarification turn by default**. Additional clarification requires explicit user choice to refine further.

---

## 7. Solution generation contract

### 7.1 Candidate definition

A solution candidate must include:

- title;
- `mechanism`;
- summary;
- why it fits the current idea;
- user flow;
- MVP pages;
- core features;
- input fields;
- output fields;
- decision logic;
- data requirements;
- technical components;
- implementation complexity;
- two-week implementation plan;
- acceptance cases;
- major risks;
- current unknowns;
- provenance.

### 7.2 Mechanism taxonomy

P0 allowed values:

```text
rule_based
workflow_based
prediction_based
recommendation_based
optimization
search_retrieval
automation
human_in_the_loop
assistant
marketplace
other
```

The taxonomy exists for diversity validation, not for user-facing jargon.

### 7.3 Diversity validator

The solution generator must not be trusted to self-certify diversity. A deterministic validator compares:

- mechanism;
- required data;
- automation level;
- human role;
- core decision logic;
- major implementation dependency.

A pair of candidates is considered materially different only when **at least two** of the following six dimensions differ: mechanism, required-data class, automation level, human role, core decision logic, or major implementation dependency. A three-candidate set passes only when every pair satisfies that rule. Naming, UI packaging, or wording differences never count.

On failure:

1. re-generate once with validator feedback naming the duplicated dimensions;
2. re-run the same deterministic pairwise rule;
3. if exactly two candidates pass, return two rather than fabricate a third;
4. if fewer than two pass, return `SOLUTION_DIVERSITY_FAILED` and ask the user to refine the Idea Brief.

### 7.4 AI-overengineering validator

By default, every candidate set must contain at least one solution whose core mechanism does **not** require an LLM, RAG, or Agent runtime. The only exemption is an explicit user-confirmed `llm_core_required=true` flag recorded in the Idea Brief because the requested user-facing outcome itself depends on open-ended language generation/understanding or semantic retrieval.

If the set violates this rule, return `OVERENGINEERED_SOLUTION_SET` and regenerate once with a required non-LLM/low-AI baseline. If the second attempt still violates the rule, fail rather than silently accept the set.

### 7.5 Comparison semantics

Do not compute fake exact total scores.

Compare candidates on transparent dimensions such as:

- problem fit;
- data requirement;
- MVP speed;
- engineering complexity;
- explainability;
- automation potential;
- current evidence sufficiency.

Recommendation language is:

> “best current option to validate under current information,”

not:

> “objectively best solution.”

### 7.6 User decision

User actions:

- adopt recommended candidate;
- select another candidate;
- combine candidates into staged implementation;
- return to refine idea.

The formal decision is stored only after explicit user confirmation.

---

## 8. Project Snapshot contract

`ProjectSnapshot` replaces Canvas as the primary user-facing source of truth.

It must contain:

1. project one-liner;
2. target user;
3. core problem;
4. selected solution and rationale;
5. user flow;
6. MVP scope;
7. inputs / outputs;
8. core decision logic;
9. technical recommendation;
10. two-week implementation plan;
11. top unknowns / risks;
12. evidence status by key claim;
13. next best action.

### 8.1 Versioning

Snapshots are immutable versions.

- accepting a change proposal creates a new snapshot;
- rejecting/defer does not alter the current snapshot;
- historical snapshots retain the exact content and dependency graph that existed when created.

### 8.2 Next Best Action

P0 uses deterministic prioritization of project claims. Priority is based on:

- claim criticality;
- verification status;
- number of confirmed decisions depending on the claim;
- feasibility blockers.

An LLM may rewrite the explanation into natural language but may not choose a lower-priority claim without an explicit rule reason.

---

## 9. Information architecture and page contract

The top-level product navigation is fixed to five user tasks:

1. **Project Snapshot** (`项目成果`)
2. **Solutions** (`方案`)
3. **Evidence** (`证据`)
4. **Documents** (`文档`)
5. **Handoff** (`开发交接`)

Any future feature must fit one of these five or require a separate product decision.

### 9.1 Project Snapshot page

First viewport must answer:

- What are we building?
- Which solution is currently selected?
- What is the MVP?
- What is the largest current uncertainty?
- What should the user do next, and why?

Do not lead with counts of sources, claims, document versions, loop rounds, or system statuses.

Secondary expandable details may expose evidence and history.

### 9.2 Solutions page

Default content:

- Idea Brief summary;
- 2–3 solution cards;
- transparent comparison;
- recommendation and rationale;
- decision history.

Each compact card shows only:

- title;
- mechanism in plain language;
- why it fits;
- MVP difficulty;
- data requirement;
- primary risk.

Detailed implementation content is expandable.

### 9.3 Evidence page

Default tabs:

1. **Key Claims** (`关键判断`)
2. **Impact History** (`影响记录`)
3. **Source Library** (`资料库`)

The default view answers:

> “What should I validate next?”

The RAG/retrieval laboratory and raw claim ledger are not top-level navigation. They remain available under advanced details.

### 9.4 Documents page

PRD and TechDoc live on one page.

User-facing document status is limited to:

- draft;
- checked;
- user confirmed;
- needs review because dependencies changed.

Internal loop states remain backend-only.

“Approve” copy is replaced by **Confirm this version**. Confirmation means the version becomes the current formal version for export/handoff; it does not imply organizational approval.

### 9.5 Handoff page

The page starts with implementation substance:

- MVP in-scope;
- explicit non-scope;
- implementation tasks;
- acceptance cases;
- current confirmed PRD/TechDoc;
- unresolved risks.

Only after that does it show:

- copy for AI Coding;
- export package;
- advanced MCP option.

### 9.6 Responsive behavior

- Desktop: fixed left navigation, main content fluid.
- Narrow desktop/tablet: compact navigation.
- Small viewport: left navigation collapses into a drawer.
- Main content must never become horizontally unreachable because of a fixed sidebar.

---

## 10. Data model

### 10.1 Existing tables retained

Retain:

- `projects`
- `project_canvas`
- `project_canvas_versions`
- `sources`
- `source_chunks`
- `documents`
- `document_versions`
- `generation_runs`
- `validation_issues`
- `project_decisions`
- `retrieval_runs`
- `retrieval_hits`
- `document_claims`
- `claim_evidence_links`
- `handoff_runs`
- `audit_events`

Legacy-only after migration:

- `guided_sessions`
- `guided_messages`

They remain readable for historical projects but are not written by the 3.0 quick-start flow.

### 10.2 `projects` changes

Add:

```text
current_snapshot_id TEXT NULL
```

`projects.status` remains lifecycle-oriented (`active`, `trashed`) and is not overloaded with UX progress state.

### 10.3 `idea_briefs`

```text
id TEXT PRIMARY KEY
project_id TEXT NOT NULL
version INTEGER NOT NULL
original_idea TEXT NOT NULL
target_user TEXT NOT NULL
problem TEXT NOT NULL
desired_outcome TEXT NOT NULL
known_resources_json TEXT NOT NULL
constraints_json TEXT NOT NULL
unknowns_json TEXT NOT NULL
provenance_json TEXT NOT NULL
confirmation_status TEXT NOT NULL
created_at TEXT NOT NULL
confirmed_at TEXT
supersedes_id TEXT
UNIQUE(project_id, version)
```

Allowed confirmation states:

```text
inferred
confirmed
superseded
```

### 10.4 `solution_runs`

```text
id TEXT PRIMARY KEY
project_id TEXT NOT NULL
idea_brief_id TEXT NOT NULL
provider TEXT NOT NULL
model TEXT NOT NULL
prompt_version TEXT NOT NULL
schema_version TEXT NOT NULL
generator_version TEXT NOT NULL
input_sha256 TEXT NOT NULL
output_sha256 TEXT
status TEXT NOT NULL
created_at TEXT NOT NULL
```

### 10.5 `solution_candidates`

```text
id TEXT PRIMARY KEY
run_id TEXT NOT NULL
project_id TEXT NOT NULL
title TEXT NOT NULL
mechanism TEXT NOT NULL
summary TEXT NOT NULL
why_fit TEXT NOT NULL
user_flow_json TEXT NOT NULL
mvp_pages_json TEXT NOT NULL
features_json TEXT NOT NULL
inputs_json TEXT NOT NULL
outputs_json TEXT NOT NULL
decision_logic_json TEXT NOT NULL
data_requirements_json TEXT NOT NULL
technical_components_json TEXT NOT NULL
implementation_plan_json TEXT NOT NULL
acceptance_cases_json TEXT NOT NULL
risks_json TEXT NOT NULL
unknowns_json TEXT NOT NULL
complexity TEXT NOT NULL
provenance TEXT NOT NULL
created_at TEXT NOT NULL
```

### 10.6 `project_decisions` additions

Retain the existing table and add:

```text
decision_key TEXT
decision_version INTEGER
decision_payload_json TEXT NOT NULL DEFAULT '{}'
supersedes_decision_id TEXT
confirmed_by TEXT
```

Formal solution selection uses:

```text
decision_type = 'solution_selection'
status = 'confirmed'
```

Changes create new decision rows; they never overwrite confirmed history.

### 10.7 `project_claims`

```text
id TEXT PRIMARY KEY
project_id TEXT NOT NULL
claim_type TEXT NOT NULL
statement TEXT NOT NULL
provenance TEXT NOT NULL
verification_status TEXT NOT NULL
criticality TEXT NOT NULL
scope_note TEXT NOT NULL DEFAULT ''
status TEXT NOT NULL DEFAULT 'active'
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
supersedes_claim_id TEXT
```

P0 claim types:

```text
target_user
user_problem
behavior
value
feasibility
```

P0 verification states:

```text
unverified
limited_support
supported
conflict
contradicted
stale
```

`provenance` and `verification_status` are independent fields.

### 10.8 `project_claim_evidence_links`

```text
claim_id TEXT NOT NULL
source_id TEXT NOT NULL
chunk_id TEXT NOT NULL
relation TEXT NOT NULL
directness TEXT NOT NULL
scope_fit TEXT NOT NULL
recency_state TEXT NOT NULL
retrieval_run_id TEXT
analysis_version TEXT NOT NULL
active INTEGER NOT NULL DEFAULT 1
created_at TEXT NOT NULL
PRIMARY KEY(claim_id, chunk_id, relation)
```

P0 relations:

```text
supports
contradicts
contextualizes
```

Irrelevant candidates remain analysis trace only and do not become formal evidence links.

### 10.9 `decision_claim_links`

```text
decision_id TEXT NOT NULL
claim_id TEXT NOT NULL
role TEXT NOT NULL
created_at TEXT NOT NULL
PRIMARY KEY(decision_id, claim_id, role)
```

Allowed roles:

```text
supports
blocks
assumption
```

### 10.10 `project_snapshots`

```text
id TEXT PRIMARY KEY
project_id TEXT NOT NULL
version INTEGER NOT NULL
idea_brief_id TEXT NOT NULL
decision_id TEXT NOT NULL
title TEXT NOT NULL
one_liner TEXT NOT NULL
target_user_json TEXT NOT NULL
problem_json TEXT NOT NULL
solution_json TEXT NOT NULL
mvp_json TEXT NOT NULL
user_flow_json TEXT NOT NULL
inputs_json TEXT NOT NULL
outputs_json TEXT NOT NULL
technical_plan_json TEXT NOT NULL
unknowns_json TEXT NOT NULL
next_action_json TEXT NOT NULL
snapshot_origin TEXT NOT NULL
created_at TEXT NOT NULL
confirmed_at TEXT NOT NULL
created_by TEXT NOT NULL
supersedes_snapshot_id TEXT
content_sha256 TEXT NOT NULL
UNIQUE(project_id, version)
```

`snapshot_origin` values:

```text
quick_value_flow
change_proposal
legacy_migration
```

### 10.11 Snapshot relation tables

```text
snapshot_claim_links(snapshot_id, claim_id, role)
snapshot_decision_links(snapshot_id, decision_id, role)
```

These prevent all semantics from disappearing into a large JSON blob.

### 10.12 `change_proposals`

```text
id TEXT PRIMARY KEY
project_id TEXT NOT NULL
trigger_source_id TEXT
from_snapshot_id TEXT NOT NULL
proposal_type TEXT NOT NULL
summary TEXT NOT NULL
reason TEXT NOT NULL
affected_claims_json TEXT NOT NULL
affected_decisions_json TEXT NOT NULL
suggested_changes_json TEXT NOT NULL
status TEXT NOT NULL
created_at TEXT NOT NULL
decided_at TEXT
decided_by TEXT
```

Allowed statuses:

```text
open
accepted
rejected
deferred
```

Only `accepted` can create a new formal snapshot.

### 10.13 `artifact_dependencies`

```text
artifact_type TEXT NOT NULL
artifact_id TEXT NOT NULL
dependency_type TEXT NOT NULL
dependency_id TEXT NOT NULL
dependency_version TEXT
created_at TEXT NOT NULL
PRIMARY KEY(artifact_type, artifact_id, dependency_type, dependency_id)
```

### 10.14 `artifact_health`

```text
artifact_type TEXT NOT NULL
artifact_id TEXT NOT NULL
health_status TEXT NOT NULL
reason TEXT NOT NULL
trigger_source_id TEXT
updated_at TEXT NOT NULL
PRIMARY KEY(artifact_type, artifact_id)
```

P0 health statuses:

```text
current
needs_review
stale_evidence
superseded
```

Health status never rewrites historical artifact content.

---

## 11. Canvas compatibility strategy

Canvas remains in the database because the current document pipeline and historical projects depend on it.

For new 3.0 projects:

```text
Confirmed Project Snapshot
        ↓ deterministic projection
Canvas / Canvas Version
        ↓
existing document generation compatibility
```

The projection is deterministic and uses this exact mapping:

- `snapshot.target_user_json.primary` → `Canvas.target_users`;
- `snapshot.problem_json.statement` → `Canvas.problem`;
- `snapshot.mvp_json.outcomes[]` → `Canvas.goals`;
- `snapshot.solution_json.explicit_non_goals[]` → `Canvas.non_goals`;
- `snapshot.mvp_json.acceptance_criteria[]` → `Canvas.success_metrics`;
- `snapshot.unknowns_json[]` plus `snapshot.technical_plan_json.constraints[]` → `Canvas.constraints`.

If a required source field is absent, the projection writes an explicit empty list/string according to the existing Canvas schema; it does not invent content.

The default 3.0 UI does not expose direct Canvas editing. The existing `PUT /api/projects/{project_id}/canvas` endpoint remains available as an advanced compatibility API for 3.0 only. A direct Canvas write must mark the current Snapshot `needs_review` and create a `snapshot_canvas_reconciliation` Change Proposal; it may not silently diverge from the Snapshot.

---

## 12. Evidence Impact Engine

### 12.1 Core relation model

```text
SOURCE
  ↓
PROJECT CLAIM
  ↓
DECISION
  ↓
SNAPSHOT / PRD / TECHDOC / HANDOFF
```

The key product question is not only “what source was cited?” but:

> “What did this source change in the current product decision?”

### 12.2 Source-to-claim analysis

The Evidence Analyzer receives:

- one project claim;
- project-scoped retrieved chunks.

It may propose:

- supports;
- contradicts;
- contextualizes.

Every proposed relation must include:

- `claim_id`;
- `source_id`;
- `chunk_id`;
- exact `evidence_span`;
- reason.

### 12.3 Deterministic validation gates

A proposed relation is persisted only if all gates pass:

1. source belongs to the same project;
2. source status is active;
3. chunk belongs to the source and project;
4. evidence span exists exactly in the stored chunk text after the defined normalization policy;
5. source type is allowed to support the claim type;
6. no conflicting project scope or archived dependency exists.

Fail closed on any gate.

### 12.4 Source-type × claim-type policy

P0 policy is qualitative, not a numeric truth score.

| Source type | Target/user problem/value claims | Feasibility claims | Product effect |
| --- | --- | --- | --- |
| `real_user_research` | admissible within sample scope | limited unless it directly contains technical facts | may support/contradict |
| `public_source` | contextual/limited unless directly scoped | contextual/limited | may support within explicit scope |
| `user_input` | project-owner assertion, not market validation | project constraint/input | may define project intent, not external truth |
| `model_hypothesis` | not evidence | not evidence | creates/updates hypotheses only |
| `implementation_evidence` | cannot validate user need/value | admissible for implementation feasibility/status | may support feasibility |
| `simulated_research` | demo-only | demo-only | never upgrades real-world validation state |

A supported claim must retain `scope_note`; support is never automatically generalized to a market-wide fact.

### 12.5 Claim status recomputation

P0 recomputation is rule-driven. Count independent sources, not chunks from the same source.

- `unverified`: zero active admissible support links and zero active admissible contradiction links, and the claim has never previously had active support.
- `limited_support`: at least one active admissible support link, but either (a) support comes from only one independent source, or (b) all support is indirect/contextual; and there is no active direct contradiction.
- `supported`: at least two independent active sources provide direct admissible support, all supporting links carry an explicit `scope_note`, and there is no active direct contradiction. This means “supported within the recorded evidence scope,” not “market truth.”
- `conflict`: at least one independent active source provides direct admissible support and at least one different independent active source provides direct admissible contradiction.
- `contradicted`: at least one active direct admissible contradiction exists and no active direct admissible support remains.
- `stale`: the claim previously had active admissible support, all such support became inactive because of source archive/invalidation, and no active contradiction is present. If active support remains after an archive, recompute to `limited_support` or `supported` instead of `stale`.

These are transparent state rules, not probability scores. Changing them later requires a separate evaluation and migration decision.

### 12.6 Impact propagation

Dependency traversal is deterministic:

```text
claim status changed
↓
query decision_claim_links
↓
identify affected confirmed decisions
↓
query snapshot/document dependencies
↓
recompute artifact health
↓
material change? → create change proposal
```

LLM involvement is limited to natural-language explanation and proposed wording. It does not decide dependency existence.

### 12.7 Material-change rule

Create a change proposal when at least one of these is true:

- a `critical` claim used as a decision assumption changes to conflict/contradicted/stale;
- a previously unverified critical feasibility blocker becomes supported or contradicted;
- the currently selected solution's core `user_problem` or `value` claim changes from `supported/limited_support` to `conflict/contradicted/stale`, or from `unverified` to `contradicted`;
- an artifact depends on a claim that loses admissible supporting evidence.

Do not create a change proposal for every low-value contextual source.

---

## 13. Source archive / restore semantics

P0 adds explicit APIs and service operations:

```text
POST /api/projects/{project_id}/sources/{source_id}/archive
POST /api/projects/{project_id}/sources/{source_id}/restore
```

Archive flow:

```text
source.status = archived
↓
linked project_claim_evidence_links.active = 0
↓
claim status recompute
↓
decision dependency impact
↓
artifact health recompute
↓
change proposal if material
```

Restore repeats validation before reactivating evidence links; links are not blindly re-enabled if source/chunk integrity has changed.

Historical Snapshot/PRD/TechDoc content is never altered.

---

## 14. Document semantics

### 14.1 Input source of truth

New generation inputs are:

```text
Current confirmed Snapshot
+ Project Claims
+ admissible active Evidence
+ Canvas compatibility projection
```

The current document generator and bounded validation Loop can be retained where compatible.

### 14.2 Document health

A document can remain historically confirmed while becoming unsuitable as the current project artifact.

Example:

```text
PRD v3
historical confirmation = true
artifact_health = stale_evidence
```

The UI must show:

> “This was the confirmed version at the time, but evidence used by sections X/Y has changed.”

It must not rewrite PRD v3.

### 14.3 User confirmation gate

UI wording changes from organizational “approval” to:

> **Confirm this version**

Backend may preserve existing approval fields for compatibility, but product copy and claim boundary must reflect single-user explicit confirmation unless real multi-role approval is implemented later.

---

## 15. AI architecture

3.0 uses **one application orchestrator + bounded AI services**.

### 15.1 Idea Interpreter

Input:

- raw idea;
- optional target user;
- optional resources/constraints/preferences.

Output:

- strict `IdeaBrief` schema;
- explicit unknowns;
- clarification-needed boolean and one blocking question at most.

It has no direct write permission to formal project decisions.

### 15.2 Solution Designer

Input:

- confirmed IdeaBrief.

Output:

- 2–3 structured solution candidates.

Mandatory post-processing:

- schema validator;
- solution completeness validator;
- diversity validator;
- AI-overengineering validator.

### 15.3 Evidence Analyzer

Input:

- project claim;
- project-scoped retrieved chunks.

Output:

- relation proposal with exact evidence span.

It cannot modify claims, decisions, snapshots, or documents directly.

### 15.4 Impact Resolver

Deterministic responsibilities:

- traverse claim → decision → artifact dependencies;
- recompute artifact health;
- decide whether material-change rule is triggered.

LLM responsibility:

- explain the impact in user language;
- suggest wording changes for a change proposal.

### 15.5 Document Composer

Input:

- current confirmed Snapshot;
- project claims;
- admissible evidence;
- compatibility Canvas.

Output:

- PRD or TechDoc draft with existing citation and validation controls.

### 15.6 Next Best Action

Not implemented as an Agent. Deterministic claim prioritization selects the target; LLM may render the recommendation naturally.

---

## 16. Runtime modes

The product must not silently represent deterministic fixtures as equivalent to semantic AI behavior.

### 16.1 `llm_structured`

Intended for actual user evaluation.

Uses an LLM for:

- Idea interpretation;
- domain-specific solution generation;
- evidence relation proposal;
- human-readable impact explanation;
- optional document composition.

All structured outputs are schema-validated and pass deterministic gates.

### 16.2 `deterministic_demo`

Intended for:

- CI;
- tests;
- offline demo;
- no-API-key operation;
- fixed golden fixtures.

The UI must disclose that semantic output quality is demo-mode and must not be treated as evidence that a real model understood arbitrary ideas.

Fallback from `llm_structured` to `deterministic_demo` must be explicit in response metadata and UI; no silent mode switch.

---

## 17. AI run trace and reproducibility

For every important AI run persist:

```text
provider
model
prompt_version
schema_version
generator/analyzer version
input_sha256
output_sha256
latency_ms
status
runtime_mode
created_at
```

Do not store or expose private model chain-of-thought. Store only inputs required for reproducibility, structured outputs, citations, validation results, and user-visible rationale.

---

## 18. Function Calling and authorization

Function Calling remains an application control-plane feature, not a user-facing selling point.

### 18.1 L0 read

- `get_current_snapshot`
- `get_project_claims`
- `retrieve_project_evidence`
- `get_solution_candidates`
- `get_document_version`

### 18.2 L1 proposal

- `create_solution_proposal`
- `create_evidence_relation_proposal`
- `create_change_proposal`
- `create_document_draft`

### 18.3 L2 explicit human gate

- `confirm_solution_decision`
- `accept_change_proposal`
- `confirm_document_version`

The model adapter must never be able to self-assert `human_confirmed=true`.

### 18.4 L3 absent from model registry

- project deletion;
- source permanent deletion;
- external publication;
- overwrite confirmed artifact;
- autonomous deployment.

---

## 19. MCP boundary

MCP remains an advanced handoff interface only.

P0 MCP resources are exactly:

- `insightforge://projects/{project_id}/snapshot/current`;
- `insightforge://projects/{project_id}/documents/prd/current`;
- `insightforge://projects/{project_id}/documents/techdoc/current`;
- `insightforge://projects/{project_id}/mvp-scope`;
- `insightforge://projects/{project_id}/unresolved-risks`.

P0 MCP tools are exactly:

- `get_current_project_context`;
- `build_handoff_manifest`.

Binary ZIP export remains HTTP/UI controlled and is not a model-triggered MCP write tool.

Do not implement in 3.0 P0:

- remote MCP OAuth;
- enterprise tenant authorization;
- MCP marketplace publishing;
- multi-client write synchronization.

A remote MCP initiative requires a real second-client need and a separate design.

---

## 20. API contract

### 20.1 Quick start

```http
POST /api/projects/quick-start
```

Request:

```json
{
  "idea": "I want to help small convenience stores reduce stock-outs",
  "target_user": null,
  "resources": [],
  "priority": "fast_mvp"
}
```

Response:

```json
{
  "project_id": "...",
  "idea_brief": {"...": "..."},
  "clarification_required": false,
  "clarification_question": null,
  "runtime_mode": "llm_structured"
}
```

### 20.2 Idea Brief

```text
GET  /api/projects/{project_id}/idea-brief
POST /api/projects/{project_id}/idea-brief/confirm
POST /api/projects/{project_id}/idea-brief/refine
```

### 20.3 Solutions

```text
POST /api/projects/{project_id}/solutions/generate
GET  /api/projects/{project_id}/solutions
POST /api/projects/{project_id}/solutions/select
```

Selection request must include explicit `human_confirmed=true` from UI/app host.

### 20.4 Snapshot

```text
GET /api/projects/{project_id}/snapshot
GET /api/projects/{project_id}/snapshots
GET /api/project-snapshots/{snapshot_id}
```

No generic “update snapshot” endpoint in P0. Formal changes occur only through initial selection or accepted change proposals.

### 20.5 Project claims and evidence

```text
GET  /api/projects/{project_id}/claims
GET  /api/projects/{project_id}/claims/{claim_id}
POST /api/projects/{project_id}/evidence/analyze
GET  /api/projects/{project_id}/evidence/impact
```

Existing source upload endpoints remain compatible.

### 20.6 Source lifecycle

```text
POST /api/projects/{project_id}/sources/{source_id}/archive
POST /api/projects/{project_id}/sources/{source_id}/restore
```

Permanent delete remains outside model tools and requires a separate explicit UI action with dependency warning.

### 20.7 Change proposals

```text
GET  /api/projects/{project_id}/change-proposals
POST /api/change-proposals/{proposal_id}/accept
POST /api/change-proposals/{proposal_id}/reject
POST /api/change-proposals/{proposal_id}/defer
```

Accept requires user confirmation and creates a new snapshot transactionally.

### 20.8 Documents

All existing 2.0.6 generation/read/validate/export endpoints remain available in 3.0 P0 for backward compatibility. Add the following preferred 3.0 endpoints/aliases:

```text
POST /api/projects/{project_id}/documents/generate
POST /api/document-versions/{version_id}/confirm
```

Legacy `POST /api/documents/{version_id}/approve` remains functional for 3.0 as a deprecated alias of `/confirm`; it must execute the same user-confirmation gate and audit action.

### 20.9 Handoff

Keep the existing handoff endpoints and add health validation. P0 handoff readiness requires all three current formal artifacts: a confirmed healthy Snapshot, a confirmed healthy PRD, and a confirmed healthy TechDoc.

Readiness fails closed when any of the following is true:

- no current confirmed Snapshot exists;
- current Snapshot health is `needs_review`, `stale_evidence`, or `superseded`;
- current confirmed PRD is missing or unhealthy;
- current confirmed TechDoc is missing or unhealthy;
- any required current artifact depends on archived evidence and no replacement dependency has been confirmed.

---

## 21. Derived user-facing project state

Do not persist a large project workflow enum. Derive one of three UX states:

### `exploring` (`探索中`)

True when no current confirmed snapshot exists or critical claims remain unresolved without making existing artifacts invalid.

### `executable` (`可执行`)

True when:

- a current confirmed snapshot exists;
- selected MVP is defined;
- no material unresolved proposal blocks the selected solution;
- current formal artifacts needed for the user's next step are healthy.

### `reconfirm_required` (`需要重新确认`)

True when:

- an open material change proposal affects the current decision; or
- current Snapshot/document health is `needs_review` / `stale_evidence` for a critical dependency.

This state is presentation-only and computed from object states.

---

## 22. Migration from 2.0.6

Migration is additive and idempotent.

### 22.1 Phase A — schema additions

Add all 3.0 tables/columns without deleting 2.0.6 tables.

Every migration must be rerunnable against:

- a fresh database;
- the 2.0.6 seeded database;
- a database containing existing custom projects/documents.

### 22.2 Phase B — legacy project snapshot

For an existing project that has no 3.0 Snapshot:

1. read latest Canvas;
2. read latest selected `project_decisions` entry if present;
3. read current PRD/TechDoc versions;
4. create `ProjectSnapshot` with `snapshot_origin='legacy_migration'`;
5. generate project claims only where semantics are explicit; do not infer unsupported market validation from historical document prose;
6. mark uncertain migrated fields as `user_input` or `model_hypothesis` according to traceable origin;
7. do not invent evidence links absent from 2.0.6 trace data.

### 22.3 Phase C — guided flow retirement

- new projects do not write `guided_sessions` or `guided_messages`;
- new projects do not create a guided session; `GET /api/projects/{project_id}/guide` returns 404 when no legacy session exists;
- all existing guide write endpoints (`respond`, `apply`, `reset`, `back`) remain functional only for projects that already have a legacy `guided_sessions` row, are marked deprecated, and are not called by the 3.0 UI;
- this compatibility behavior lasts for the 3.0 release line only;
- new UI does not expose the old Guided Mode/Advanced Workspace dual-mode concept.

### 22.4 Phase D — Canvas projection

When a new Snapshot is confirmed, create/update the compatibility Canvas through one deterministic projection service and normal Canvas versioning.

### 22.5 Phase E — version truth

Before 3.0 release, synchronize:

- package directory/release name;
- `Settings.app_version`;
- `INSIGHTFORGE_APP_VERSION` default;
- `pyproject.toml` version;
- README version references;
- verification report version;
- static asset cache version.

A release test must fail when these values disagree.

---

## 23. Backward compatibility

P0 compatibility guarantees:

- existing project/source/document records remain readable;
- current source IDs/chunk IDs are preserved;
- historical document claims remain untouched;
- approved historical document content remains immutable;
- current retrieval runs remain inspectable;
- current handoff artifacts remain historical evidence but do not automatically qualify as healthy current handoffs.

No guarantee is made that the old guided UI remains user-facing.

---

## 24. Transaction boundaries

The following operations must be atomic:

### Confirm solution

```text
confirmed decision
+ initial project claims
+ snapshot v1
+ snapshot links
+ projects.current_snapshot_id
+ Canvas projection/version
+ audit event
```

If any write fails, no formal decision/snapshot is created.

### Accept change proposal

```text
proposal accepted
+ superseding decision/claim changes as required
+ snapshot vN+1
+ snapshot links
+ current_snapshot_id update
+ artifact health recompute
+ Canvas projection/version
+ audit event
```

### Archive source

```text
source archived
+ project evidence links deactivated
+ claims recomputed
+ artifact health recomputed
+ change proposal if material
+ audit event
```

---

## 25. Error handling and fail-closed behavior

- Cross-project source/chunk/claim references → 403/422 and no partial write.
- Evidence span not found in stored chunk → relation rejected.
- Source archived during analysis → relation rejected at commit-time revalidation.
- LLM returns invalid solution schema → one repair attempt, then explicit failure.
- Solution diversity still fails after one regeneration → return valid smaller candidate set.
- `llm_structured` unavailable → return explicit runtime-mode failure or user-approved demo fallback; never silently switch.
- Change proposal accept on stale `from_snapshot_id` → 409 conflict requiring refresh.
- Source archive causing critical artifact staleness → handoff readiness fails closed.
- Legacy migration cannot determine provenance → preserve field as unresolved/model hypothesis; do not guess.

---

## 26. Security and integrity constraints

1. Every project-scoped query includes `project_id` before semantic ranking.
2. Every citation/evidence link revalidates project/source/chunk ownership.
3. Permanent destructive operations remain outside model tool registry.
4. Audit payloads avoid unnecessary full sensitive source text; store IDs, hashes, relation metadata, and bounded excerpts where required.
5. Source SHA-256 remains immutable per source version.
6. If source content changes, create a new source/version identity rather than mutating evidence under an existing hash.
7. Handoff reads only current confirmed artifacts with acceptable health.

---

## 27. P0 implementation scope

P0 is deliberately narrow.

### Must implement

- quick-start Idea input;
- Idea Brief + confirmation;
- domain-specific 2–3 solution generation;
- deterministic diversity/overengineering/completeness validation;
- solution selection / combination decision;
- Project Snapshot v1;
- five-module IA;
- project-level Claims;
- source → claim relation proposal and deterministic validation;
- Evidence Impact view;
- deterministic claim → decision → artifact propagation;
- Change Proposal accept/reject/defer;
- Snapshot versioning;
- source archive/restore propagation;
- document health / stale evidence semantics;
- Canvas projection compatibility;
- explicit runtime modes;
- migration from 2.0.6;
- version-truth synchronization;
- complete automated regression coverage.

### P0 may reuse

- existing project/source services;
- existing source ingestion/chunking;
- retrieval profiles/runs;
- current document generator and bounded quality loop;
- document versioning/export;
- audit infrastructure;
- handoff package generation where health checks are added;
- existing strict tool registry and local MCP foundations.

---

## 28. P1 scope

P1 requires evidence from user testing or P0 bottlenecks.

Candidates:

- improved embedding retrieval if lexical retrieval misses gold evidence;
- reranking only if embedding adds measurable recall but ordering is insufficient;
- richer Decision History visualization;
- combined/staged solution editing UX;
- snapshot export optimized for portfolio presentation;
- more granular claim scope/sample modeling;
- LLM-assisted claim extraction from large research sources;
- real Codex/IDE client handoff usability testing.

Each P1 feature requires its own success criterion and failure exit condition.

---

## 29. Explicitly forbidden in 3.0 P0

Do not implement merely for architecture prestige:

- multi-agent PM/Research/Critic/Manager system;
- GraphRAG;
- a general knowledge graph UI;
- autonomous decision changes;
- autonomous PRD approval;
- organization-level approval roles;
- remote MCP OAuth;
- enterprise SSO/RBAC;
- arbitrary 0–100 evidence scores;
- AI-based source authority score treated as truth probability;
- automatic claims of “real user validation” from simulated examples;
- solution ranking tuned against post-release test cases without a frozen evaluation protocol.

---

## 30. Evaluation and experiment protocol

Implementation correctness and product effectiveness are separate.

### 30.1 Engineering test suite

All pre-existing 2.0.6 tests must either:

- remain passing when semantics are still valid; or
- be intentionally replaced by a 3.0 contract test with documented reason.

No silent deletion of failing tests to achieve green status.

### 30.2 Golden product cases

Create frozen fixtures covering at least:

1. convenience-store replenishment;
2. non-AI workflow problem where AI overengineering should be rejected;
3. idea with genuine ambiguity requiring one clarification;
4. idea with only two materially different solutions;
5. conflicting real-user evidence;
6. simulated research that must not upgrade validation;
7. implementation evidence supporting feasibility but not user value;
8. source archive causing stale document health;
9. cross-project evidence attack;
10. legacy 2.0.6 migration.

### 30.3 Required P0 engineering metrics

Report:

- existing regression tests passed / total;
- new 3.0 tests passed / total;
- migration idempotency;
- cross-project leakage failures = 0;
- evidence-span validation failures correctly blocked;
- historical artifact mutation failures = 0;
- silent runtime fallback count = 0;
- version-truth mismatch count = 0.

### 30.4 Product-evaluation metrics

These are future user-test metrics, not claims at implementation completion:

- time to first useful Snapshot;
- first-value completion rate;
- % users who can explain why a solution is recommended;
- solution-specificity rating;
- manual edits before Snapshot acceptance;
- evidence-impact comprehension rate;
- unsupported-claim rate;
- source disclosure accuracy;
- % change proposals accepted/rejected/deferred;
- PRD stale-evidence detection accuracy;
- repeat-use intent / second-project completion.

### 30.5 Comparison experiments

Recommended frozen comparisons:

- old guided flow vs new quick-value flow;
- generic three-template solution generation vs domain-specific solution generation;
- no evidence impact vs Evidence Impact Engine;
- direct auto-update vs explicit Change Proposal (usability/safety only; auto-update must not be shipped as default);
- BM25 baseline vs current hybrid retrieval only if evidence recall is a bottleneck.

Do not use post-hoc test feedback to repeatedly change prompts while presenting the same test as frozen evidence.

---

## 31. Test contract

At minimum add test families for:

### Data/migration

- schema additive migration from 2.0.6;
- rerunnable migration;
- legacy snapshot origin;
- legacy evidence not over-inferred;
- foreign-key integrity.

### Idea/Solution

- Idea Brief provenance separation;
- one-question clarification gate;
- candidate schema completeness;
- diversity rejection;
- overengineering rejection;
- two-candidate valid fallback;
- user confirmation required for formal decision.

### Snapshot

- atomic initial snapshot creation;
- immutable version history;
- current snapshot pointer;
- Canvas projection parity;
- next-best-action deterministic selection.

### Evidence

- project scope isolation;
- exact span validation;
- source type × claim type policy;
- simulated evidence cannot upgrade real validation;
- implementation evidence cannot validate user need;
- support/contradiction conflict state;
- archive/restore propagation.

### Change proposal

- material change only;
- accept creates new snapshot;
- reject/defer preserves current snapshot;
- stale proposal returns 409;
- no LLM direct formal update path.

### Artifact health

- historical content unchanged;
- stale evidence marks current health;
- handoff fail-closed on stale critical artifact.

### UI contract

- five top-level modules only;
- no primary RAG/Claim Ledger/Approval navigation;
- first screen accepts one Idea;
- Snapshot page contains one primary next action;
- Source Library is secondary under Evidence;
- responsive sidebar collapses without horizontal content loss;
- runtime mode disclosure visible when demo mode is active.

### Version/release

- app/package/report/static version values agree.

---

## 32. Acceptance criteria for P0

P0 is implementation-complete only when all are true:

1. A fresh user can create a project from one rough idea without completing a Canvas or source form.
2. The system produces at least two materially different domain-specific solution candidates on frozen golden cases.
3. Unless `llm_core_required=true` is explicitly user-confirmed, every solution set contains at least one candidate whose core mechanism does not require LLM/RAG/Agent runtime.
4. User selection creates one immutable Snapshot transactionally.
5. Key Snapshot judgments exist as project-level claims with separate provenance and verification state.
6. A new source can support/contradict/contextualize a claim only through a validated project-scoped chunk/span.
7. A material evidence change produces a Change Proposal rather than silently changing the Snapshot.
8. Accepting the proposal creates a new Snapshot; rejecting/defer does not.
9. Archiving a source propagates to claim/artifact health without mutating history.
10. Current PRD/TechDoc can become `stale_evidence` while historical content remains unchanged.
11. Handoff fails closed when critical current artifacts are unhealthy.
12. Old 2.0.6 projects migrate without data loss or invented validation claims.
13. Runtime mode is never silently changed.
14. Version identity is consistent across application metadata and verification documentation.
15. Regression and 3.0 contract tests are green with explicit test counts reported.

---

## 33. Claim boundary for portfolio/interview use

### Can claim after successful P0 implementation and verification

- Built a runnable Idea-to-MVP workspace that turns a rough idea into domain-specific solution alternatives and an executable Project Snapshot.
- Implemented project-level claim/evidence relationships that show how new evidence can affect product decisions and artifact freshness.
- Implemented explicit Change Proposal and user-confirmation gates so AI recommendations cannot silently rewrite formal project state.
- Preserved immutable Snapshot/document history while separately recomputing current artifact health.
- Implemented strict project-scoped retrieval/evidence validation, deterministic dependency propagation, and bounded AI services.
- Reused FastAPI, SQLite, versioned artifacts, strict Function Calling, and local MCP/handoff infrastructure from the prior runnable system.

### Cannot claim from implementation alone

- validated market demand;
- improved real PM productivity;
- five-minute time-to-value unless measured with users;
- better solution quality than ChatGPT/ChatPRD without a controlled evaluation;
- enterprise-grade collaboration or approval;
- autonomous PM decision-making;
- GraphRAG/knowledge graph innovation;
- production remote MCP;
- real customer retention;
- evidence relation equals objective market truth.

---

## 34. Implementation sequence after spec approval

The implementation plan should be written only after this design is reviewed. It should sequence work to minimize semantic breakage:

1. version-truth and migration foundation;
2. data model and services;
3. Idea Brief / Solution contracts with validators;
4. Snapshot transaction and Canvas projection;
5. new five-module UI shell;
6. project claims and Evidence Impact Engine;
7. source lifecycle propagation;
8. document health integration;
9. handoff health gate;
10. legacy compatibility cleanup;
11. full regression + golden evaluation.

This sequence is a design constraint, not yet an implementation plan.

---

## 35. Final architecture summary

```text
                ┌──────────────────┐
                │    Rough Idea     │
                └────────┬─────────┘
                         ↓
                ┌──────────────────┐
                │    Idea Brief     │
                └────────┬─────────┘
                         ↓
              ┌──────────────────────┐
              │ 2–3 Solution Options │
              └──────────┬───────────┘
                         ↓
                User Confirmation
                         ↓
                ┌──────────────────┐
                │ Project Snapshot │◄─────────────────────────┐
                └────────┬─────────┘                          │
                         ↓                                    │
                 Project Claims                               │
                         ↕                                    │
                       Evidence                               │
                         ↓                                    │
              Deterministic Impact Graph                      │
                         ↓                                    │
                  Change Proposal                             │
                         ↓                                    │
                User accept/reject/defer                      │
                         └──────────── accept ────────────────┘

Current Snapshot
      ↓
PRD / TechDoc
      ↓
quality checks
      ↓
user confirmation
      ↓
healthy Handoff package
```

The product-level distinction is therefore:

> InsightForge does not merely generate a PRD or store citations. It makes product assumptions and decisions explicit, lets evidence change recommendations visibly, and keeps formal project state under deterministic validation and user confirmation.
