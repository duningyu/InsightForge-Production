# B2 Task 1 fix-3 report

## Scope

- Test-only change in `tests/stage_b_generation_surface_harness.js`.
- No changes to `app/static/app.js` or any other production file.
- No real Provider/Search calls; the surface tests use a fake DOM and mocked API responses.

## Coverage added

The harness now invokes the real app surface wiring through the captured `DOMContentLoaded` bootstrap and actual DOM click/loader paths for:

- AI reference generation with a non-empty visible body.
- Evidence Action Card generation with all required body fields.
- Solution generation with exactly three visible cards.
- PRD document loading and Handoff loading with selected PRD/TechDoc references.
- Retry through the actual retry click and generation path, asserting stale content cleanup before the deferred response.

The existing RED contracts for duplicate solutions, wrong-solution PRD, and TechDoc scope drift remain unchanged. The stale-content retry contract also remains RED until the production behavior is fixed.

## TDD and verification

- RED first: the new real-surface cases failed before the fake DOM/bootstrap plumbing was added.
- Focused harness run twice: `total=15 passed=11 failed=4`, deterministically.
- The four failures are the intentional RED contracts listed above.
- All nine other local `tests/*_harness.js` files passed.
- `node --check tests/stage_b_generation_surface_harness.js` passed.

## Commit boundary

Only the focused harness coverage and this report are included. Production files remain untouched.
