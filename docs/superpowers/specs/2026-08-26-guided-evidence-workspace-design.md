# InsightForge 2.0 Guided Evidence Workspace Design

## 1. Goal

Transform InsightForge 1.1.0 from a technically oriented Evidence Workspace into a novice-first product that helps early product practitioners turn a vague idea into an evidence-backed, reviewable, and executable product project.

The default experience is **Guided Mode**: conversational coaching + a visible step flow + a right-side provenance panel. A top-right switch opens **Advanced Workspace**, which preserves Canvas, source governance, retrieval, documents, audit, Function Calling, and MCP controls.

## 2. Problem statement

The 1.1.0 implementation is runnable and test-covered, but its information architecture assumes that users already understand PRD fields, product constraints, source taxonomies, authority scores, Top-K retrieval, RAG evaluation, and AI coding handoff. That conflicts with the intended audience: AI product job seekers, novice/transitioning PMs, and independent builders with weak product-definition skills.

The redesign addresses five verified product-level issues:

1. The UI exposes system modules instead of user tasks.
2. Blank Canvas fields push the hardest product work back to novices.
3. Source type and authority inputs are unexplained and error-prone.
4. Retrieval and document generation are black boxes without replayable configuration or source provenance.
5. AI coding handoff is a prompt/interface claim rather than a concrete, versioned deliverable.

## 3. Product principles

- **Task language over technical language:** novice mode uses user goals, not BM25, authority, or Loop jargon.
- **One high-value question at a time:** the coach asks a single question, explains why it matters, and offers examples or an “I’m not sure” path.
- **Confirmed / sourced / suggested / unresolved are distinct states:** model suggestions never silently become confirmed requirements or market facts.
- **Trace before trust:** every retrieval, citation, claim, decision, and handoff artifact has a replayable origin.
- **Advanced controls remain available:** technical depth is retained behind an explicit mode switch.
- **Bounded agent behavior:** deterministic state transitions and application-owned tools remain authoritative. An optional LLM may improve wording, but cannot approve, publish, delete, or overwrite approved state.
- **No technology theatre:** LangChain is not added merely as a label. Existing FastAPI services and ToolRegistry remain the control plane; MCP is extended only where it exposes concrete project resources.

## 4. User experience

### 4.1 Guided Mode layout

The default desktop layout has three columns:

1. **Step rail:** Idea → User problem → Evidence → Solution → PRD/TechDoc → AI coding handoff.
2. **Coach workspace:** conversation, one current question, quick choices, examples, and confirmed project summary.
3. **Evidence panel:** source cards, retrieval traces, claim ledger, and links back to original provenance.

Mobile collapses the evidence panel into tabs below the coach.

### 4.2 Advanced Workspace

The mode switch reveals the expert modules:

- Project overview
- Versioned Canvas
- Source library and provenance metadata
- Retrieval laboratory and profile configuration
- Documents, claims, validation, approval, and export
- AI coding handoff readiness and package export
- Audit, tools, and MCP capabilities

### 4.3 Guided flow

1. User creates a project with a rough idea only.
2. The PM Coach restates the idea and asks for the target audience.
3. It asks for the key scenario/problem, constraints, evidence currently available, and success criteria.
4. It proposes three bounded solution directions with benefits, costs, risks, and unknowns.
5. User selects or edits one direction.
6. The system proposes a structured Canvas patch and requires confirmation before saving a new Canvas version.
7. Evidence gaps are shown in the right panel; the user can add sources through novice-friendly source categories.
8. The user generates PRD/TechDoc, sees the retrieval runs and claim ledger, validates, and approves.
9. When both approved artifacts are ready, the user exports a versioned AI coding handoff ZIP with hashes and unresolved boundaries.

## 5. Backend architecture

### 5.1 New bounded PM Coach

`GuidedProjectService` is a deterministic state machine persisted in SQLite. It stores:

- current step
- user-confirmed fields
- AI-suggested fields
- unresolved questions
- proposed solution alternatives
- selected alternative
- message history and trace metadata

It exposes read/respond/apply/reset APIs. `apply` writes a normal Canvas version through `ProjectService`; the coach cannot bypass versioning.

### 5.2 Source guidance and provenance

Sources gain optional provenance fields:

- source URL
- publisher
- published date
- captured date
- authority label and basis
- active/archived status
- metadata JSON

