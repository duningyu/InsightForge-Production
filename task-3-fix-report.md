# Task 3 Fix Report

## Finding fixed

The frontend Action Card DTO adapter now fails closed when any required list is missing, non-array, empty, over-sized, or contains empty items. In particular, `who_or_where`, `action_steps`, `acceptable_artifacts`, and `fill_template` cannot be empty arrays. Existing required text-field validation remains unchanged.

The optional `suggested_questions` list still accepts an empty array. No backend validator, Evidence persistence behavior, no-source behavior, provenance copy, or raw-leak boundary was changed.

## Changes

- `app/static/app.js`: reject empty required string lists in `viewStringList()`.
- `tests/stage_b_generation_surface_harness.js`: add a fake-DOM regression for each required Action Card list; assert no card and no placeholder success text are rendered.

## Verification

- Red regression before the production fix: `who_or_where: []` rendered one Action Card.
- `node tests/stage_b_generation_surface_harness.js` — 16/16 passed.
- `node --check app/static/app.js` — passed.
- `py -3.12 -m pytest -q tests/test_ai_reference_no_source.py tests/test_evidence_guidance.py tests/test_evidence_coach.py` — 12 passed.
- `py -3.12 -m pytest -q tests/test_task3_review_contracts.py` — 38 passed.
- `py -3.12 -m pytest -q tests/test_api_error_contract.py tests/test_stage_b_api_contract.py` — 53 passed.
- `node tests/generation_recovery_behavior_harness.js` — passed.
- `node tests/document_evidence_ux_behavior_harness.js` — passed.

All runs used local/fake/intercepted test paths. No real Provider, Search, transport, deployment, B3, or long-running Chromium flow was run.
