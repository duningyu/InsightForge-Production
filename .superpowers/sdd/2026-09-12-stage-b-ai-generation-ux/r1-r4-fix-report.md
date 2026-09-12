# Concentrated R1-R4 fix — 2026-09-12

Scope: review findings R1-R4 only, on `deploy/railway-stage-b`, parent `dbc27d814b8aceaee54a0a46384589e7e4db555c`. No architecture rewrite, R5/browser evidence changes, real Provider/Search calls, deployment, or push.

## Changes

- **R1:** reject recognizable provider/debug/raw envelope markers recursively inside allowed values before persistence and at public/read/replay boundaries. Revalidate stored reference and Action Card domains. Guard document versions, drafts, citations and durable replay, plus frontend adapters/rendering. Failure metadata now admits app-owned enums and fixed fixture/recovery copy only; rejected raw text is not interpolated into public errors. Ordinary prose and ordinary non-envelope JSON have positive controls.
- **R2:** omitted AI reference categories become optional empty lists in the frontend, while at least one reference category remains populated. All four Action Card lists remain mandatory. Tests exercise partial generation, stored load and retry through the actual frontend path.
- **R3:** generated PRD/TechDoc content includes separate inherited summary/core idea, selected target user/problem and selected MVP data; TechDoc includes selected MVP pages. Tests generate and persist selected-B documents and pass their content through the actual frontend snapshot adapter/editor path, without forcing validation success.
- **R4:** scope checking distinguishes bounded explicit exclusions/non-goal sections from positive commitments, including repeated mentions, contrasting clauses, new headings and positive content concealed in non-goal headings. Selected identity and page requirements remain enforced.

The TDD, receiving-code-review and verification-before-completion skills guided reproduction before implementation, local diff review, and fresh verification before committing. See [RED evidence](r1-r4-red-evidence.md).

## Final focused GREEN

Executed after all production changes:

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_whole_branch_fixes.py tests/test_stage_b_output_contract.py::test_public_success_fields_cannot_contain_diagnostic_objects tests/test_v2_document_lifecycle.py tests/test_stage_a_safe_fixture.py::test_safe_fixture_returns_substantive_deterministic_outputs_without_provider tests/test_stage_a_safe_fixture.py::test_stage_a_failure_fixture_uses_normal_route_and_retry
```

**126 passed in 72.60s; exit 0; EXTERNAL_CONNECTION_ATTEMPTS=0.**

Also executed successfully:

```powershell
node tests/whole_branch_fix_harness.js
node tests/task_2_fix_behavior_harness.js
node tests/solution_detail_behavior_harness.js
node tests/generation_recovery_behavior_harness.js
node tests/document_evidence_ux_behavior_harness.js
node --check app/static/app.js
git diff --check
```

New JavaScript harness: **118 passed, 0 failed**. Four existing behavior harnesses: **PASS**. Syntax and whitespace checks: exit 0. The pytest selection also invokes the new frontend harness; these counts are not disjoint tests.

Earlier focused regression coverage selected `test_stage_b_output_contract.py`, `test_stage_b_api_contract.py`, `test_task3_review_contracts.py`, `test_task4_exact_three_contract.py`, `test_ai_reference_no_source.py` and `test_evidence_coach.py`: **200 passed, 1 failed in 115.14s**, zero external connection attempts. The sole failure expected malformed reference/card diagnostic objects to be silently projected. Its expectation was updated to the intended safe typed rejection (solution projection still has its no-leak assertion), and that exact test passed in the final 126-test run above. The six-file selection was not rerun or represented as entirely green. No repository-wide suite was started.

## Review and limits

Reviewed the scoped production/test diff; additional document replay/lifecycle and non-goal-heading gaps were reproduced RED and patched before the final GREEN. Existing untracked review documents remain unmodified and outside the commit.

Marker detection is a bounded recognizable-envelope guard, not a general secret detector. Exclusion detection is lexical, not a semantic proof of arbitrary prose. Frontend tests execute the real adapters/render paths with a fake DOM and mocked fetch: they do not constitute R5 browser/layout evidence. Generated-document adapter acceptance does not assert independent document-validator approval or product-wide acceptance. No broad-suite or whole-branch completion claim is made.