A transparent classifier maps novice source categories to the existing source taxonomy and explains what the source can and cannot support. Users may override the proposal in Advanced Workspace.

### 5.3 Retrieval profiles and trace

Retrieval profiles are centralized and versioned:

- `quick_explore_v1`: Top-K 4
- `balanced_traceable_v1`: Top-K 8 (default)
- `thorough_review_v1`: Top-K 12
- `document_generation_v1`: Top-K 5 per generation query

All profiles use the existing baseline weights (BM25 0.55, TF-IDF cosine 0.30, authority 0.15) and are explicitly labelled `manual_baseline_not_frozen_best`. Every run stores the query, purpose, profile, weights, candidate count, returned hits, scores, actor, and timestamp.

### 5.4 Claim-evidence ledger

Document generation returns both Markdown and structured claims. Each claim is one of:

- `user_confirmed`
- `source_backed`
- `model_suggestion`
- `unresolved`

Source-backed claims must link to valid project-scoped chunks. Model suggestions and unresolved claims must be locally disclosed. Claims and evidence links are persisted and exposed by API. The deterministic generator selects evidence by source type and lexical fit instead of rotating through citations by index.

### 5.5 AI coding handoff

`HandoffService` checks readiness and builds a ZIP only when:

- a Canvas exists;
- an approved, validation-passed PRD exists;
- an approved, validation-passed TechDoc exists;
- the package records unresolved claims rather than hiding them.

The ZIP contains approved documents, approved context, source manifest, claim ledger, retrieval trace, acceptance tests, implementation tasks, `AGENTS.md`, and a SHA-256 manifest.

### 5.6 MCP and tool boundaries

Add read tools/resources for guided state, retrieval trace, claim ledger, and handoff readiness. Add a bounded L1 tool to prepare a handoff manifest, but binary export remains an explicit HTTP/UI action. L2 approval still requires host-owned `human_confirmed=true`; delete/publish/overwrite remain absent.

## 6. Data model additions

- `guided_sessions`
- `guided_messages`
- `project_decisions`
- `retrieval_runs`
- `retrieval_hits`
- `document_claims`
- `claim_evidence_links`
- `handoff_runs`

Existing databases are upgraded through additive, idempotent SQLite migrations. Existing 1.1.0 records remain valid.

## 7. API additions

- `GET /api/projects/{project_id}/guide`
- `POST /api/projects/{project_id}/guide/respond`
- `POST /api/projects/{project_id}/guide/apply`
- `POST /api/projects/{project_id}/guide/reset`
- `GET /api/source-guidance`
- `POST /api/projects/{project_id}/sources/guided`
- `GET /api/retrieval/profiles`
- `GET /api/projects/{project_id}/retrieval-runs`
- `GET /api/retrieval/runs/{run_id}`
- `GET /api/documents/{version_id}/claims`
- `GET /api/projects/{project_id}/handoff/readiness`
- `POST /api/projects/{project_id}/handoff/export`

Existing APIs remain backward compatible.

## 8. Error handling and safety

- Missing project/canvas/document returns 404/422 through existing handlers.
- Invalid guided step transitions are rejected rather than guessed.
- Source classification is returned as a proposal with basis; it is not represented as model certainty.
- Retrieval runs with no lexical signal return an empty trace, not authority-only matches.
- Handoff export fails closed and returns all missing readiness conditions.
- Optional LLM failure falls back to deterministic coaching/generation without changing authorization semantics.

## 9. Testing

Add automated tests for:

- database migration and backward compatibility
- guided state progression, proposal/confirmation separation, and Canvas apply
- source guidance mapping and provenance persistence
- retrieval profile centralization, trace persistence, and project isolation
- claim/source-type alignment and claim API
- handoff readiness, ZIP contents, and SHA-256 manifest
- MCP/tool schema additions and risk levels
- UI static contract for guided default, advanced toggle, evidence panel, and handoff view

All previous 37 tests must continue to pass.

## 10. Claim boundary

The completed version may claim:

- a runnable novice-first Guided Evidence Workspace;
- a deterministic bounded PM Coach with transparent state and tool boundaries;
- replayable retrieval traces and structured claim-evidence links;
- a concrete AI coding handoff ZIP;
- local MCP code exposing new read resources/tools.

It must not claim:

- real market validation from one product-manager feedback session;
- autonomous product management;
- optimal RAG parameters;
- semantic truth verification equivalent to human review;
- production remote MCP, enterprise authorization, or online business impact.
