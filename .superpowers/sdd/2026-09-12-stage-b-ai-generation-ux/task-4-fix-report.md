# Task 4 fix report: exact-three solution contract

## Scope and source status

This is a scoped follow-up to the Task 4 review on parent commit `2a47102`.
The approved plan was read from `docs/superpowers/plans/2026-09-12-stage-b-ai-generation-ux.md`.
The requested `task-4-brief.md` is not present in this worktree, and `git log --all --name-only` found no such file in the relevant history. The unrelated similarly named brief in an archived/old worktree was not used.

No unrelated review file was edited. In particular, the pre-existing untracked `task-4-review.md` remains untouched and is not included in this fix.

## Findings fixed

- `SolutionSetDraft.candidates` accepted 2 or 3 candidates. It now requires exactly 3 complete `SolutionCandidateDraft` values with `Field(min_length=3, max_length=3)`.
- Synchronous and asynchronous provider adapter prompts said `2-3`. Both now say `exactly 3`.
- `DeterministicDemoRuntime` accepted any frozen case with at least 2 solutions. It now rejects every case whose solution count is not exactly 3 with an explicit `StructuredRuntimeUnavailableError`.
- The quick-start copy in `app/static/index.html` now states 3 solutions.
- The provider schema fixture and deterministic runtime assertion were updated to reflect the strict contract.

The existing duplicate/near-identical rejection remains in `app/services/generation_contracts.py`; `_material_difference_count` and `SOLUTION_DIVERSITY_FAILED` were not changed. Selected-solution inheritance and Stage A detail behavior were not changed.

## Independently auditable RED evidence

The test was written before the production fix and run against parent `2a47102`.
The actual failure record is tracked at:

`.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/task-4-red-evidence.txt`

Command:

`py -3.12 -m pytest tests/test_task4_exact_three_contract.py -q`

Observed result: exit code 1, `3 failed in 0.49s`.
The failures were: schema did not reject two candidates; provider prompt did not contain `exactly 3` and still contained `2-3`; deterministic runtime did not reject a two-solution frozen case.

## Fast verification

- `py -3.12 -m pytest tests/test_task4_exact_three_contract.py -q` — **3 passed**.
- `py -3.12 -m pytest tests/test_task4_exact_three_contract.py tests/test_provider_adapters.py -q` — **48 passed**.
- Targeted diversity, deterministic-runtime, and selected-solution inheritance tests — **3 passed**.
- `node tests/solution_detail_behavior_harness.js` — **16 passed, 0 failed**.
- `node tests/stage_b_generation_surface_harness.js` — exit code 0.
- `rg` scan found no `2-3` or `2–3` range text under `app/`.
- `git diff --check` — clean.

An attempted combined command covering the broader Task 4 test files was stopped after about 30 seconds at roughly 43% progress, per the scoped-fix time limit. Its partial run is not reported as a pass and was not allowed to continue into a long test run.

No real Provider, Search, transport, deployment, or B3 operation was performed. Adapter coverage used local monkeypatches/mock fixtures only.

## Commit scope

The requested commit is:

`fix: enforce exact-three solution contract`
