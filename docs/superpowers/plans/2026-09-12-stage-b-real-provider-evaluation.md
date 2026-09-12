# Stage B Real Provider Evaluation Implementation Plan

> **For the implementing agent:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Define a bounded, durable, one-transport real-provider canary after B1/B2 are proven, without inheriting stale authorization or mixing evaluation versions.

**Architecture:** Freeze prompt, context, schema, rendering contract, and quality rubric at the B1/B2 commit. Use one synthetic product idea and one AI reference surface. Record receipt, dispatch, transport, response classification, parse/schema result, domain result, artifact, latency, tokens, and leakage checks in the existing durable observability path.

**Tech Stack:** Railway project `triumphant-sparkle`, environment `stage-b`, service `insightforge-stage-b`, persistent root `/app/data`, existing Stage B receipts/dispatch ledger/authorization services, Chromium harness, Python operator scripts.

**Spec:** Baseline dry observability at commit `e0e928674e33f892b6892c43c383505666771e27`; current services `app/services/provider_acceptance_authorization.py`, `app/services/provider_dispatch_ledger.py`, `app/services/ai_runtime.py`, `app/services/async_generation.py`, and routes in `app/main.py`.

## Global Constraints

- This plan is not executed during B1/B2.
- Before execution, obtain a new explicit user authorization for the latest frozen commit; the historical authorization does not automatically cover a new commit.
- Use only the synthetic idea: “面向正在准备实习求职的学生，提供一个轻量求职进度管理工具，帮助记录投递、笔试、面试和待跟进事项。”
- First canary uses exactly one surface, preferably AI reference; automatic retry is zero and Search is zero.
- Stop immediately on failure or after one PASS. A multi-surface real chain requires separate explicit authorization.

## Tasks

### 1. Freeze the engineering contract

Files/artifacts: latest B1/B2 commit, `STAGE_B_AI_SURFACE_MATRIX.md`, the three Stage B plan documents, fixture matrix, API contract tests, frontend harnesses.

Record commit SHA, prompt/context/schema versions, rendering contract, quality rubric, test commands, and clean/dirty worktree. Confirm the baseline and latest deployment commit are distinct in the operator receipt. No code changes are allowed after freeze without a new version and new evaluation batch.

### 2. Reconfirm authorization and deployment state

Services/routes: `app/services/provider_acceptance_authorization.py`, `app/services/provider_dispatch_ledger.py`, `app/main.py` acceptance routes, existing Railway deployment/operator scripts under `scripts/` and `deployment/`.

Ask the user for explicit authorization naming the frozen commit and one AI-reference canary. Verify the deployed service is the frozen commit, persistent root is `/app/data`, authorization target matches provider/model, and conservative safe ceiling is recalculated from durable receipts rather than configured budget alone.

### 3. Execute one real AI-reference canary

Use the existing durable receipt creation, dispatch, transport, and inspector path. Verify request identity, provider/model, latency/tokens, raw response hash and byte count, normalization classification, parse pass, schema pass, domain completeness, artifact persistence, and public response denylist. Capture Chromium-visible result if the service endpoint is reachable, asserting visible body and zero JSON/provider leakage.

The expected request accounting is one transport, zero automatic retries, zero Search requests. On any provider, parser, schema, persistence, or frontend failure, stop and mark the canary failed; do not spend another request.

### 4. Record directional product-value evidence only after canary PASS

Do not execute this task without separate explicit `STAGE_B_PRODUCT_FLOW_CANARY` authorization. Use 2–3 user-confirmed synthetic Ideas, the same provider/model, and a side-by-side direct-prompt baseline. Store human 1–5 scores and reasons for Context Fidelity, Specificity, Novel Value, Decision Usefulness, Uncertainty Honesty, Actionability, Solution Differentiation, Tradeoff Quality, MVP Realism, Document Inheritance, and Handoff Executability. Keep rule-based contract metrics and human review primary; an LLM judge is auxiliary.

## Acceptance criteria

- No real request occurs before fresh authorization naming the frozen commit.
- The first authorized canary uses one transport, zero retries, zero Search, and the synthetic idea only.
- Durable observability reconstructs receipt → dispatch → transport → response → parse/schema/domain → artifact.
- Public/API/browser surfaces show no raw JSON or provider payload.
- A PASS supports engineering reliability and directional product evidence only; it does not support market-demand or statistical-superiority claims.
