# Managed Multi-Model Selector V1

## Status and scope

This is an additive successor execution based on the durable-idempotency hotfix
at `0f365b730b5c11cb21577328bfbab886faed02e6`. It does not rewrite Phase A,
the historical hotfix receipts, or the production directory. Development and
acceptance in this execution use mocks and fixtures only; real Provider
requests remain zero until a separately authorized GLM acceptance gate.

The latest external idempotency audit is a prerequisite, not a new product
claim: the current durable ledger contains one failed intent, one provider
call, one quota reservation, and the timeout release leaves beta001 at 2/3.
The earlier pre-fix two-call incident remains historical evidence.

## Product contract

Ordinary Managed Pilot users may choose `AUTO`, `QWEN`, `GLM`, or `DEEPSEEK`
for Solutions generation. The available model IDs are:

| preference | family | model ID | route |
|---|---|---|---|
| AUTO | resolved server-side | `MANAGED_PILOT_DEFAULT_MODEL` | Alibaba Cloud Model Studio/Bailian |
| QWEN | QWEN | `qwen3.7-flash` | Alibaba Cloud Model Studio/Bailian |
| GLM | GLM | `glm-5.2` | Alibaba Cloud Model Studio/Bailian |
| DEEPSEEK | DEEPSEEK | `deepseek-v4-flash-0731` | Alibaba Cloud Model Studio/Bailian |

The DeepSeek ID is taken from `docs/beta/FROZEN_PROVIDER_CONTRACT.md` and the
existing provider adapter test, not invented by this change. AUTO preserves
the current managed default (`qwen3.7-flash`) until a later, separately
approved decision changes it. A request stores both the requested preference
and the resolved family/model ID.

The selector is available in ordinary Pilot settings and as a per-generation
override. An override does not mutate settings. Ordinary users see the hosted
test-environment explanation and never enter a Provider, model ID, base URL,
or API key. Existing BYOK/Advanced profile APIs remain available only through
their existing advanced path and are not part of the Managed selector.

## Single registry and routing

`ManagedModelRegistry` is the sole source for UI/API validation and runtime
resolution. Each entry contains a stable preference, family, exact model ID,
display label, Bailian route, credential reference, and capability metadata.
The registry must reject disabled/unknown preferences and must not silently
fall back to another model.

`ManagedModelRouter` resolves a requested preference to one immutable runtime
selection for the operation. V1 wires this router to Solutions only. It does
not claim multi-model support for IdeaBrief, evidence, Snapshot, or PRD.
All three families use the existing Bailian credential abstraction. The
existing managed credential remains the source of truth; a compatibility
alias may be accepted at the configuration boundary, but no second frontend
secret or domain-level secret name is introduced. Secrets never enter the
registry response, analytics, SQLite business payloads, browser responses,
logs, images, or receipts.

Provider-specific structured-output and thinking settings are not guessed.
Qwen keeps its existing verified settings. GLM and DeepSeek use the existing
adapter contract until a model-specific capability is established by a
separate acceptance. This V1 does not alter timeout, retry, output limits, or
the existing solution validator.

## Durable generation identity

The existing durable solution intent ledger remains the server authority. It
is extended additively to store safe requested preference, resolved family,
and resolved model ID. Its uniqueness remains participant + project +
operation + idempotency key. On the first request, the server freezes the
selection. A replay with the same intent but a different requested/resolved
model returns `IDEMPOTENCY_MODEL_MISMATCH` and performs no quota reservation
or Provider call. Replays with the same selection follow the existing
IN_PROGRESS/SUCCEEDED/FAILED idempotent behavior. An explicit user switch
creates a new intent.

Each persisted generation run records requested preference and resolved model
provenance. Legacy rows that lack these fields are reported as
`UNKNOWN_LEGACY`; they are never retroactively inferred.

## Quota and failure behavior

The existing per-participant quota contract is unchanged. A successful
Solutions generation consumes one solution-generation unit. A Provider
failure/timeout releases its reservation. A model switch does not reset quota.
Operator-safe accounting can group Provider calls by family/model, while the
participant quota remains operation-based. No model fallback, voting,
automatic alternate retry, or hidden switch is allowed.

## Output and UI

Each selected runtime normalizes its response into the existing
`SolutionCandidates`/solution-set domain and passes the existing normalization,
diversity, and persistence validators. Fewer than two valid candidates is a
controlled generation failure, never HTTP success with an empty solution set.

The UI presents a compact provenance label such as “由 GLM-5.2 生成” and safe
latency/status metadata. It does not display Provider internals or credentials.
Settings display:

- Qwen3.7-Flash
- GLM-5.2
- DeepSeek V4 Flash
- 阿里云百炼官方 API / InsightForge 测试环境提供 / 无需配置 API Key

## Acceptance boundaries

Offline tests must cover registry, router, settings, per-generation override,
model-frozen idempotency, mismatch rejection, quota release, and normalized
Qwen/GLM/DeepSeek fixtures. Browser tests use mocked Provider responses and
must cover desktop/mobile selector behavior and provenance rendering. The
offline gate also includes existing IdeaBrief, clarification, confirmation,
Solutions, managed-runtime, idempotency, quota, privacy, SQLite, JS, and
secret-scan checks.

Only after all offline gates pass may this execution request one real GLM
Solutions acceptance (`glm-5.2`, no fallback, no retry). DeepSeek receives no
real call in V1. One GLM success must not change AUTO's default. Beta002 and
beta003 remain stable until a later operator decision.

## Non-goals

This execution does not change the product source in the formal directory,
historical release commits, Provider endpoint, Qwen timeout, quota limits,
Evidence/Claim semantics, PRD/IdeaBrief model routing, or deployment exposure.
