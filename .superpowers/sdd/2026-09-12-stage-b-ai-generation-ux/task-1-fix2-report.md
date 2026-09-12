# B2 Task 1 P1 Duplicate Fixture Fix

Date: 2026-09-12

## Scope

Test-only fix for the duplicate-solution fixture in `tests/fixtures/stage_b_generation_ux_cases.json`. No production files, Provider calls, Search calls, or subagents were used.

## Contract inspected

The fixture now contains exactly three complete `SolutionCandidateDraft` candidates using the actual public schema. All required text/list fields are present, mechanisms are from the supported allowlist, runtime flags are explicit, and the fixture remains synthetic.

The quality shape is intentional:

- candidates 0 and 1 are a near-identical pair: they differ in exactly one `DIVERSITY_FIELDS` value (`major_dependency`);
- candidate 2 differs from each pair member in at least two diversity fields;
- IDs and titles remain distinct, so the intended defect is differentiation quality rather than identity/schema validity.

## Strict TDD evidence

Before repairing the fixture, the new independent contract assertion failed with:

`duplicate fixture candidates must pass the solution candidate schema before quality validation false !== true`

This reproduced the P1 contamination identified in `task-1-rereview.md`: the old fixture was rejected for missing required schema fields and an unsupported mechanism before the duplicate-quality path could be exercised.

After the fixture repair, the focused test's contract probe passes schema validation for all three candidates and independently receives `SOLUTION_DIVERSITY_FAILED` from `validate_solution_response`.

## Focused verification

Command:

`node tests/stage_b_generation_surface_harness.js`

Result: `total=11 passed=7 failed=4` (exit code 1).

The duplicate case now reaches the intended application-level rejection assertion and fails only because the current production UI still renders the three cards (`3 !== 0`). The other three failures are pre-existing Task 1 production-surface gaps (unsafe PRD, TechDoc scope drift, and stale retry content) and are outside this P1 fixture-only scope. The fixture schema/quality isolation assertions pass before that UI assertion.

## Changed files

- `tests/fixtures/stage_b_generation_ux_cases.json`
- `tests/stage_b_generation_surface_harness.js`
- this report
