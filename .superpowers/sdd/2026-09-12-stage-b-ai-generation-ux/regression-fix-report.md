# Stage B scoped regression fix

Starting HEAD: `d8386db0fee190fd049078c7ef3fb2beb7c4830c` (clean worktree).
Date: 2026-09-12. Branch: `deploy/railway-stage-b`.
Commit message: `fix: restore Stage B regression fixtures and safe render paths`.

All 10 reported failures were reproduced before edits. The five affected files now pass: **63 passed**, including one added behavioral test. This is bounded regression evidence, not a full-suite or deployment approval.

## Failure classification and changes

| File / failing test | Count | Root cause and scoped correction |
| --- | ---: | --- |
| `test_account_business_paths.py`: `test_running_task_keeps_workspace_after_logout_and_account_switch[False/True]`, `test_four_generations_account_scope_replay_and_worker_reconstruction` | 3 | Obsolete fake substance: three candidates existed, but the first two differed only in title and implementation metadata. Stage B correctly rejected material duplicates, preventing success/commit. The fake now supplies rule, workflow, and forecast candidates with different summaries and user flows. Both success paths explicitly assert exactly three public candidates. Quota, cancellation, account isolation, persistence, reconstruction, and transport-count assertions remain. |
| `test_normal_dispatch_control_integration.py`: `test_normal_async_managed_path_acquires_permit_and_records_dispatch`, `test_same_acceptance_execution_replay_cannot_dispatch_twice` | 2 | Obsolete two-candidate fake and count expectation. Both tests now use a complete, materially distinct exact-three fake and assert three returned candidates. Real adapter/ledger behavior still runs over `httpx.MockTransport`; permit/event counts and replay prohibition remain. |
| `test_hybrid_runtime.py`: `test_two_local_solution_calls_are_counted_monotonically_in_failure_audit` | 1 | The two-candidate fake failed schema construction on its first call, before the diversity-regeneration path this test intends to exercise. It now returns three distinctly titled material duplicates. The existing two-call/two-round audit assertions remain; new assertions require `SOLUTION_DIVERSITY_FAILED` and zero persisted candidates. No retry budget was increased. |
| `test_v3_golden_cases.py`: `test_case_2_non_ai_workflow_rejects_all_ai_overengineering` | 1 | The added third candidate changed mechanism/metadata but insufficient user-visible substance, so diversity rejection preceded overengineering rejection. Its summary and flow now describe an automated executor. A positive control first validates the same three candidates with `llm_core_required=True`; the original `OVERENGINEERED_SOLUTION_SET` expectation remains for `False`. |
| `test_v3_golden_cases.py`: `test_case_4_stage_b_rejects_two_solutions_without_padding` | 1 | Obsolete rejection boundary: the deterministic runtime now rejects an incomplete frozen set before returning it. The test asserts that runtime rejection and independently asserts cardinality rejection for the original two frozen candidates. The frozen fixture remains two; there is no production padding or fixture expansion here. |
| `test_real_user_regression_contract.py`: `test_ai_reference_renders_object_items_without_object_stringification` | 1 | Historical presenter-path compatibility assertion. Stage B's strict string-list adapter already rejects object payloads, so this failure alone did not establish a live object-rendering leak. Restored the existing conditional structured presenter and serialized identity fallback behind that unchanged adapter. Accepted strings, including ordinary JSON text, retain their original display and decision identity; arbitrary object payloads remain rejected. All historical assertions remain unchanged. |
| `test_real_user_regression_contract.py`: `test_handoff_unresolved_items_have_safe_human_fallbacks` | 1 | Implementation safety regression confirmed behaviorally: string unresolved items bypassed the humanizer and could expose machine diagnostics. Object-field coercion could also display `[object Object]`. All unresolved items now traverse `humanizeUnresolvedItem`; its field reader uses existing `viewString` raw-marker/type checks before the existing diagnostic fallback. Safe Chinese instructions and structured explanations remain visible. All historical assertions remain unchanged. |

The new `_stage_b_solution_payload` is used only by the affected account and dispatch tests. The older `_solution_payload` remains unchanged for separate legacy browser-script consumers. This avoids changing unrelated fixtures or the known baseline failures.

## Production and test boundaries

- Only `app/static/app.js` changed in production: reference presentation fallback and Handoff humanization.
- No backend schema, cardinality, completeness, material-diversity, non-LLM baseline, provider adapter, dispatch, quota, retry, persistence, or raw-output validator was modified.
- Reference input validation remains strict. No generic object acceptance, validator bypass, `skip`, `xfail`, or blanket success expectation was added.
- Existing real-user safety assertions were preserved verbatim. Added a behavioral test invoking the actual application JS through the existing fake-DOM harness, with no external fetch.
- The known 12 baseline failures were not targeted, rewritten, or rerun. Their current full-suite status is not re-certified by this scoped run. No broad Python suite was executed.

## TDD and verification evidence

The systematic-debugging and test-driven-development skills guided root-cause classification and RED-before-production-edit execution. Verification-before-completion required successful scoped checks before commit.

Initial RED, from the repository root:

```powershell
py -3.12 -X utf8 E:/AI_Projects/tmp/stage-b-regression-runner.py E:/AI_Projects/_deploy/insightforge_managed_multi_model_v1/worktree/InsightForge -q --tb=short -p no:cacheprovider tests/test_account_business_paths.py tests/test_normal_dispatch_control_integration.py tests/test_hybrid_runtime.py tests/test_v3_golden_cases.py tests/test_real_user_regression_contract.py
```

Result before edits: **10 failed, 52 passed in 56.45s**, exit 1, `EXTERNAL_CONNECTION_ATTEMPTS=0`. The failure distribution exactly matched the request: 3 / 2 / 1 / 2 / 2.

Additional RED after adding behavioral coverage, before any production change:

```powershell
py -3.12 -X utf8 E:/AI_Projects/tmp/stage-b-regression-runner.py E:/AI_Projects/_deploy/insightforge_managed_multi_model_v1/worktree/InsightForge -q --tb=short -p no:cacheprovider tests/test_real_user_regression_contract.py
```

Result: **3 failed, 6 passed in 0.27s**, `EXTERNAL_CONNECTION_ATTEMPTS=0`: the two original assertions plus the new behavioral test. Its reference text/identity control passed; its Handoff diagnostic-exclusion assertion failed against the real renderer.

GREEN used the same five-file command as initial RED after the fixture and production fixes:

**63 passed in 46.81s**, exit 0, `EXTERNAL_CONNECTION_ATTEMPTS=0`.

Additional checks for the changed frontend:

```powershell
node tests/whole_branch_fix_harness.js
node --check app/static/app.js
git diff --check
```

Results: **204 JS checks passed, 0 failed**, exit 0; Node syntax check and whitespace check exit 0. The JS count includes the two new behavioral checks also invoked by the Python regression test; these counts are not disjoint. The existing marker, ordinary JSON/prose, reference completeness, Action Card, and selected-document scope checks remain passing. Git emits existing LF-to-CRLF conversion notices only.

The Python runner clears Provider/Search-related configuration, sets `REAL_PROVIDER_STAGE_B=false`, and blocks non-loopback socket connections. Tests use fake transports and disposable local databases. The JS harness uses a fake DOM and controlled fetch responses; it is behavior evidence, not browser/layout acceptance. No real Provider, Search, deployment, push, or broad-suite run was performed.
