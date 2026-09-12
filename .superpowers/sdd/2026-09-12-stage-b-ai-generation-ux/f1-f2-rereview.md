# F1/F2 scoped rereview — PASS

Reviewed 2026-09-12 on branch `deploy/railway-stage-b`, HEAD `34ba419ea06a9bbc3fad31b9e380ab8ab63004b7`.

Scope: prior whole-branch findings R1–R4, the remaining F1/F2 counterexamples in `r1-r4-rereview.md`, and the fixes described in `f1-f2-fix-report.md`. Inspected the concentrated `7a4a0a8..34ba419` production/test diff and relevant current consumers. No new whole-branch review, real Provider, Search, deployment, broad regression suite, or browser/layout acceptance run.

Worktree: `E:\AI_Projects\_deploy\insightforge_managed_multi_model_v1\worktree\InsightForge`.

## Disposition

| Obligation | Verdict | Fresh evidence |
|---|---|---|
| F1 / R1: quoted JSON Authorization, provider_raw, message envelope | **PASS for the specified counterexamples** | All three fail generation validators, real in-process reference API generation, legacy stored reference GET/replay, and actual frontend adapters/renderers. Safe errors do not echo synthetic private values. |
| R1: ordinary JSON/prose and bounded failure metadata | **PASS for the named controls** | Eight ordinary controls survive reference generation/load/idempotent replay and all four frontend adapters. Five direct metadata tests retain only owned values/copy. |
| R2: partial references and mandatory Action Card lists | **PASS** | Partial reference service generation/load/replay and frontend load/generate/retry pass. Entirely empty reference and each of the four empty mandatory Action Card lists remain rejected by the frontend. |
| R3: selected-B PRD/TechDoc inheritance, including pages | **PASS for the reported defect** | Both deterministic generated documents and API-generated/persisted documents reach the actual frontend adapter/editor with both unique selected pages. No forced backend validation success. |
| F2 / R4: honest exclusions versus positive scope commitments | **PASS for the specified counterexamples** | `不会支持` and `不集成` remain in the enabled editor; positive completion commitments under/in non-goal headings fail and clear/disable the editor, for both version-shaped and draft-shaped inputs. |
| R4: selected identity/page checks | **PASS** | Wrong selected title and missing selected page still fail the actual workspace adapter; the required inherited-term checks remain in source. |

No outstanding failure was reproduced within this bounded selection. This closes the specified F1/F2 counterexamples and supports scoped R1–R4 acceptance. It is not whole-branch, security-completeness, or product/deployment approval. R5 and historical baseline failures remain outside this review.

## F1 / R1 evidence

Exact shared inputs, using synthetic markers only:

```json
{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}
{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}
{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}
```

The backend matcher at `app/services/generation_contracts.py:71` now permits serialized quotes around Authorization/Bearer, includes `provider_raw`, and recognizes the specified message header. The frontend matcher at `app/static/app.js:468` carries the same additions. These feed existing recursive value checks; they are not merely tests against a replacement regex.

| Boundary exercised | Observed result for all three inputs |
|---|---|
| Reference generation: category list, uncertainty notice, fixture disclosure | `StructuredOutputContractError`; no persisted reference row, no raw value in public exception payload, no retained exception cause/context. |
| Guidance scalar/list/disclosure, solution summary, document content validators | Typed rejection at each of the five positions. Together with the three reference positions, **24 cases passed**. |
| POST `/api/projects/project_insightforge_demo/ai-reference` with fake runtime | HTTP 503, owned `MODEL_OUTPUT_CONTRACT_FAILED`, no `SYNTHETIC_REREVIEW` in response, zero result rows. |
| Legacy stored reference: API GET and idempotent POST replay | HTTP 503 with the same safe error; no private marker returned; row count remains one, with no replacement result. |
| Legacy stored reference: direct service GET and idempotent generation replay | Typed rejection without private marker in public payload; row count remains one. |
| Actual reference/guidance/solution/document frontend adapters | Rejected in all eight tested positions per input. |
| Actual reference renderer / document editor | No raw reference rendered; reference shows failure copy. Document editor is empty and disabled. |

