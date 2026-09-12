# Task 5 fresh re-review

## Verdict

**FAIL** for `7a2fde1..7ec4564`.

The stale-content retry finding is fixed and the change is narrowly scoped, but the responsive acceptance evidence still does not substantiate actual rendered geometry/overflow/readability. The new objects expose fake-DOM-shaped APIs, yet their dimensions and readability are prescribed by the fixture rather than computed from the DOM/CSS.

## Findings

### P1 — Responsive geometry assertions remain non-rendered

`measureResponsiveFixture()` assigns every surface's `width`, `height`, `clientWidth`, and `scrollWidth` through `setLayout()`. `getBoundingClientRect()` only returns those assigned values. Child widths and intrinsic widths are also hardcoded by the fixture; CSS is consulted only for selected grid column counts, the solution-grid gap, and `flex-wrap`.

Consequently, the assertions do execute `getBoundingClientRect()`, `clientWidth`, `scrollWidth`, and the `readability` check, but they do not measure CSS-driven layout. Relevant declarations such as control input `min-width`, control-grid gap, padding, and actual track sizing are not used to derive the measured boxes.

Fresh local mutation evidence: changing the in-memory stylesheet rule
`.ai-reference-item-controls select, .ai-reference-item-explanation { ... min-width: 0; }`
to `min-width: 1000px` still produces **21/21 PASS**. That mutation would make the desktop control grid exceed its approximately 1180px container (`180px + 1000px + 10px`), so the fake assertions would miss a concrete horizontal-overflow regression.

The report may accurately call this a deterministic fake/local fixture, but it cannot claim actual rendered responsive geometry or equivalent browser layout coverage without a real layout engine or a stronger fixture model that derives geometry from the relevant CSS.

### P2 — AI Reference stale-retry ordering: PASS

The new test is non-vacuous and checks the required order:

1. It renders a valid prior reference and explicitly seeds an old error message.
2. It starts a deferred failed retry.
3. Before the deferred response resolves, it asserts stale content is gone and the generating message is visible.
4. After failure, it asserts no stale content and safe failure copy.
5. A second deferred success retry remains empty while pending, then renders exactly one replacement result and removes both old error states.

This matches `generateAIReference()` clearing/rendering before the awaited POST at `app/static/app.js:2891-2896`. The focused test passed.

## Scope and boundary checks

- **Scope: PASS.** The commit changes only `tests/stage_b_generation_surface_harness.js` and `task-5-fix-report.md`; no production app/style file changed in `7a2fde1..7ec4564`.
- **Local-only boundary: PASS.** Verification used Node syntax checks, the local harness, intercepted fake fetch responses, and an in-memory stylesheet mutation. No real Provider, Search, network transport, deployment, or B3 path was invoked.
- **Fix-report accuracy: Bounded.** The 21/21 result and retry sequence are accurate. The responsive section should remain explicitly described as a fake contract probe, not as actual rendered-layout verification.

## Fresh verification

- `node --check tests/stage_b_generation_surface_harness.js` — PASS
- `node --check app/static/app.js` — PASS
- `node tests/stage_b_generation_surface_harness.js` — **21/21 PASS**
- In-memory overflow mutation of the stylesheet — **21/21 PASS**, demonstrating the responsive assertion gap
- `git diff --check 7a2fde1 7ec4564` — reports a blank line at EOF in `task-5-fix-report.md` (non-blocking hygiene issue)

## Required follow-up

Use a local browser/layout runner or make the deterministic fixture derive child/track geometry and overflow from all relevant CSS constraints. Keep the existing stale-retry test. Until responsive geometry is genuinely measured or the report claims are narrowed, Task 5 remains **FAIL**.
