# Whole-branch review: B1 + B2

## Verdict: FAIL

Reviewed on 2026-09-12. Do not approve B1+B2 as engineering-ready or product-accepted at this head. There are independently reproduced contract/UI failures in the reviewed branch, in addition to the separately documented baseline failures. Scoped task PASS reports do not establish whole-branch acceptance.

- Baseline: `e0e928674e33f892b6892c43c383505666771e27`.
- Head: `dbc27d814b8aceaee54a0a46384589e7e4db555c` (`dbc27d8`).
- Worktree: `E:\AI_Projects\_deploy\insightforge_managed_multi_model_v1\worktree\InsightForge`.
- Review only: no application, test, configuration, or existing report was edited. This report is the only added worktree file. No commit, deployment, B3 evaluation, real Provider, Search, or external transport was performed.
- At the user's follow-up, the long regression command was interrupted. Its partial progress is NOT counted as a passing suite. Conclusions below use completed checks, direct local reproductions, source evidence, and explicitly attributed historical evidence.

Severity: P1 = blocks the required safety/core workflow contract; P2 = material correctness or acceptance-evidence gap; P3 = hygiene/documentation. Findings below are outstanding obligations of this branch, not a claim that every underlying weakness first appeared after the baseline.

## Materials and provenance

Reviewed the supplied package `.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/review-e0e9286..dbc27d8.diff`, `STAGE_B_AI_SURFACE_MATRIX.md`, the B1 output-contract and B2 generation-UX plans, the B3 authorization-boundary plan, both SDD ledgers, available task reports/fix reports/reviews/re-reviews in both Stage B SDD directories, and root-level task 2/3/5 follow-up reports/reviews. Checked the actual head implementations and relevant test fixtures against these claims.

Package SHA256: `0583EFE51AB875BD81DEAD20742D1A3EEBD2DEA2A5CC6769F348FFCC3ABB5F07`.

The package and `git diff e0e9286 dbc27d8` have identical file/index/addition/deletion lines: **6067/6067 lines match**. Their hunk context differs, so byte-for-byte diff-text equality is not claimed. The range changes 64 files. The six pre-existing untracked review files were preserved.

Historical evidence is treated as historical, not rerun evidence. In particular, Task 4's fix report references an earlier review that is not present among the current root files; the available exact-three red artifact and re-review were examined, without inventing the missing original review. Task 5's latest scoped fake-layout PASS does not override the broader Chromium requirement in the approved B2 plan.

## Blocking findings

### R1 — P1 — Raw provider material can bypass the new public boundary inside allowed strings

**Locations:** `app/services/generation_contracts.py:104`, `:135`, `:144`, `:245`; `app/services/ai_reference.py:86-110`, `:112`; `app/static/app.js:466-471`, `:503-514`, `:2856-2861`.

The projectors allowlist field names and types, not their contents. A schema-valid reference item containing a serialized provider envelope is accepted, saved as `completed`, returned by the service's public read representation, and rendered verbatim as a suggestion. DOM `textContent` prevents HTML execution; it does not prevent disclosure of raw JSON, prompts, or credential-bearing text. The closed error-message registry fixes one channel, not this value channel.

Completed local reproduction, using a fake runtime and temporary SQLite database:

```text
possible_target_users = ['{"choices":[{"message":{"content":"REVIEW_SYNTHETIC_SECRET"}}]}']
AIReferenceService.generate(...) -> completed
AIReferenceService.get(...) -> raw marker remains in public result
RAW_ALLOWED_STRING_PERSISTED_PUBLIC completed True
```

A second fake-DOM probe put the same item in an otherwise complete seven-category reference and exercised the actual `renderAIReference()`:

```text
RAW_STRING_RENDERED true
```

There is another instance of this same value-trust gap: `failure_public()` copies arbitrary strings from `quota_status`, `failure_stage`, `fixture_origin`, and `fixture_disclosure`. A completed direct probe returned `FAILURE_METADATA_ECHO True` for a synthetic private marker in `failure_stage`. Earlier fixes deliberately retained these auxiliary fields; this whole-branch review does not treat that scoped exclusion as satisfying the overall no-leak contract.

**Impact:** The required raw-leak safety boundary is bypassable without extra keys or a schema error. This demonstrates a disclosure path, not discovery of an actual credential or proof of access to secrets the model never received.