The API and stored replay assertions are in `tests/test_f1_f2_rereview_fixes.py:19` and `:34`: **15 cases passed**. They use temporary seeded SQLite, actual `create_app`/`TestClient`, participant `test`, a fake runtime, and a stopped async worker. The storage corruption is deliberate fixture setup; rejection does not delete the legacy row. Source confirms generation checks precede insertion (`app/services/ai_reference.py:86`, `:98`), and both GET and idempotent replay re-enter `_row`/`reference_public` (`:76`, `:113`; `generation_contracts.py:178`).

The persisted API workflows above are reference workflows. Guidance, solution and document results for these exact three strings are validator/frontend evidence, not claims that every corresponding persisted API workflow was rerun.

Ordinary controls include prose mentioning choices/provider/debug/API key, `{"quantity":3}`, ordinary `type: message` JSON, ordinary `role: assistant` JSON, non-Bearer Authorization JSON, and prose mentioning `provider_raw`. All **eight** pass reference service generation/load/idempotent replay (`tests/test_whole_branch_fixes.py:112`). The frontend harness preserves their values in all four adapters and in reference rendering/document editing (`tests/whole_branch_fix_harness.js:82`, `:90`). Empty optional reference categories remain empty rather than causing rejection.

The **five** direct failure-metadata tests at `tests/test_whole_branch_fixes.py:97` and `:103` pass. Arbitrary values in `quota_status`, `failure_stage`, `fixture_origin`, and `fixture_disclosure` are not echoed; recognized quota/origin values and fixed fixture disclosure remain. `failure_public` continues to derive error copy from the owned registry. Prior sync/async failure replay evidence is historical and was not rerun here.

## F2 / R4 evidence

`documentAddsNonGoal` at `app/static/app.js:671` adds the two explicit negative forms and limits heading-based implicit exclusion to bare excluded list terms. A heading no longer exempts narrative commitments merely because they lack an enumerated positive verb. Selected title and inherited-term checks still execute at `:702`; the workspace adapter checks both selected version and draft at `:724`.

The actual frontend harness uses selected title `SELECTED_B`, page `PAGE_B`, and non-goals `不做支付` / `不包含广告`. Each tested document retains the selected title/page prefix. For each row below, both version-shaped and saved-draft-shaped inputs were checked through the actual adapter and editor:

| Added content | Actual result |
|---|---|
| `本期不会支持支付。` | Accepted; full content retained; editor enabled. |
| `本期不集成支付。` | Accepted; full content retained; editor enabled. |
| Both negative statements as bullets below `## 非目标` | Accepted; full content retained; editor enabled. |
| `## 非目标` followed by `- 支付功能将在本期完成。` | Rejected; editor empty and disabled. |
| `## 非目标 支付功能将在本期完成` | Rejected; editor empty and disabled. |
| `本期支持支付。` | Rejected; editor empty and disabled. |
| `本期不集成支付，但支付功能将在本期完成。` | Rejected; editor empty and disabled. |
| Negative bullet followed by positive completion bullet below `## 非目标` | Rejected; editor empty and disabled. |

These are **32 passing F2 harness checks** (eight narratives × two input shapes × adapter/editor checks), a subset of the 202-check harness. Existing original exclusion, bare non-goal lists, mixed positive/negative clauses, and section-transition controls also pass. Wrong identity (`# OTHER\nPAGE_B`) and missing page (`# SELECTED_B\nOTHER_PAGE`) each return null (`tests/whole_branch_fix_harness.js:145`).

This demonstrates frontend acceptance/rejection, not deletion from storage or new backend semantic scope enforcement.

## Preserved R2 / R3 evidence

