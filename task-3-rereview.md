# B2 Task 3 Fresh Re-review

## Verdict

**PASS** for `296010d..3708259`.

The scoped fix closes the prior frontend fail-open defect: empty arrays are now rejected for the required Action Card lists `who_or_where`, `action_steps`, `acceptable_artifacts`, and `fill_template`. The optional `suggested_questions` list remains optional, including when absent or empty. Evidence remains optional and the no-source behavior is unchanged.

## Scope and materials reviewed

- Commit `3708259` against base `296010d`
- `.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/review-296010d..3708259.diff`
- `task-3-review.md`
- `task-3-fix-report.md`
- `docs/superpowers/plans/2026-09-12-stage-b-ai-generation-ux.md`
- current frontend adapter/renderer, backend generation contracts, and focused harnesses

The commit contains only the intended frontend helper change, its focused regression harness update, and the fix report. No Provider, Search, transport, deployment, or B3 implementation was added or changed.

## Re-review findings

### Required Action Card fields — PASS

`viewStringList()` now returns `null` for an empty list when `required` is true. `toEvidenceGuidanceViewModel()` continues to invoke it with `required: true` for all four actionable lists, so incomplete cards fail closed before rendering. The focused fake-DOM regression covers each required list and verifies that no card or placeholder success text is shown.

### Evidence optional and `suggested_questions` optional — PASS

The adapter still calls `viewStringList(card[key], {required: key !== "suggested_questions", ...})`. Therefore an absent or empty `suggested_questions` list remains valid, while required actionable lists cannot be empty. Backend `validate_guidance()` retains the same distinction. The existing optional-evidence behavior harness and backend guidance tests pass; no evidence source is created by the reviewed path.

### Raw leak and safe rendering — PASS

The fix changes only list completeness validation. It does not introduce a new rendering path, raw object interpolation, provider diagnostic exposure, or error-contract change. Existing focused surface, API error, and Stage-B contract checks remain green, and rendering continues to use typed nodes/text content for the reviewed surfaces.

### Scope and regressions — PASS

`git diff --name-only 296010d..3708259` contains only:

- `app/static/app.js`
- `tests/stage_b_generation_surface_harness.js`
- `task-3-fix-report.md`

`git diff --check` passes. The pre-existing untracked review files were preserved.

## Fast local verification

- `node tests/stage_b_generation_surface_harness.js` — **16/16 passed**
- `node --check app/static/app.js` — **PASS**
- `py -3.12 -m pytest -q tests/test_ai_reference_no_source.py tests/test_evidence_guidance.py tests/test_evidence_coach.py tests/test_task3_review_contracts.py` — **50 passed**
- `py -3.12 -m pytest -q tests/test_api_error_contract.py tests/test_stage_b_api_contract.py` — **53 passed**
- `node tests/task_2_fix_behavior_harness.js` — **PASS**
- `node tests/generation_recovery_behavior_harness.js` — **PASS**
- `node tests/document_evidence_ux_behavior_harness.js` — **PASS**
- `git diff --check 296010d..3708259` — **PASS**

No real Provider, Search, transport, deployment, B3, or long-running Chromium evaluation was run.

## Final decision

**PASS.** The previously reported empty-required-list contract failure is fixed, optional evidence and optional `suggested_questions` semantics are preserved, and no raw-leak or scope regression was found in the scoped commit.