**Required before approval:** Add negative cases for raw envelopes/private markers inside allowed scalar/list/disclosure values at generation, persistence/replay, public API, and rendering boundaries. Reject forbidden raw/debug output rather than turning it into user content; derive bounded failure metadata from application-owned enums/copy. Preserve valid ordinary prose. Existing denylist tests must not be described as comprehensive until these value positions are exercised.

### R2 — P2 — Valid partial AI references now fail at the frontend

**Locations:** `app/static/app.js:473-478`, `:503-509`; `app/services/generation_contracts.py:135-141`; `app/schemas.py:114-122`.

The Task 3 Action Card fix made `viewStringList()` reject an empty required list. `toAIReferenceViewModel()` uses that helper with its default `required: true` for every reference category. The actual reference schema/domain contract allows empty categories and requires only at least one substantive category. Thus the shared-helper change silently strengthens the unrelated reference contract to require all seven lists nonempty.

Completed differential probe:

```text
validate_reference(AIReferenceDraft(possible_target_users=['local test'])) -> accepted
PARTIAL_REFERENCE_BACKEND_ACCEPTED True
complete reference with research_directions=[] -> frontend rejection
PARTIAL_REFERENCE_UI 这次没有生成可用建议，请重新尝试。
```

**Impact:** A successful, persisted, contract-valid reference becomes an unusable generation/load result. Retry can return the same valid persisted result and remain unusable. This is an introduced cross-surface regression, not one of the baseline failures below.

**Required before approval:** Separate reference-category optionality from required Action Card lists; test partial-reference generation, persisted load, and retry as well as entirely empty rejection. Keep the four Action Card actionable lists mandatory.

### R3 — P1 — Generated TechDoc lacks content that its own frontend now requires

**Locations:** `app/services/generation.py:423-444`, `:518-525`; `app/static/app.js:649-677`, `:2759-2762`; `tests/test_v3_solution_api.py:139-168`.

The frontend's selected-snapshot gate requires every `snapshot.mvp.pages` value to occur literally in PRD **and TechDoc**. PRD now emits selected pages (`generation.py:269`, selected MVP section), but TechDoc collects/emits features, flow, inputs/outputs, and risks without collecting/emitting selected pages. A legitimate unique MVP page can therefore be absent from a backend-accepted TechDoc and cause the frontend to reject it after persistence.

Completed deterministic-generator probe supplied selected B context with page `UNIQUE_B_PAGE`. The generated TechDoc passed the real required-section validator:

```text
TECHDOC_SECTIONS_PASS True MVP_PAGE_IN_CONTENT False
```

The frontend's `inheritedTerms.some(term => !content.includes(term))` necessarily rejects that content when the same snapshot is current. The selected-B API test checks identity, summary, value, rationale, problem/user, the first flow step and first feature, but **not MVP pages or the actual frontend adapter**. It also directly sets `validation_status='passed'` before confirmation; its handoff success is a controlled inheritance test, not end-to-end validation acceptance.

**Impact:** A normal solution-to-TechDoc path can save a document and then show generation failure/empty editor. This is a backend/frontend integration defect missed by separately passing tests.

**Required before approval:** Align the inherited DTO/content contract for both document types, and run locally generated B documents through the actual frontend adapter. Include unique pages and all required inherited fields; distinguish persistence success from UI acceptance and validation success.

### R4 — P2 — The scope guard rejects honest non-goal statements

**Locations:** `app/static/app.js:640-647`, `:664-667`, `:677`.

`snapshotNonGoalTerms()` strips negation from explicit non-goals, then `documentMatchesSelectedSnapshot()` rejects any occurrence of the resulting term anywhere in the document. A correct statement of an excluded feature is therefore treated as scope expansion.

Completed fake-DOM probe with current snapshot `explicit_non_goals=['不做支付']`, selected title `SELECTED_B`, and page `PAGE_B`:

```text
Document '# SELECTED_B\nPAGE_B\n正常方案内容':
  CONTROL_DOC_ERROR null EDITOR_LENGTH 26
Append only '\n明确不做支付。':
  HONEST_EXCLUSION_DOC_ERROR {"code":"DOCUMENT_CONTENT_INVALID"} EDITOR_LENGTH 0
```

**Impact:** Correct documents and user-edited drafts can disappear from the editor because they explicitly document the approved scope boundary. Conversely, literal token checks are not proof of semantic inheritance or absence of scope drift.

**Required before approval:** Validate structured scope/identity independently of prose, or distinguish exclusions from positive feature commitments. Cover both legitimate non-goal sections and actual added-scope cases; do not remove scope checks altogether.

