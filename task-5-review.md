# B2 Task 5 Independent Review

## Verdict

**FAIL** for `d84a1b1..7a2fde1`.

The commit is narrowly scoped and the production behavior exercised by the fake harness is generally fail-closed: provider/parse/schema/empty failures produce safe Chinese recovery copy, loading terminates, successful retry renders non-empty content once, local recovery is written, and no real Provider/Search/transport/deployment/B3 path is used. However, the Task 5 acceptance evidence does not substantiate the claimed responsive/layout coverage, and the AI Reference stale-content test does not actually seed stale content before testing failure. Those gaps are material to the requested task and must be fixed or the claims must be downgraded.

## Scope and materials reviewed

- Commit `7a2fde1` against parent `d84a1b1`
- `.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/review-d84a1b1..7a2fde1.diff`
- `.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/task-5-report.md`
- `.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/task-5-red-evidence.txt`
- `docs/superpowers/plans/2026-09-12-stage-b-ai-generation-ux.md`
- `app/static/app.js`, `app/static/styles.css`, and `tests/stage_b_generation_surface_harness.js`

The commit changes only `app/static/styles.css` and the acceptance harness. It does not alter the B1/B2 DTOs, exact-three contract, persistence implementation, Provider/Search integration, transport, deployment, or B3 code.

## Finding 1 — responsive/layout acceptance is static and incomplete

**Unresolved — P1 acceptance-evidence failure.**

The plan requires 1366 and 1440 desktop fixtures plus 125% and 150% equivalent settings through the existing Chromium harness mechanism, with readable/no-overflow checks for solution cards, the reference panel, Action Cards, generation progress, PRD/TechDoc, and Handoff.

The new checks in `tests/stage_b_generation_surface_harness.js:276-315` do not execute a browser, render the page, measure computed layout, or inspect overflow/scroll width. The four fixture tuples are only arithmetic values. Three fixtures (`1366/100%`, `1440/100%`, and `1366/125%`) perform no assertion because `cssWidth <= 960` is false; only `1440/150%` checks that a raw CSS regex exists. The remaining surface checks are also raw stylesheet regexes. The task report explicitly describes these as “fast CSS/fixture contracts rather than browser pixel test,” which does not meet the plan's Chromium-harness acceptance requirement.

The added rule at `app/static/styles.css:209` is a plausible fix for the narrow AI-reference controls, but the test cannot establish that the listed surfaces are readable or free of overflow at the requested fixtures.

Required follow-up: run the existing local Chromium/fake-transport harness or add an equivalent deterministic browser fixture. For each requested viewport/zoom-equivalent case, assert rendered surface visibility and relevant geometry/overflow; cover all named surfaces. No real Provider, Search, transport, deployment, or B3 access is needed.

## Finding 2 — AI Reference stale-content cleanup is not tested on a retry

**Unresolved — P2 test-quality gap.**

In `tests/stage_b_generation_surface_harness.js:471-481`, each failure case first calls `localStorage.clear()` and `loadAIReference()`. `loadAIReference()` resets `aiReferencePanel.result`, decisions, and reference id before rendering. `generateAIReference()` also clears those fields before the POST. Therefore the assertion that `#ai-reference-content` has zero children after failure only proves that the panel started empty; it does not prove that a failed retry removes stale AI-reference content.

The only real stale-content retry assertion is for the Solutions surface at `tests/stage_b_generation_surface_harness.js:563-583`. The AI Reference success path checks body text and loading state, but does not assert that the previous error banner/message is cleared after recovery. Action Cards and PRD/TechDoc do not receive an equivalent failed-retry stale-content assertion in this added harness.

Required follow-up: seed a valid prior AI-reference result and an error state, issue a deferred failed retry, assert stale content is cleared while pending and remains absent on failure, then resolve a successful retry and assert exactly one rendered result plus replacement of the old error message. Add the corresponding stale-content assertions for any other surface whose Task 5 report claims this behavior.

## Persistence and failure/retry checks

### Failure, safe recovery, and loading — PASS with bounded coverage

- Provider, parse, schema, and empty-result cases are exercised with intercepted fake responses.
- User-visible recovery copy is checked for safe Chinese text and against `Traceback`, provider-wrapper text, parser text, and `MODEL_OUTPUT_SCHEMA_INVALID`.
- Failed content is not rendered in the tested initially-empty AI-reference case; loading is hidden after failure and after recovery.
- The Solutions retry test uses a deferred fake response and verifies the POST is issued and stale solution content is cleared before resolution.
- The underlying implementation uses typed response validation and `textContent`/allowlisted rendering for the reviewed surfaces; no new raw error/provider/prompt/schema rendering path is introduced.

### Persistence — PASS as local recovery, weaker than a real refresh

The persistence case writes AI Reference and Action Card results to the existing local draft store, then re-runs the load functions with empty server responses and confirms the visible bodies reappear. This is useful fake/local coverage, but it is a same-VM “refresh-equivalent” test, not a new page/DOM reload. It does not establish server persistence or exercise a fresh runtime. The report should not describe this as browser refresh persistence without that stronger fixture.

## TDD RED evidence

**PASS, bounded.** `task-5-red-evidence.txt` records the pre-edit command and the expected failure:

```text
FAIL zoom-equivalent desktop fixture keeps AI reference controls readable: 1440px at 150% must stack AI reference controls
Baseline behavior cases passed: 16
Baseline responsive acceptance cases failed: 1
```

This is consistent with the reviewed diff: the only production change is the `max-width:1199px` single-column rule for `.ai-reference-item-controls`, and the current harness reports 20/20. The file is a concise record rather than a full command transcript containing the parent checkout hash, so it supports but does not independently reproduce the RED run.

## Scope, false-success, and regression checks

- **Scope: PASS.** The diff is limited to one CSS rule and one test harness; no unrelated production logic or B3 behavior was added.
- **No real integration: PASS.** The harness forbids `/search` and `/provider` routes and uses intercepted synthetic responses only.
- **Raw leak: PASS for tested paths.** Failure messages are humanized and the reviewed renderers use typed/escaped content; the narrow negative assertions found no raw provider/parser/schema strings.
- **False success: PASS for exercised cases.** Success requires a valid response id/result and non-empty visible fixture content; duplicate solution append is checked. The responsive report claim is nevertheless too broad because its test is not a rendered layout test.
- **Existing contracts: PASS.** The targeted solution design/API suite remains green; this commit does not change the exact-three or selected-solution implementation.

## Fresh verification

All runs were local and fake/deterministic or intercepted transport only:

- `node tests/generation_recovery_behavior_harness.js` — **PASS**
- `node tests/loading_progress_harness.js` — **PASS**
- `node tests/cancel_progress_harness.js` — **PASS**
- `node tests/document_evidence_ux_behavior_harness.js` — **PASS**
- `node tests/stage_b_generation_surface_harness.js` — **20/20 PASS**
- `py -3.12 -m pytest tests/test_v3_solution_design.py tests/test_v3_solution_api.py -q` — **16 passed**
- `node --check app/static/app.js` — **PASS**
- `node --check tests/stage_b_generation_surface_harness.js` — **PASS**
- `git diff --check d84a1b1..7a2fde1` — **PASS**

## Final decision

**FAIL pending real responsive fixture coverage and a non-vacuous AI-reference stale-retry test.** The CSS change and local recovery/error behavior are reasonable, but the current acceptance harness cannot support the report's responsive/layout and stale-cleanup claims.
