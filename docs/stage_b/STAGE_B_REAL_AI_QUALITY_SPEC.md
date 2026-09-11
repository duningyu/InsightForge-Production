# Stage B Real AI Quality Specification

Status: preparation only. This document freezes the first real-provider quality batch; it does not authorize a real request by itself.

## Scope

Stage B evaluates whether InsightForge adds product value beyond a direct call to the same model:

`REAL IDEA → InsightForge context/guidance → comparable solutions → user decision → PRD/TechDoc/Handoff`

The first batch uses exactly one provider/model pair:

- Provider: Bailian
- Model: `qwen3.7-flash`
- Search: disabled
- Accounts: disabled
- Participant: `railway_stage_b`
- `INSIGHTFORGE_SAFE_FIXTURE_MODE=false`
- `REAL_PROVIDER_STAGE_B=true` only in the isolated Stage B service

Stage A remains the synthetic regression environment. Stage A data, beta data, and real-user data are not evaluation inputs.

## Safety boundary

Real-provider execution is fail-closed unless all of the following hold:

1. `REAL_PROVIDER_STAGE_B=true`;
2. safe fixture mode is false;
3. accounts are disabled;
4. `BETA_PARTICIPANT_ID=railway_stage_b`;
5. the request is made by the Stage B evaluation path.

The guard does not change authentication, ownership, or document permissions. It is not an auth bypass. No public fixture/reset endpoint is allowed.

The initial transport budget is 12. Automatic retries are zero. A user clicking “重新生成” creates a separately recorded logical attempt and consumes another transport. Budget exhaustion fails closed.

The Bailian key is entered manually in the Stage B Railway Service Variables only. It must not appear in Git, tests, Docker layers, logs, screenshots, receipts, or browser storage.

## Frozen comparison

Each real idea is run through two separately labelled modes:

- `INSIGHTFORGE`: the normal context assembly and product workflow;
- `DIRECT_BASELINE`: the same raw idea sent to the frozen minimal baseline prompt, without InsightForge context.

Prompt versions are frozen for a batch. Any prompt change starts a new batch and cannot be mixed with earlier scores.

## Batch protocol

The operator supplies three unmodified user ideas (`idea_A`, `idea_B`, `idea_C`) with their known information and unknowns. Full text stays in the private evaluation artifact. Public receipts contain only the IDs.

1. Run one synthetic provider smoke request and stop to inspect provider/usage/ledger evidence.
2. Run `idea_A`, inspect its trace and outputs, then continue only if there is no safety or quality anomaly.
3. Repeat for B and C; do not run all requests in parallel.
4. Score guidance and solutions before generating documents.
5. Continue documents/Handoff for at least two ideas only if the AI layer meets the minimum gate.

The evaluation is directional product evidence, not a statistically powered study. It must not be presented as proof of general model superiority.

## Required trace

Every transport records evaluation ID, idea ID, execution mode, operation, provider, model, prompt/context versions, request/response timestamps, latency, retry ordinal, result classification, optional token usage/cost, generation ID, schema validation, and failure classification. Normal traces contain hashes and metadata, not complete prompts or responses.

Complete request/response payloads and human scores belong only in a private, uncommitted evaluation artifact directory.

## Failure and search rules

Failures are classified as `NETWORK`, `AUTH`, `RATE_LIMIT`, `TIMEOUT`, `PROVIDER_4XX`, `PROVIDER_5XX`, `INVALID_RESPONSE`, `SCHEMA_VALIDATION`, `APPLICATION_POSTPROCESS`, or `UNKNOWN`. No automatic retry is allowed in the quality batch.

Search remains off. Model knowledge must not be labelled as searched evidence; the UI must continue to state that network lookup is unavailable.

## Decision outcomes

- `STAGE_B_AI_VALUE_ACCEPTED`: clear added value in the small batch and no critical fabrication/inheritance failure;
- `STAGE_B_AI_VALUE_PARTIAL`: useful in some ideas but with material prompt/context/inheritance weaknesses;
- `STAGE_B_AI_VALUE_NOT_PROVEN`: workflow runs but added value over the direct baseline is not demonstrated.

Do not upgrade the result because the technical chain succeeded.
