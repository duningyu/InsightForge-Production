# Hybrid Async Generation v1 Implementation Plan

## Scope

Execution `insightforge_managed_multi_model_v1`, branch
`insightforge-managed-multi-model-v1`. Preserve existing uncommitted timeout
observability work. No live Provider calls, no beta002/beta003 rollout.

## Tasks

1. Add durable async-run schema and repository transitions. Write RED tests for
   create/replay/claim/terminal behavior, participant/project isolation, and
   quota reservation uniqueness; then implement minimal SQL-backed repository.
2. Add async worker lifecycle and application wiring. Write RED tests for one
   claim, clean shutdown, failure release, and no duplicate execution; implement
   the bounded SQLite worker using the existing domain service boundary.
3. Add async submit/status API. Write RED tests for 202 response, status polling,
   terminal replay, and invalid project/run isolation; implement without changing
   the legacy synchronous endpoint.
4. Update browser generation state to submit async jobs and poll. Add local JS
   harness coverage for loading, success, failure, explicit retry, and duplicate
   delivery using one intent.
5. Add/adjust hybrid timeout configuration and safe provider-attempt linkage for
   the async path. Use deterministic mock transports only; preserve concrete
   timeout subtypes and exception causes.
6. Run targeted tests, full pytest, compileall, JavaScript checks, diff check,
   SQLite integrity/FK checks, and secret scan. Build the beta001 gray image only
   after all offline gates pass; leave beta002 and beta003 unchanged.

## Acceptance

`HYBRID_ASYNC_GENERATION_BETA001_GRAY_DEPLOYED` is permitted only when all
offline/gray gates pass and the actual beta001 image identity is recorded. The
next legal action is a separate human authorization for exactly one real GLM-5.2
async Solutions request, with no retry or fallback.
