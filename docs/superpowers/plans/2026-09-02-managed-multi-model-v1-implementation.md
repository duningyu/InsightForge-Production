# Managed Multi-Model Selector V1 Implementation Plan

## Guardrails

- Work only in execution worktree `insightforge-managed-multi-model-v1`.
- Preserve historical receipts and the Phase A/frozen hotfix commits.
- Real Provider requests: `0` through development and offline acceptance.
- Do not change timeout, retry, quota limits, Cloudflare/Caddy, or participant
  databases.
- Use additive schema changes and retain `UNKNOWN_LEGACY` for old rows.

## Phase 1 — RED contract tests

1. Add registry tests for AUTO/QWEN/GLM/DEEPSEEK, exact IDs, Bailian route,
   unknown/disabled selection rejection, and default preservation.
2. Add router tests for one resolved selection, credential-reference reuse,
   no fallback, and Solutions-only wiring.
3. Add durable intent tests for requested/resolved model persistence, same-intent
   replay, and `IDEMPOTENCY_MODEL_MISMATCH` with zero Provider/quota activity.
4. Add fixture tests for Qwen, GLM, and DeepSeek response shapes through the
   existing normalization and diversity validators.
5. Add settings/API tests proving ordinary Managed Pilot users cannot submit
   provider/key/base-url/model-id mutations while Advanced/BYOK behavior stays
   unchanged.
6. Add quota/provenance tests for success consumption, failure release, model
   switch as a new intent, and operator-safe per-model accounting.
7. Add frontend/browser tests for selector rendering, per-generation override,
   loading/error states, mobile 390x844 and desktop 1440x900, and safe model
   provenance. Run these tests before production edits and record meaningful
   RED failures. Do not proceed if the tests do not exercise the old contract.

## Phase 2 — Minimal implementation

1. Add a single managed model registry module using the verified model IDs and
   existing Bailian URL/credential boundary. Keep secret values out of domain
   objects and responses.
2. Add a router that resolves a preference once for Solutions and returns an
   immutable safe selection object. Keep AUTO mapped to the current Qwen
   default until an explicit later decision.
3. Extend `solution_generation_intents` additively with requested preference,
   resolved family, and resolved model ID; update the durable guard to reject
   same-key model mismatch before quota/provider work.
4. Extend solution-run provenance and safe response metadata without storing
   prompt/completion/provider raw bodies. Treat old rows as `UNKNOWN_LEGACY`.
5. Thread a validated per-generation preference through the existing Solutions
   endpoint/service into the router. Preserve the current idempotency header
   contract and explicit retry/new-intent semantics.
6. Reuse the existing adapter and solution validators. Do not add model-specific
   structured-output assumptions, hidden retries, fallback, or timeout changes.
7. Add the Managed settings selector and safe provenance text; preserve the
   existing advanced/BYOK UI as a separate path.

## Phase 3 — Targeted GREEN and regression

1. Run registry/router/idempotency/fixture/quota tests.
2. Run IdeaBrief, clarification, confirmation, Solutions eligibility,
   managed-runtime, history, feedback, rate-limit, and privacy tests.
3. Run frontend checks, compileall, `git diff --check`, SQLite integrity/FK,
   and secret scans across source, tests, reports, logs, and receipts.
4. Verify the resulting test evidence contains no real Provider request and no
   secret/Authorization value.

## Phase 4 — Review and release preparation

1. Review the diff for frozen-source contamination and accidental public secret
   paths.
2. Create the suggested small commits where the repository workflow permits:
   registry/router, selector, and tests; then create a successor release commit
   only after all offline gates pass.
3. Build a new image/artifact without overwriting Phase A or prior hotfix
   artifacts. Record commit, image digest, and artifact SHA.
4. Back up beta001/002/003 before any deployment. Deploy beta001 only for the
   first acceptance; keep beta002/003 stable.

## Phase 5 — Authorized real GLM boundary

After offline gates and beta001 deployment smoke pass, stop at the explicit
human authorization boundary:

`HUMAN_INTERACTION_REQUIRED`

`interaction_type: AUTHORIZE_ONE_REAL_GLM52_SOLUTIONS_ACCEPTANCE`

The later authorized action is exactly one real `glm-5.2` Solutions request,
with no fallback or automatic retry. Record safe upstream/selection/quota
metadata only. Do not call DeepSeek and do not change AUTO's default from one
success. Recommend, but do not perform, any beta002/beta003 rollout after the
result.
