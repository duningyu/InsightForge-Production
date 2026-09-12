# F1/F2 scoped fix report — 2026-09-12

Implemented the remaining F1/R1 and F2/R4 counterexamples from `r1-r4-rereview.md` in the current InsightForge worktree. The bounded checks below pass. This is scoped implementation evidence, not whole-branch or deployment approval.

- Worktree: `E:\AI_Projects\_deploy\insightforge_managed_multi_model_v1\worktree\InsightForge`.
- Branch: `deploy/railway-stage-b`.
- Starting HEAD: `7a4a0a8daf5f3ec6aa0111cfc08e1e14e87cae05`.
- Implementation commit message: `fix: close F1/F2 serialized-value leaks and scope exclusions`.
- RED evidence: [f1-f2-red-evidence.md](f1-f2-red-evidence.md).

## F1 / R1

Minimally extended the existing matching expressions in `app/services/generation_contracts.py` and `app/static/app.js` consistently:

- Authorization permits quotes around the serialized key and Bearer value.
- Provider diagnostic markers include `provider_raw`.
- A serialized message-envelope header containing `type: message` and `role: assistant` is rejected.

The existing recursive value checks and existing generation/public/replay consumers remain in use. No new persistence mechanism, endpoint, or output schema was introduced.

The three exact synthetic rereview strings are shared fixtures. Tests cover reference generation before persistence, including list, uncertainty notice, and disclosure fields; guidance scalar/list/disclosure, solution summary, and document content validators; actual reference API POST/GET and idempotent replay; and direct service GET/replay after injecting a legacy stored value into temporary SQLite. API failures return the owned `MODEL_OUTPUT_CONTRACT_FAILED` response without echoing the synthetic private value. Invalid new generation leaves no result row; invalid legacy replay creates no replacement row.

Frontend tests invoke actual reference, guidance, solution, and document workspace adapters. The reference renderer and document editor reject each fixture. Ordinary JSON/prose controls survive reference generation/load/replay and all four frontend adapters; the reference renderer and document editor retain ordinary content. Controls include ordinary `type: message`, `role: assistant`, and non-Bearer Authorization examples, plus prose mentioning provider_raw.

## F2 / R4

`documentAddsNonGoal` now accepts the explicit negative phrases `不会支持` and `不集成`. A non-goal section only grants an implicit exclusion to a bare listed excluded term (or a list of such terms). Narrative assertions receive the normal clause check, including assertions on the heading line itself. This removes the heading-based exemption for positive commitments such as `支付功能将在本期完成` without adding another list of positive verbs.

Tests exercise both version-shaped and saved-draft-shaped content through the actual workspace adapter and editor: the two honest negative phrases, negatives beneath a non-goal heading, a positive completion promise beneath/in that heading, a positive support control, and mixed negative/positive clauses. Honest content remains in the enabled editor; rejected content clears and disables it. These tests do not claim deletion from the database or new backend semantic scope validation.

Selected identity, inherited content, and selected page checks were not removed or relaxed. Existing identity/page negative checks pass, as do the existing selected-B generated and API-persisted PRD/TechDoc frontend acceptance checks. Existing optional reference and mandatory Action Card controls also pass.

## TDD evidence

The test-driven-development skill guided test-first execution. All relevant RED observations preceded production edits:

- Generation validators: 24 genuine new assertion failures across the three rereview strings and eight value positions; ordinary controls passed.
- Corrected isolated API/service run: 15 failed in 14.14s, all expected wrong-status or missing-exception assertions; external connection attempts 0.
- Actual JS harness: 152 passed, 50 failed. Thirty failures expose value leaks and twenty expose negative wording/heading scope defects. Existing selected identity/page checks passed.

The evidence file records commands and captured output. It separately identifies early test setup errors involving missing participant context and an incorrectly placed idempotency key; those errors are not counted as genuine RED evidence. The corrected tests set participant `test` and send the idempotency key in the request body.

## Completed bounded verification

Final verification after the request to run only the new focused test and existing harness:

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_f1_f2_rereview_fixes.py
node tests/whole_branch_fix_harness.js
```

Exact final results: **15 passed in 12.69s, exit 0; EXTERNAL_CONNECTION_ATTEMPTS=0**. Existing JS harness: **SUMMARY passed=202 failed=0, exit 0**. No further test runs followed.

The already-completed earlier run was:

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_f1_f2_rereview_fixes.py tests/test_whole_branch_fixes.py
```

Result: **163 passed in 91.45s (0:01:31), exit 0; EXTERNAL_CONNECTION_ATTEMPTS=0**.

```powershell
node tests/whole_branch_fix_harness.js
node --check app/static/app.js
git diff --check
```

Results: **JS harness 202 passed, 0 failed**; standalone Node syntax check exit 0; diff whitespace check exit 0. Git reported only its existing LF-to-CRLF conversion notices. The Python selection also invokes this JS harness, so these are not disjoint test counts.

The local runner clears provider/search configuration and blocks outbound non-loopback sockets. New API tests stop the local async worker and use deterministic fake generation with temporary databases. No broad suite, real Provider, Search, deployment, push, or browser/layout acceptance was run. R5 and its artifacts were not changed. Pre-existing untracked review files remain outside the implementation commit.

The value guard remains a bounded recognizable-marker check, not a general secret detector or parser for all encoded/obfuscated transport formats. The scope guard remains lexical, not semantic proof. The concrete rereview counterexamples are fixed with regression evidence; no broader security, model-quality, or product approval is claimed.
