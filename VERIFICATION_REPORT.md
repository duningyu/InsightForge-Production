# InsightForge 3.0 Verification Report

**Verification date:** 2026-08-27
**Application version:** 3.0.0
**Branch:** `feature/insightforge-3.0`
**Environment:** Linux x86_64, Python 3.13.5, Node.js 22.16.0

## 1. Verified product scope

This report covers the implementation-aligned InsightForge 3.0 P0 product:

- Quick Value first path: rough Idea → structured IdeaBrief → 2–3 domain-specific solution candidates → explicit user selection → immutable Project Snapshot;
- five primary user modules: **项目成果 / 方案 / 证据 / 文档 / 开发交接**;
- project-level Claims with provenance separated from verification state;
- exact source/chunk/span Evidence relationships with fail-closed project scoping;
- Evidence Impact propagation through Claim → Decision → Artifact dependencies;
- material evidence changes create a Change Proposal instead of mutating the current formal project state automatically;
- accepted Change Proposals create a new immutable Snapshot version and preserve historical hashes/content;
- Source archive/restore propagates evidence health atomically;
- Snapshot-aware PRD/TechDoc generation and health status;
- single-user **Confirm this version** Gate rather than organizational approval semantics;
- fail-closed AI Coding handoff when current formal artifacts are missing or unhealthy;
- additive 2.0.6 migration with explicit `legacy_migration` Snapshot origin;
- `deterministic_demo` and `llm_structured` are separate runtimes; deterministic demo is a frozen engineering mode and is not represented as arbitrary semantic-model performance.

## 2. Baseline reference

Before 3.0 implementation, the untouched runnable package was verified as:

```text
2.0.6 untouched = 99 passed
```

The 3.0 branch was developed additively from that baseline; legacy tables and historical artifacts are retained rather than rewritten as 3.0 evidence.

## 3. Automated verification evidence

### 3.1 Full suite before final documentation

A fresh detached full-suite run after Task 15 completed with:

```text
186 passed in 45.60s
exit status 0
```

After adding the release-identity/documentation contract test, the completed release tree was rerun and recorded 187 passing tests (Section 8).

### 3.2 Targeted integrity suite

Command:

```bash
pytest tests/test_v3_schema_migration.py \
  tests/test_v3_snapshot_transaction.py \
  tests/test_v3_project_claim_evidence.py \
  tests/test_v3_change_proposals.py \
  tests/test_v3_source_lifecycle.py \
  tests/test_v3_document_health.py \
  tests/test_v3_handoff_and_tools.py \
  tests/test_v3_legacy_migration.py \
  tests/test_v3_end_to_end.py -q
```

Observed result before final documentation edits:

```text
47 passed in 14.93s
exit status 0
```

### 3.3 Syntax / bytecode verification

Command:

```bash
python -m compileall -q app tests
```

Observed result: exit status `0`.

## 4. Required integrity outcomes

### Migration idempotency

Covered by `tests/test_v3_schema_migration.py` and `tests/test_v3_legacy_migration.py`:

- 2.0.6 schema migration is additive and rerunnable;
- repeated legacy migration does not create additional Snapshots/Claims/Evidence links;
- legacy IDs and historical document/claim content are retained;
- migrated project Claims remain unverified unless supported by actual project-level evidence;
- migration invents **zero** project evidence links.

### Cross-project evidence leakage

Covered by project-level evidence and frozen golden-case tests:

- a source/chunk outside the Claim's project is rejected fail-closed;
- no cross-project `project_claim_evidence_links` row is persisted.

### Silent runtime fallback

Covered by Quick Start / Solution runtime tests:

- unsupported deterministic-demo semantic inputs return an explicit unsupported/runtime error rather than pretending to understand arbitrary Ideas or evidence;
- a requested LLM runtime is not silently replaced by deterministic demo;
- UI copy discloses deterministic demo mode.

### Historical mutation

Covered by Change Proposal, document-health, and end-to-end tests:

- accepting a material Change Proposal creates Snapshot vN+1;
- prior Snapshot content and `content_sha256` remain unchanged;
- source invalidation changes artifact health rather than rewriting historical PRD/TechDoc/Snapshot content.

## 5. Frozen engineering acceptance cases

The 3.0 fixture/test set covers ten approved engineering cases:

1. convenience-store replenishment;
2. non-AI workflow where AI overengineering is rejected;
3. decision-critical ambiguity with at most one clarification;
4. only two materially valid solutions;
5. conflicting real-user evidence;
6. simulated research cannot validate a real-user claim;
7. implementation evidence can support feasibility but not user need/value;
8. archived evidence makes dependent artifacts stale;
9. cross-project evidence attack fails closed;
10. 2.0.6 legacy migration remains additive and does not invent validation.

The end-to-end frozen case exercises Quick Start → Snapshot v1 → real-user evidence contradiction → material Change Proposal → Snapshot v2 → document confirmation → handoff readiness → source archive → stale documents → handoff not ready.

These are engineering acceptance cases. They do **not** constitute real-user product effectiveness evidence.

## 6. Data / artifact integrity boundary

Implemented invariants include:

- formal Snapshot creation requires an explicit user-confirmed solution decision;
- project Claim provenance and verification status are separate fields;
- evidence links require current-project source/chunk scope and an exact stored span;
- independent support is counted by source, not by number of chunks;
- `simulated_research` cannot become real-user validation;
- `implementation_evidence` cannot establish user need or user value;
- historical artifacts are immutable; current usability is represented by `artifact_health`;
- source archive/restore recomputes downstream health transactionally;
- handoff reads the current formal context and fails closed when required PRD/TechDoc artifacts are unhealthy.

## 7. Claim boundary and known limitations

The implementation supports the claim that InsightForge 3.0 is a runnable local Idea-to-MVP workspace with domain-specific solution exploration, explicit project Claims, evidence-impact proposals, immutable Snapshot/document history, and fail-closed handoff controls.

It does **not** establish or claim:

- measured real-user five-minute time-to-value;
- retention, willingness to pay, productivity improvement, or reduced PRD/dev clarification rate;
- superiority to ChatGPT, ChatPRD, Productboard, Notion, Miro, or other products;
- production enterprise collaboration, RBAC, SSO, SLA, or multi-tenant security;
- GraphRAG or a product knowledge-graph innovation;
- autonomous organizational approval;
- production remote MCP OAuth/integration;
- fairness/compliance validation for production high-impact decisions;
- arbitrary semantic quality from `deterministic_demo`;
- production-scale latency/cost/reliability results.

MCP remains a local STDIO handoff capability; remote enterprise integration is explicitly outside the 3.0 P0 scope.

## 8. Final release status — user-feedback completion refresh (2026-08-28)

Fresh full-suite verification after the user-feedback completion work and stale-draft conflict fix:

```text
pytest -q: 337 passed, 1 skipped in 106.36s
python -m compileall -q app tests: PASS
node --check app/static/app.js: PASS
node --check app/static/model-settings.js: PASS
```

The single skip is the Windows-only `start.bat` launcher test when executed on Linux.

Browser acceptance evidence and deployment/live-provider boundaries are shipped under `outputs/browser_acceptance/` and `docs/`. A fresh Chromium rerun from this sandbox was blocked by administrator policy for localhost navigation, so the package does not claim a new sandbox browser run after the final non-visual conflict fix. Formal Windows deployment must rerun browser acceptance and real provider connectivity locally.
