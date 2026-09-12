# B2 Task 3 implementer report

Date: 2026-09-12

## Scope and TDD order

Implemented only Task 3 from the approved Stage B plan. Fresh deterministic RED tests were added before production edits. The RED run was:

```text
py -3.12 -m pytest -q tests/test_ai_reference_no_source.py tests/test_evidence_guidance.py
3 failed, 6 passed
```

The three genuine failures covered missing explicit AI-reference provenance and unsupported assertive claims in AI reference and Evidence Action Card output. After the minimum fix, the updated tests passed.

## Implementation

- AI reference output now always carries visible, application-owned `AI参考/待验证` provenance and states that it is not research, market, or user fact.
- Obvious unsupported assertive research, market, and user claims are rejected with the existing safe structured-output error before persistence.
- Evidence guidance applies the same unsupported-claim boundary and normalizes persisted disclosure to the application-owned optional-guidance warning.
- Evidence guidance remains optional: Action Cards are not sources, and no source is created when evidence is absent.
- Action Cards remain fail-closed only when required fields are missing; `suggested_questions` is optional and empty lists still render a complete actionable card with safe UI copy.
- Fake Chromium assertions now cover explicit AI provenance and all required Action Card labels.

## Verification

Completed with local deterministic fixtures, fake providers, and intercepted loopback transport only:

```text
py -3.12 -m pytest -q tests/test_ai_reference_no_source.py tests/test_evidence_guidance.py tests/test_evidence_coach.py
12 passed

py -3.12 -m pytest -q tests/test_task3_review_contracts.py
38 passed

node tests/stage_b_generation_surface_harness.js
15 passed, 0 failed

node tests/generation_recovery_behavior_harness.js
PASS

node tests/document_evidence_ux_behavior_harness.js
PASS
```

The requested fake Chromium runner was attempted, but it did not complete within the bounded wait and was stopped. Its known legacy blocker is the fixture imported from `_solution_payload()`, which returns 2 candidates while the existing B2 contract requires exactly 3 complete candidates. AI-reference and Evidence guidance were reached/passed in the prior run; the runner is recorded as timeout/skip for this task and was not rerun or modified. No real external connection was made.

## Exclusions and worktree

No real Provider, Search, transport, deployment, or B3 evaluation was run. No unrelated production or fixture files were changed. The pre-existing untracked `task-2-rereview2.md` is intentionally preserved and excluded from the focused commit.
