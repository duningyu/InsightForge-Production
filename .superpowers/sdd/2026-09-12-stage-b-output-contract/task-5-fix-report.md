# Task 5 B1 Fix Report

Date: 2026-09-12
Worktree: `E:\AI_Projects\_deploy\insightforge_managed_multi_model_v1\worktree\InsightForge`

## Scope

Fixed only the five B1-attributed regressions documented in `task-5-diagnosis.md`:

1. Updated the account lifecycle synthetic solution fixture to emit exactly three valid, title-unique, materially diverse candidates. The account persistence assertion now expects three candidates per successful generation.
2. Repaired the synchronous `SolutionDesignService` empty-candidate path. An explicitly empty model result now reaches the persisted run validation path, records a `failed_schema` status, releases the reservation, writes the failure audit, persists zero candidates, and still raises the structured error needed for the API's safe 503 envelope. Existing non-empty structured recovery behavior remains unchanged.
3. Migrated the P0 API assertion to the safe public error contract: trusted `error_code`, message, recovery action, `content_written: false`, and `retryable: false`; no `preserved_input` or raw message is accepted.

No real Provider/Search/transport/deployment was used. No unrelated production behavior or the 12 pre-existing failures were modified.

## Strict TDD evidence

### RED

Before the production edit, the new/updated regression assertions were run with:

```text
py -3.12 -m pytest -q tests/test_account_business_paths.py::test_running_task_keeps_workspace_after_logout_and_account_switch tests/test_account_business_paths.py::test_four_generations_account_scope_replay_and_worker_reconstruction tests/test_pilot_p0_hotfix_red.py::test_zero_candidate_solution_run_cannot_remain_successful
```

Result: `4 failed` (the parameterized account test produced two failures). The account fixtures still contained two candidates, and the empty-candidate service test reported `DID NOT RAISE` because the result was intercepted before durable run persistence.

### GREEN

The minimal production fix is limited to `app/services/solution_design.py`:

- allow an explicitly empty `SolutionSetDraft` result through the initial parse boundary;
- keep the durable run record on the validation path;
- distinguish that empty cardinality failure from non-empty structured recovery failures so the pre-existing recovery contract is retained;
- persist the failed run and re-raise the structured error, allowing the existing API handler to return the safe 503 projection.

The account fixture and public P0 expectation changes are limited to the two diagnosed test files.

## Verification

Focused regressions only:

```text
py -3.12 -m pytest -q tests/test_account_business_paths.py::test_running_task_keeps_workspace_after_logout_and_account_switch tests/test_account_business_paths.py::test_four_generations_account_scope_replay_and_worker_reconstruction tests/test_pilot_p0_hotfix_red.py::test_zero_candidate_recovery_is_not_reported_as_201_success tests/test_pilot_p0_hotfix_red.py::test_zero_candidate_solution_run_cannot_remain_successful
```

Result: `5 passed in 11.36s`.

`git diff --check` reported no whitespace errors. A broader test command was interrupted on request and was not used as completion evidence; the full suite was not rerun.

## Self-review

- Exact-three cardinality is preserved in production validation; fixtures now satisfy it rather than weakening the contract.
- The failed empty run is persisted before the exception is re-raised, and the candidate table remains empty.
- The API assertion verifies the public projection and rejects both preserved input and raw provider-style text.
- No external calls, deployment actions, subagents, or changes outside the diagnosed scope were used.

## Commit

Commit message: `fix: repair B1 solution generation regressions`