### R5 — P2 — The required browser acceptance gate remains unproved

**Locations:** `docs/superpowers/plans/2026-09-12-stage-b-ai-generation-ux.md:58`; `tests/stage_b_generation_surface_harness.js:67-72`, `:410-480`, `:755`; root `task-5-review.md`, `task-5-rereview.md`, `task-5-rereview2.md` and Task 5 reports.

The approved plan explicitly requires the existing Chromium mechanism at 1366/1440 desktop widths and 125%/150% equivalents, covering all six surfaces. Current Task 5 layout evidence comes from custom fake elements, a subset CSS parser, and assigned `_layout` values. The final mutation check is useful and genuinely rejects its targeted min-width regression, but it does not execute browser layout, wrapping, fonts, actual control geometry, clipping, or zoom. The refresh case is explicitly a local-recovery simulation, not proof of fresh-browser/server persistence.

Historical Task 2 reports a separate screenshot run; later reports record the dedicated browser flow timing out on a legacy two-candidate fixture. Neither is a completed current-head all-surface browser gate. This review did not start that long flow, in accordance with the user's stop-long-tests instruction.

**Required before approval:** Obtain bounded local-only Chromium acceptance evidence with complete fake responses for the approved viewports and actual persisted reload, or explicitly obtain a scope change. Retain the fake harness as unit-level regression coverage; do not relabel it browser/product acceptance.

## Cross-cutting assessment

| Requested area | Assessment at this head |
|---|---|
| Raw leakage / secret values | FAIL: R1. No real secret was accessed or exposed by this review; all probe markers are synthetic. No comprehensive credential-content scan was completed. |
| Silent raw fallback | Shared structured parser rejects malformed/prose/multiple-root output rather than returning it as fallback. No new explicit parser raw fallback found; R1 bypasses the protection via schema-valid strings instead. |
| Schema/domain boundaries | Exact-three schema/prompts and structured-error handling improved; completed focused tests pass. R2/R3 show inconsistent backend/render contracts. Stored reference `_row()` projects but does not rerun domain validation, so projection alone must not be called complete replay validation. |
| Fake-success UI | Terminal solution polling/restore validation precedes success in inspected fixes; focused harness passes. R3 still separates backend persistence from frontend acceptance. A successful generation or handoff fixture is not proof that content passed independent validation. |
| Stale state / retry | Completed harnesses cover pre-await clearing, malformed terminal recovery, cancellation-related recovery behavior, and stale-reference retry. R2 can strand a valid stored result. No claim of exhaustive project-switch/race coverage. |
| Solution/document inheritance | FAIL: R3/R4. Selected identity/value/flow additions exist, but substring checks and first-item API assertions are insufficient whole-path acceptance. Existing generic document boilerplate is not evidence of selected-domain architecture. |
| Public debug route | PASS for the registered-route test at current head; four-test focused run below completed. This is not an audit of an externally deployed route inventory. |
| Stage A regressions | Single/partial read-only solution detail and recovery harnesses pass. R2 is a cross-surface regression introduced by a shared helper. Broad Stage A/full-suite status is not freshly established. |
| Scope creep | No unrelated deployment/provider/search implementation identified in the reviewed diff. B3 plan documentation is present; no B3 evaluation was executed or authorized here. Existing fixed document boilerplate is an inheritance limitation, not a new external feature implementation. |
| Evidence quality | FAIL for whole-branch acceptance: R5, uncompleted full regression run, residual baseline gate, and narrow fixtures. Historical scoped PASS and TDD summaries are not independently rerun full-branch proof. |

## Completed local checks and limits

All test/probe responses were fake/deterministic; no live external service was used. Python review runners removed provider-related environment settings and/or blocked socket connections. The completed focused pytest run recorded **0 external connection attempts**. The interrupted broad run cannot supply a final attempt counter or aggregate pass result; no successful external connection was permitted by its guard.

