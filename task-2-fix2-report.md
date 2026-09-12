# Task 2 fix 2 report

Parent: `e4a7dae`

## Scope

Fixed only the two residual findings from `task-2-rereview.md`:

1. A restored generation result can no longer render a successful terminal state before complete solution DTO validation.
2. The handoff adapter now fails closed when readiness evidence is incomplete or does not match the current project/snapshot context.

No Provider, Search, transport, deployment, or B3 path was invoked.

## Changes

### Recovery / polling generation

- `restoreGenerationReference()` validates a `SUCCEEDED` response with the existing strict `toSolutionsViewModel()` before `loadProject()`, state exposure, progress rendering, or polling.
- An invalid terminal response is converted to an explicit `FAILED` state with `MODEL_OUTPUT_SCHEMA_INVALID`, preserves the project, and shows recovery UI without closing the progress dialog.
- `renderGenerationProgress()` applies the same defensive terminal gate, so a raw malformed `SUCCEEDED` value cannot produce success copy or close the modal through another caller.
- Exported the existing restore function through the test-only hook so the regression exercises the real recovery entry point.

### Handoff readiness

The adapter now validates the fields actually returned by `HandoffService` in `app/services/handoff.py`:

- explicit top-level `canvas_version`, `snapshot`, and `unresolved_acknowledgement` keys;
- project id equals `state.currentProjectId`;
- null/non-null snapshot parity with current context;
- snapshot id and version equal the current `state.snapshot` id/version;
- both `prd` and `techdoc` document keys are present;
- every present document has explicit `health_status === "current"`.

Missing document health is no longer converted to `"current"`. No UI-only fields such as `features` or `non_goals` were promoted to required backend DTO fields; those remain derived from the current snapshot as before.

The stage-B surface fixture was updated only to include the real current snapshot identity/context required by the stricter adapter.

## TDD evidence

- Added the restore regression before the production behavior fix. After exposing the real test hook, the old path reproduced the failure: malformed restored `SUCCEEDED` closed the modal and proceeded into project loading.
- Added handoff regressions for missing health, missing real DTO field, project mismatch, snapshot id mismatch, and snapshot version mismatch.
- The valid current-project/current-snapshot fixture remains accepted.

## Verification

All commands were local/fake-only:

```text
node tests/task_2_fix_behavior_harness.js                         PASS
node tests/generation_recovery_behavior_harness.js                 PASS
node tests/stage_b_generation_surface_harness.js                   PASS
node tests/solution_detail_behavior_harness.js                     PASS
node tests/document_evidence_ux_behavior_harness.js                PASS
node --check app/static/app.js                                     PASS
py -3.12 -m pytest -q tests/test_v2_handoff.py tests/test_v3_handoff_and_tools.py tests/test_v3_ui_evidence_documents_handoff.py tests/test_v4_document_evidence_ux.py
24 passed
```
