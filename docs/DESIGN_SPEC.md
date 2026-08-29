# InsightForge 3.0 Implementation-Aligned Design Contract

**Release:** 3.0.0
**Baseline:** InsightForge 2.0.6 runnable package
**Architecture:** Quick Value → Evidence Depth
**Primary persona:** AI product job seekers and junior/transitioning PMs with a rough Idea but an incomplete product definition.

## Product promise

InsightForge first helps a user decide **what to build**. It then helps the user see **which assumptions are supported, contradicted, stale, or still unknown** before those assumptions flow into formal documents and AI Coding handoff.

```text
Idea → 2–3 domain-specific solutions → Project Snapshot
                                      ↓
                             key assumptions / Claims
                                      ↕
                                  Evidence
                                      ↓
                              Change Proposal
                                      ↓ user confirms
                              Snapshot vN+1
                                      ↓
                              PRD / TechDoc
                                      ↓
                                  Handoff
```

## P0 requirements implemented

### First value

- One Idea is sufficient to start.
- IdeaBrief keeps user input and model hypotheses separate.
- Only decision-critical ambiguity can block with one clarification.
- Solutions are domain mechanisms, not InsightForge workflow variants.
- Two valid materially different solutions are allowed; the system must not pad to three.
- A low-AI/non-LLM baseline is required unless `llm_core_required=true`.
- A formal solution decision and Snapshot require explicit human confirmation.

### Project Snapshot

The Snapshot is the user-side current formal project definition. It includes target user, problem, solution, MVP, user flow, inputs/outputs, technical plan, unknowns, and one next-best action. Every formal change creates a new immutable version.

### Evidence Impact

Project-level Claims have five core types:

- `target_user`
- `user_problem`
- `behavior`
- `value`
- `feasibility`

`provenance` and `verification_status` are independent. Evidence relations are `supports`, `contradicts`, or `contextualizes`; source policy and exact spans are deterministic gates.

Material Claim changes traverse stored Decision and artifact dependencies and may produce a Change Proposal. Evidence never directly rewrites a Snapshot.

### Documents and handoff

PRD/TechDoc generation is current-Snapshot aware. Artifact health is separate from immutable content. Only healthy current validated documents can be confirmed. Handoff fails closed on stale dependencies.

## UI contract

Primary navigation is locked to:

1. 项目成果
2. 方案
3. 证据
4. 文档
5. 开发交接

RAG configuration, raw Canvas, Claim ledger IDs, audit, Function Calling, and MCP are detail/infrastructure surfaces rather than first-level tasks.

## Runtime contract

- `deterministic_demo`: frozen examples for engineering verification only; unsupported semantics fail explicitly.
- `llm_structured`: optional live structured adapter; no silent fallback.
- deterministic code, not the model, owns scope validation, exact evidence spans, dependency traversal, artifact health, state transitions, and write authorization.

## Legacy contract

2.x data is retained additively. A legacy Canvas may be projected into an explicitly labelled `legacy_migration` Snapshot with unverified project Claims. Existing documents, document Claims, source IDs, and source content remain historical records. Migration creates no project evidence links and does not infer market validation.

## Non-goals

Not P0 and not claimed as implemented product value:

- GraphRAG or a generalized product knowledge graph;
- multi-agent PM debate/orchestration;
- enterprise RBAC/SSO/realtime collaboration;
- remote MCP OAuth;
- autonomous formal decision or approval;
- automatic market-truth verification;
- real-user effectiveness or retention claims from engineering tests.

The full approved pre-implementation design is retained separately in the project planning bundle; this file describes the implemented release contract.