| Completed command/check | Result |
|---|---|
| `node --check app/static/app.js` | PASS |
| `node tests/stage_b_generation_surface_harness.js` | 22 passed, 0 failed; fake DOM/CSS model only |
| `node tests/task_2_fix_behavior_harness.js` | PASS |
| `node tests/solution_detail_behavior_harness.js` | PASS; read-only partial detail, focus restoration, zero requests |
| `node tests/generation_recovery_behavior_harness.js` | PASS |
| `node tests/document_evidence_ux_behavior_harness.js` | PASS |
| Guarded `pytest -q --tb=short -p no:cacheprovider tests/test_task4_exact_three_contract.py tests/test_stage_b_api_contract.py::test_stage_b_registers_no_public_debug_route` | **4 passed in 1.59s**, external connection attempts 0 |
| In-memory fake-DOM / temporary-database probes R1-R4 | Completed; counterexamples reproduced as quoted above; no source/test edits |
| Package changed-line/blob-identity comparison | PASS, 6067 lines match |
| `git diff --check e0e9286 dbc27d8` | FAIL, P3: `task-5-fix-report.md:44: new blank line at EOF` |

The broad 35-file guarded local regression command was interrupted with Ctrl-C after partial progress, per the user's follow-up; its session exited and no matching review Python process remained. It is **INCOMPLETE**, not PASS. An earlier collection attempt used the matrix's nonexistent `tests/test_v3_snapshot_api.py`; it ran no tests. The corrected broad command used `tests/test_v3_snapshot_transaction.py`, but was subsequently stopped. No fresh full-suite count is asserted.

The requesting-code-review skill supplied the review/severity/evidence structure; it did not authorize implementation changes. No source fix was attempted. No dedicated secret scanner result, current Chromium success, B3 result, deployment readiness, or real-model quality is claimed.

## Remaining baseline failures — separate from R1-R5

These are **historically established baseline failures**, not newly attributed B1+B2 regressions and not freshly rerun here:

- B1 `task-5-rerun-report.md` at `4f67c54` reports **827 passed, 12 failed, 1 warning, 783.42s** after fixing five B1-attributed failures.
- B1 `task-5-rerun-review.md` independently reports reproducing the disputed 12 failures against the **exact approved baseline `e0e9286`**, using an isolated export. That establishes baseline attribution for these cases; it is not a full baseline-suite census.
- Their continued current-head status is **not freshly established by this review**. Do not copy the `4f67c54` aggregate count onto `dbc27d8`, and do not call the repository-wide engineering gate green.

Exact historical failures:

```text
tests/test_api.py::test_upload_size_limit_is_enforced_before_ingestion
tests/test_beta_analytics_ui.py::test_consent_ui_and_client_payload_are_privacy_bounded
tests/test_next_action.py::test_project_next_action_follows_persisted_priority_order
tests/test_next_action.py::test_home_next_action_uses_tour_completion_only_after_no_incomplete_project[False-start_example_tour]
tests/test_next_action.py::test_home_next_action_uses_tour_completion_only_after_no_incomplete_project[True-create_new_idea]
tests/test_next_action.py::test_document_health_must_exist_and_be_current_before_guidance_advances[missing]
tests/test_next_action.py::test_document_health_must_exist_and_be_current_before_guidance_advances[stale]
tests/test_next_action.py::test_canvas_edit_routes_to_snapshot_review_instead_of_impossible_document_confirmation
tests/test_next_action.py::test_snapshot_health_without_open_proposal_routes_to_reconfirmation_that_repairs_health
tests/test_next_action.py::test_snapshot_review_selects_newest_current_open_proposal_for_exact_focus
tests/test_next_action.py::test_completed_handoff_must_match_current_snapshot_and_confirmed_document_versions
tests/test_user_feedback_completion.py::test_document_draft_commit_rejects_a_stale_selected_base_version
```

Recorded signatures: upload-limit and stale-draft expectations differ from generic safe public error text; beta-consent test expects the missing `InsightForge Closed Beta` branding string; nine next-action cases fail in handoff-export setup with HTTP 422 before reaching their intended assertions. The warning is a Windows GBK subprocess-reader UnicodeDecodeError in the guidance-navigation test. Do not interpret those nine setup failures as independently verified defects in every downstream next-action rule.

The initial B1 gate's three account-lifecycle and two zero-candidate failures were fixed and absent from the later reported rerun; they are not listed as remaining baseline failures. Dedicated secret scanning was historically SKIP; the Dockerfile/.dockerignore audit is not a credential-content scan.

## Final disposition

**FAIL — changes and fresh bounded evidence are required before whole-branch approval.** Resolve R1-R4, complete or explicitly rescope R5, retain baseline failures as a separate gate/waiver decision, and rerun only authorized local/fake checks. The stopped run and historical reports do not justify PASS. This review grants no authority for real Provider/Search/transport, deployment, or B3.