- R2: eight reference service controls pass generation/load/idempotent replay. The actual frontend harness exercises partial-reference load, generation and retry, requires two mocked POSTs, rejects an entirely empty reference, and rejects each empty `who_or_where`, `action_steps`, `acceptable_artifacts`, and `fill_template` list.
- R3: `test_generated_selected_b_document_passes_actual_frontend_adapter[prd/techdoc]` passes with distinct title, summary, core idea, target user, problem, value, rationale, two flow steps, two features, and `UNIQUE_B_PAGE_1`/`UNIQUE_B_PAGE_2`. Generated content passes the real required-section validator and actual frontend adapter/editor.
- R3: `test_selected_b_persisted_documents_are_accepted_by_frontend_without_forced_validation` passes after local API candidate generation/selection and PRD/TechDoc generation. Persisted GET content equals generation response content and reaches the actual frontend adapter/editor. Page emissions remain at `app/services/generation.py:327` and `:530`.

The `--document` harness reconstructs the version wrapper with `validation_status: 'not_run'` and current health. These R3 checks prove content/snapshot compatibility and editor acceptance; they do not prove all returned metadata, independent validation approval, confirmation/handoff readiness, or real browser behavior.

## Fresh bounded checks

All commands ran from the reviewed worktree. The inspected local runner clears Provider/Search-related configuration and blocks non-loopback socket connections; local socketpairs are permitted. API tests use in-process transport and temporary databases. Both Python runs completed with **EXTERNAL_CONNECTION_ATTEMPTS=0**.

```powershell
py -3.12 -B -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_f1_f2_rereview_fixes.py tests/test_whole_branch_fixes.py::test_partial_reference_generation_load_and_retry_preserve_ordinary_prose tests/test_whole_branch_fixes.py::test_failure_metadata_uses_only_owned_values tests/test_whole_branch_fixes.py::test_known_failure_metadata_keeps_enum_and_owned_fixture_copy tests/test_whole_branch_fixes.py::test_generated_selected_b_document_passes_actual_frontend_adapter tests/test_whole_branch_fixes.py::test_selected_b_persisted_documents_are_accepted_by_frontend_without_forced_validation
```

**31 passed in 22.55s; exit 0; external connection attempts 0.** Breakdown: 15 F1 API/replay, eight ordinary reference controls, five metadata controls, two generated-document cases, one persisted-document case.

```powershell
py -3.12 -B -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_whole_branch_fixes.py::test_reference_raw_values_rejected_before_persistence tests/test_whole_branch_fixes.py::test_allowed_value_positions_reject_raw_material -k SYNTHETIC_REREVIEW
```

**24 passed, 80 deselected in 8.61s; exit 0; external connection attempts 0.** This selects only the three new strings across eight generation/value positions.

```powershell
node tests/whole_branch_fix_harness.js
node --check app/static/app.js
git diff --check HEAD^ HEAD
```

**Frontend SUMMARY passed=202 failed=0**; syntax and commit whitespace checks passed. The three R3 Python cases invoke the harness's separate `--document` path; test counts describe their respective layers and are not a count of unique end-to-end workflows.

No full-suite/TDD-red rerun was performed. The fix report's earlier 163-test result and RED claims are historical, not this review's fresh evidence. The verification-before-completion skill guided using completed current-head results and retaining these limits.

## Provenance and limits

- Reviewed `r1-r4-rereview.md` SHA256: `F95C4B083F261912A50DA34E2B80649C936F32A785B107742031D36A673A3C0E`.
- Reviewed `f1-f2-fix-report.md` SHA256: `159C27ECE385E3B04F402BBC3AF987C1F5721F33C2ED16E8B7AFC6DE23D938E6`.
- This report is the only authored file. No application/test/configuration edits, commit, push, real Provider/Search, deployment, or R5 work. Existing untracked review files were preserved. This report path is ignored by the repository's existing ignore rules; it was written locally without staging or changing those rules.
- The raw-value check remains a recognizable-marker guard, not a general secret detector or exhaustive parser of encoded/obfuscated formats. The scope check remains lexical, and substring inheritance is not semantic proof. PASS applies to the explicit counterexamples and controls above.

**Final scoped verdict: PASS — the specified F1/R1 and F2/R4 counterexamples are closed at `34ba419`; the focused R2/R3 and identity/page controls remain passing. R5 and whole-branch acceptance are not adjudicated.**
