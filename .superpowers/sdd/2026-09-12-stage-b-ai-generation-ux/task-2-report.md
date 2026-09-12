# B2 Task 2 implementer report

Date: 2026-09-12

## Scope and TDD order

Implemented only Task 2 from the approved Stage B plan. Before production edits, the existing Task 1 surface harness was run and its intentional RED was recorded in `artifacts/stage-b-red-ux.txt`:

- 11 passed, 4 failed.
- The four genuine failures were duplicate solutions rendering, wrong-solution PRD visibility, TechDoc scope drift visibility, and stale solution content remaining during retry.

The allowed tracked changes are limited to `app/static/app.js` and `tests/generation_recovery_behavior_harness.js`; this report is the requested SDD artifact. No `index.html` or `styles.css` change was needed.

## Implementation

- Added surface-specific allowlisted L4 adapters and fail-closed render guards for AI reference, Evidence guidance, solutions, document workspace, and Handoff.
- Removed whole-payload user rendering from those AI surfaces. User-visible values now come from bounded strings, bounded string lists, or explicitly allowlisted structured-list fields. `JSON.stringify` remains only in request, persistence, comparison, or internal recovery paths.
- Enforced complete success DTOs: AI reference fields, Evidence cards, exactly three unique and sufficiently differentiated solution candidates, document identity/version/type/content, and safe Handoff summaries are validated before state is marked successful.
- Cleared stale content, errors, IDs, selections, drafts, and loading-related content before retry for the requested generation flows. Invalid terminal poll results are also rejected and fail closed.
- Added stable Chinese error mapping for invalid document content/version responses; raw provider payloads, prompts, schema dumps, tracebacks, and exception text are not shown to users.
- Preserved Evidence optional semantics and Stage A deterministic fixture disclosure/compatibility.
- Updated the recovery harness fake success response to use the approved complete three-solution fixture, so the test exercises the new complete-DTO contract rather than accepting an incomplete one-card payload.

## Verification

All of the following used local deterministic fixtures, fake providers, or intercepted loopback transport only:

```text
node --check app/static/app.js                                  PASS
node tests/stage_b_generation_surface_harness.js                15 passed, 0 failed
node tests/generation_recovery_behavior_harness.js              PASS
node tests/document_evidence_ux_behavior_harness.js             PASS
py -3.12 -m pytest -q tests/test_api_error_contract.py tests/test_ai_reference_no_source.py tests/test_evidence_coach.py
                                                               11 passed
PLAYWRIGHT_MODULE=.../codex-primary-runtime/.../playwright
node tests/real_user_screenshot_gate.cjs                        passed=true, screenshots=45, failures=[]
```

The existing `tests/run_ai_reference_no_source_browser.py` was also attempted with its fake loopback transport. AI reference and Evidence passed, but its legacy fake solution payload returned two candidates in the old shape, so the solution-card wait timed out under Task 2's explicit exactly-three complete-solution contract. That runner is outside the Task 2 file scope and was not modified. No real external connection was made (`external: 0` in the runner diagnostics).

The unrelated `tests/solution_detail_behavior_harness.js` was not changed; its old one-candidate fixture now fails closed and then lacks a `#toast` DOM stub while testing the rejected detail path. Detail rendering remains read-only and adapter-gated; updating that out-of-scope harness belongs to the later solution-detail task.

## Exclusions

No real Provider, Search, transport, deployment, or B3 evaluation was run. No production backend, provider adapter, search path, or out-of-scope test file was changed.
