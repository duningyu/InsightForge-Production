# Task 1 scoped review-fix report

Date: 2026-09-12

## Scope

This fix is limited to the B2 Task 1 test package. No production files,
Provider/Search transport, deployment configuration, or external service were
changed or used.

## Review findings addressed

1. The wrong-solution PRD and TechDoc scope-drift cases now assert the
   observable safety contract: unsafe content must not be visible, and the
   result must either preserve a valid selected-document continuation or be a
   typed fail-closed state (error code, visible error, and disabled editor).
   The tests no longer require a valid B document to be invented when the only
   response is invalid.
2. The duplicate fixture now contains exactly three complete candidates. The
   first two have different identities/titles but the same user flow and
   feature set; the third has a distinct flow. The test independently checks
   this fixture shape and requires the duplicate set to render no cards with
   an actionable safe state.
3. The stale-state regression now calls the real `retryFailedGeneration()`
   orchestration path with a pending fake POST. It observes the DOM before
   releasing the response, so stale content cannot be hidden by a response-only
   assertion. Transport remains deterministic and local.
4. `artifacts/stage-b-red-ux.txt` was refreshed from the corrected harness
   output. Because the repository ignores `artifacts/` broadly, this one
   required artifact is staged explicitly; ignore policy was not changed.

## Verification

The corrected Task 1 harness remains intentionally RED before production
Tasks 2/4, as required by the approved plan:

```text
node tests/stage_b_generation_surface_harness.js
SUMMARY total=11 passed=7 failed=4
```

The four failures are the intended current-production gaps: duplicate-set
rejection, PRD unsafe-content rejection, TechDoc scope-drift rejection, and
stale content during retry. The retry failure now comes through the actual
retry API/state transition path.

The existing pure Node harnesses remain green:

- `node tests/generation_recovery_behavior_harness.js`
- `node tests/solution_detail_behavior_harness.js`
- `node tests/document_evidence_ux_behavior_harness.js`

No real Provider or Search request was made.
