# B2 Task 4 report

Date: 2026-09-12

## Outcome

Task 4 is complete. Stage B now requires exactly three schema-valid solution candidates, checks visible material differentiation, and fails closed for duplicate or near-identical sets. The selected solution B context is carried from the confirmed Project Snapshot into PRD, the current TechDoc, and Handoff without reintroducing an unselected candidate. Stage A single-solution detail behavior remains unchanged.

## Strict TDD evidence

Fresh tests were added before the production changes. The genuine RED run was:

```text
Failed: DID NOT RAISE ValueError
FAILED test_selected_solution_b_is_inherited_by_prd_techdoc_and_handoff
```

The first GREEN attempt exposed a real document-contract regression: PRD inserted a nested `##` heading inside section 7, so the document validator reported `DOCUMENT_INCOMPLETE`. The minimum fix changed that inherited subsection to `###`; the targeted Python suite then passed.

## Implementation

- `validate_solutions` uses the real `_material_difference_count` over user-visible solution substance and rejects pairs with fewer than two material differences.
- The managed generation prompt and UI copy require exactly three solutions; the UI also requires complete visible fields, including core idea (`summary`), flow, MVP scope, and tradeoffs/risks.
- Snapshot persistence records selected solution summary/core idea and user value so downstream documents do not reconstruct context from stale candidate data.
- PRD and TechDoc inherit selected identity, summary, value, rationale, problem/target-user context, MVP scope, inputs/outputs, flow, and risks from the current Snapshot.
- Handoff exports the same selected context, points `README_FIRST.md` to `CONFIRMED_CONTEXT.md`, and renders the selected solution context in the Handoff view.
- Document/UI checks reject missing selected context and reject content containing explicit non-goal terms or an unselected solution title.
- Stage A detail behavior was not broadened or made writable.

## Verification

Only local deterministic/fake tests were run:

```text
py -3.12 -m pytest tests/test_v3_solution_design.py tests/test_v3_solution_api.py -q
16 passed in 7.57s

node tests/solution_detail_behavior_harness.js
solution detail behavior PASS: read-only, missing fields honest, close restores focus, zero requests

node tests/stage_b_generation_surface_harness.js
SUMMARY total=16 passed=16 failed=0
```

The API test selects solution B and asserts its identity, summary, user value, problem, target user, rationale, flow, and MVP feature survive into both documents and the Handoff ZIP. It also asserts that the rejected solution A title is absent from every exported artifact.

The known legacy Chromium runner was not run. No real Provider, Search, transport, deployment, or B3 path was invoked.

## Commit and worktree

The focused commit is:

```text
fix: preserve solution and document inheritance
```

The intended final worktree contains only this task's committed changes plus the pre-existing untracked review reports (`task-2-rereview2.md`, `task-3-rereview.md`, and `task-3-review.md`).
