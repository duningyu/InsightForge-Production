# InsightForge 3.0 Architecture

## 1. Architectural objective

3.0 moves first value ahead of governance. The user-facing source of truth is the current **confirmed Project Snapshot**, while evidence, versioning, retrieval, validators, Function Calling, and MCP operate underneath it.

```text
Idea
  ↓
IdeaBrief
  ↓
SolutionCandidate[2..3]
  ↓ explicit human decision
ProjectSnapshot vN
  ↓
ProjectClaim ←→ Source/Chunk
  ↓ evidence status change
ImpactResolver
  ↓
ChangeProposal
  ↓ explicit human confirmation
ProjectSnapshot vN+1
  ↓
PRD / TechDoc
  ↓
Healthy confirmed Handoff
```

Three invariants govern the implementation:

1. **AI proposes.**
2. **Deterministic code validates scope, spans, states, and dependencies.**
3. **Human confirmation owns formal solution decisions, Change Proposal acceptance, and document confirmation.**

## 2. Five-module IA

```text
项目成果       方案          证据          文档          开发交接
Snapshot      Solutions     Claims/Impact PRD/TechDoc   MVP/Handoff
```

There is no primary Guided/Advanced mode switch in 3.0. Legacy Guided endpoints are retained only for pre-existing Guided sessions and are marked deprecated.

## 3. Domain services

```text
FastAPI / Browser / Function Calling / local MCP
                  │
                  ├── QuickStartService
                  ├── SolutionDesignService
                  ├── SnapshotService + DecisionService
                  ├── ProjectClaimService
                  ├── SourceService + RetrievalService
                  ├── ImpactResolver + ChangeProposalService
                  ├── DocumentLoop + DocumentVersionService
                  ├── ArtifactHealthService
                  └── HandoffService
                              │
                         SQLite 3.0 schema
```

### Structured AI runtime

`DeterministicDemoRuntime` and `OpenAIStructuredRuntime` share strict Pydantic contracts for IdeaBrief, Solution candidates, and evidence-relation proposals. The runtime never owns formal writes.

### Deterministic validators

- Solution diversity: every pair differs on at least two material dimensions.
- Overengineering: when `llm_core_required=false`, at least one core candidate must not require LLM/RAG/Agent runtime.
- Evidence: project/source/chunk scope, source active state, source-type × Claim-type policy, exact span, recency, and retrieval trace.
- Change propagation: stored `decision_claim_links` and `artifact_dependencies`, not an LLM reconstruction of the project.

## 4. Data model

### New 3.0 entities

- `idea_briefs`
- `solution_runs`
- `solution_candidates`
- `project_claims`
- `project_claim_evidence_links`
- `decision_claim_links`
- `project_snapshots`
- `snapshot_claim_links`
- `snapshot_decision_links`
- `change_proposals`
- `artifact_dependencies`
- `artifact_health`

`projects.current_snapshot_id` points at the current formal Snapshot. `project_decisions` is extended additively with version/supersession metadata.

### Legacy entities retained

Legacy Canvas, Guided session, document, document Claim, retrieval, source, audit, and handoff tables remain. No destructive migration is used.

## 5. Snapshot and Canvas

For 3.0 projects:

```text
Confirmed ProjectSnapshot
       ↓ deterministic projection
legacy Canvas compatibility record
       ↓
existing document generator/validator pipeline
```

Direct Canvas editing is blocked for Snapshot-managed projects. Accepted compatibility edits must go through reconciliation and a new Snapshot; user confirmation of an edit does not upgrade its market-validation status.

## 6. Project Claims versus document Claims

`project_claims` exist before documents and model product assumptions such as target user, user problem, value, and feasibility.

`document_claims` remain immutable document-version ledger entries used to audit what a generated PRD/TechDoc said and cited.

They are intentionally separate. Historical generated prose is never promoted into project truth during migration.

## 7. Evidence state

Project Claim status is deterministic:

- `unverified`
- `limited_support`
- `supported`
- `conflict`
- `contradicted`
- `stale`

`provenance` is independent from status. `user_input` means the project owner supplied the statement; it does not mean the market has verified it.

Evidence source policy is fail-closed. For example:

- `real_user_research` may support product/user Claims, with sample scope retained;
- `simulated_research` cannot upgrade project Claim validation;
- `implementation_evidence` can support `feasibility` only;
- `model_hypothesis` and `user_input` are not self-validating evidence.

## 8. Artifact health and immutability

Historical artifact content is immutable. Current usability is stored separately in `artifact_health`:

- `current`
- `needs_review`
- `stale_evidence`
- `superseded`

Source archive/restore is transactional. Archive deactivates dependent project evidence links, recomputes Claims, propagates health, and creates a material Change Proposal when policy requires it. Restore revalidates source identity, scope, span, and policy before reactivating an old link.

## 9. Documents

3.0 document generation requires a current Snapshot. Every new document version stores dependencies on:

- current Project Snapshot;
- active project Claims;
- cited source IDs.

Only `validation_status=passed`, active, `health_status=current` documents can be confirmed. The database still uses the legacy value `status='approved'`; externally the action is **Confirm this version**, not organizational approval.

## 10. Handoff

3.0 readiness fails closed unless the current Snapshot, confirmed PRD, and confirmed TechDoc are all healthy. The package includes executable MVP material before optional MCP integration details.

## 11. Legacy migration

On application startup, `LegacyMigrationService` adds an explicitly labelled `legacy_migration` Snapshot only when traceable legacy Canvas data exists. It preserves old documents/Claims/sources verbatim, creates unverified project Claims from traceable Canvas inputs, and creates **no project evidence links**. Migration is idempotent.

## 12. Explicit non-goals

3.0 does not implement GraphRAG, a general product knowledge graph, multi-agent debate, enterprise RBAC, remote MCP OAuth, automatic organizational approval, autonomous product decisions, or real-time team collaboration.
