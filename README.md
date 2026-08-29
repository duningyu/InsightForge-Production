# InsightForge 3.0 — Quick Value → Evidence Depth

InsightForge 3.0 is a local-first **Idea-to-MVP product design workspace** for AI product job seekers and junior/transitioning product managers. Its default flow is no longer a technical evidence workbench or a long product-coach questionnaire.

The first-value path is:

```text
Rough Idea
  → conservative IdeaBrief
  → 2–3 domain-specific solution candidates
  → explicit user solution decision
  → immutable Project Snapshot
```

Evidence is added after first value when the user wants to reduce uncertainty:

```text
Source
  → project Claim
  → validated evidence relation
  → dependent Decision / Artifact impact
  → Change Proposal
  → explicit user confirmation
  → new Project Snapshot version
```

The governing rule is: **AI proposes; deterministic code validates and propagates dependencies; the user confirms formal decisions and artifacts.**

## Primary product modules

The browser exposes exactly five primary user tasks:

1. **项目成果 / Project Snapshot** — current product definition, MVP, key unknowns, and one next-best action.
2. **方案 / Solutions** — 2–3 materially different ways to solve the current domain problem, with implementation detail and trade-offs.
3. **证据 / Evidence** — key Claims, evidence impact, and the source library.
4. **文档 / Documents** — Snapshot-aware PRD/TechDoc generation, health, confirmation, and export.
5. **开发交接 / Handoff** — executable MVP scope, implementation tasks, acceptance cases, and a fail-closed AI Coding package.

Canvas, RAG score details, Claim ledgers, validators, Function Calling, audit records, and MCP remain infrastructure or advanced detail; they are not the default navigation model.

## Implemented 3.0 behavior

- `IdeaBrief` distinguishes explicit `user_input` from `model_hypothesis`; confirming a brief confirms understanding only, not market truth.
- Solution generation returns **2–3 domain-specific candidates** and does not pad two valid options to three.
- Deterministic solution validation requires material pairwise diversity and rejects all-AI overengineering when an LLM core is not required.
- A formal solution choice requires explicit human confirmation and creates an immutable `ProjectSnapshot` plus project-level Claims.
- Canvas is retained as a deterministic compatibility projection for the existing PRD/TechDoc pipeline; new 3.0 projects cannot edit it as an independent source of truth.
- Project Claims keep `provenance` separate from `verification_status`.
- Project evidence relations are fail-closed on project/source/chunk scope, active source state, source-type admissibility, exact evidence span, and retrieval trace when present.
- Evidence impact traverses stored dependencies; an LLM does not get permission to mutate formal Decisions, Snapshots, or documents.
- Material evidence changes create a user-reviewable `ChangeProposal`; acceptance creates a new Snapshot version and supersedes, rather than rewrites, history.
- Source archive/restore propagates through evidence links, Claim status, artifact health, and dependent Change Proposals in a transaction.
- PRD/TechDoc generation is bound to the current Snapshot and stores Snapshot/Claim/source dependencies plus artifact health.
- The user-facing action is **Confirm this version**. The underlying legacy database status value `approved` remains for backward compatibility and must not be described as an organizational approval workflow.
- Handoff is ready only when the current Snapshot and both current confirmed PRD/TechDoc versions are healthy.
- Legacy 2.x projects are migrated additively to explicitly labelled `legacy_migration` Snapshots without inventing project evidence or market validation.

## Structured AI runtime selection

### Local guidance

Uses frozen fixtures under `tests/fixtures/v3_golden_cases.json` when no usable model profile is selected. It exists to verify workflow, schema, gates, and deterministic acceptance behavior. It **does not prove arbitrary semantic AI quality** and fails explicitly when no frozen semantic case exists.

### Configured provider profile

Create a provider profile in **Settings**, write its API key to the operating-system credential store, test the connection, and select it globally or for one project. Legacy `OPENAI_*` environment variables do not select or authorize a remote provider. If the selected profile fails, the request returns explicit recovery actions rather than silently switching to another paid model.

PRD/TechDoc generation remains local until that path is migrated through the same per-project profile resolver.

## Requirements

- Python 3.10+
- SQLite; no external database is required for the local single-instance workflow.
- Internet access is only needed for initial dependency installation or optional live LLM use.

## Run

### Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start.ps1
```

### macOS/Linux

```bash
chmod +x scripts/start.sh scripts/start_mcp.sh
./scripts/start.sh
```

Open `http://127.0.0.1:8000`.

Manual setup:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload
```

## Test

```bash
pytest -q
python -m compileall -q app tests
node --check app/static/app.js
```

`VERIFICATION_REPORT.md` records the exact commands and counts used for the released package.

## Retrieval baseline

Project retrieval remains project-scoped before ranking. Named profiles use the current auditable baseline:

```text
0.55 * BM25 + 0.30 * TF-IDF cosine + 0.15 * authority
```

This is an engineering baseline, **not a frozen best configuration**. Retrieval traces store query, purpose, profile, Top-K, weights, candidates, hits, scores, actor, and time.

## MCP

A local STDIO MCP server exposes current Snapshot and healthy confirmed handoff context. MCP is an interoperability surface, not the product's core value and not a truth-verification mechanism.

```bash
./scripts/start_mcp.sh
# or: python -m app.mcp_server
```

No production remote MCP OAuth, enterprise SSO, or organization-wide permission model is claimed.

## Claim boundary

Engineering tests establish software behavior, not market effectiveness. This package does **not** establish:

- five-minute time-to-value in real users;
- user retention, productivity improvement, or willingness to pay;
- superiority to ChatGPT, ChatPRD, Productboard, Notion, or other tools;
- semantic truth verification equivalent to human research review;
- enterprise collaboration/security/SLA readiness;
- GraphRAG, a knowledge-graph product, or a multi-agent PM system;
- production remote MCP integration.

`simulated_research` is demonstration material, `model_hypothesis` remains a hypothesis, and `implementation_evidence` can support implementation feasibility but cannot prove user value or product-market fit.

## Legacy 2.0 compatibility boundary

The 2.0.6 package used **Guided Mode** as the novice-first flow and an **Advanced Workspace** for lower-level controls. Those surfaces are retained only as legacy-readable behavior for pre-existing projects, not as the 3.0 default IA. The historical implementation also included a replayable `retrieval trace`, a document-level `claim-evidence ledger`, and a concrete `AI coding handoff ZIP`; 3.0 preserves the underlying audit/handoff capabilities while moving them behind the five user-task modules above.
