# Function Calling Boundary — InsightForge 3.0

Function Calling is an application integration mechanism, not the product's primary user value. The application owns schemas, risk levels, authorization, persistence, evidence validation, and human confirmation.

All JSON schemas are strict (`additionalProperties=false`). Model output cannot set a host-owned confirmation flag.

## Risk levels

### L0 — read-only

Examples include:

- `get_current_snapshot`
- `get_project_claims`
- `get_solution_candidates`
- `retrieve_project_evidence`
- retained compatibility reads such as Canvas/document/claim/handoff readiness.

L0 cannot write formal state.

### L1 — proposal/draft

Examples include:

- `create_solution_proposal`
- `create_evidence_relation_proposal`
- `create_change_proposal`
- document draft/validator/export-manifest helpers.

An L1 call may create a proposal or draft but cannot establish a formal product decision.

`create_evidence_relation_proposal` validates a proposed relation; persistence still requires the application's project Claim Evidence path and its deterministic gates.

### L2 — explicit human Gate

- `confirm_solution_decision`
- `accept_change_proposal`
- `confirm_document_version`

`ToolRegistry.execute(..., human_confirmed=False)` rejects L2 calls. The model adapter cannot self-authorize.

## Operations intentionally not registered for autonomous model use

- permanent project/source/document deletion;
- external publishing;
- overwriting a historical Snapshot/document;
- automatic candidate solution confirmation;
- automatic organizational approval;
- bypassing artifact health;
- cross-project retrieval/evidence writes.

## Runtime mode

The registry uses the same `deterministic_demo` or `llm_structured` structured runtime contracts as the REST application. Selecting live mode without valid credentials fails explicitly. Silent fallback is prohibited.

## Audit

Executed tools create `audit_events` with the actor, tool name, risk level, and arguments. Structured semantic runs separately record provider/model/prompt/schema/component versions and input/output hashes through the existing audit stream. Full hidden chain-of-thought is neither required nor stored.
