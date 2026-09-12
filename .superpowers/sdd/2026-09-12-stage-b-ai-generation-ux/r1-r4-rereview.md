# R1–R4 rereview — FAIL

Reviewed 2026-09-12 against `whole-branch-review.md`, findings R1–R4 only.

- Branch: `deploy/railway-stage-b`.
- Reviewed HEAD: `7a4a0a8daf5f3ec6aa0111cfc08e1e14e87cae05`.
- Parent/original reviewed HEAD: `dbc27d814b8aceaee54a0a46384589e7e4db555c`.
- Worktree: `E:\AI_Projects\_deploy\insightforge_managed_multi_model_v1\worktree\InsightForge`.
- Inspected the concentrated commit's production/test diff and the relevant current generation, persistence, replay, API, and frontend consumers. The commit changes 15 files, with 651 additions and 15 deletions.
- Source review SHA256 (`whole-branch-review.md`): `462BC971C808E78F49998689D36C8E37FAB5EC2BE31472B54A0C85A22F4762FC`.
- This report is the only added review file. No application, test, configuration, or existing report edits; no commit, push, real Provider, Search, deployment, broad suite, or browser acceptance run.

## Disposition

| Finding | Verdict | Fresh evidence and remaining obligation |
|---|---|---|
| R1 — value-level raw/provider/debug rejection | **FAIL, P1 remains** | Original marker fixtures are rejected, but ordinary serialized authorization and provider envelopes still pass generation, persistence/replay, API, and actual frontend adapters/rendering. See F1. |
| R1 — bounded failure metadata | **PASS for the four named fields** | Application-owned enums/copy replace arbitrary `quota_status`, `failure_stage`, `fixture_origin`, and `fixture_disclosure`. Direct tests, stored sync replay, async polling, and frontend disclosure probe pass. This sub-result does not close R1 overall. |
| R2 — optional reference categories / mandatory Action Cards | **PASS** | Partial references survive generation, persisted load, idempotent replay, and actual frontend generate/load/retry paths. Entirely empty references and empty mandatory Action Card lists remain rejected. |
| R3 — selected MVP pages and inherited document content | **PASS for the reported defect** | PRD and TechDoc now include required inherited terms, including both unique selected-B pages. Deterministic generated and API-persisted content passes the actual frontend workspace adapter/editor. No forced backend validation success. |
| R4 — honest exclusions versus added scope | **FAIL, P2 remains** | The original exclusion case is repaired, but normal negative wording still clears the editor, and positive commitments can pass under a non-goal heading. See F2. |

There are two remaining load-bearing findings, F1 and F2. The passing committed regressions do not invalidate the additional counterexamples. R5 and historical baseline failures are outside this rereview; this is not whole-branch or product approval.

## F1 / R1 — P1 — Serialized authorization/provider data still crosses the public value boundary

**Locations:** `app/services/generation_contracts.py:71-96`, `:99-109`, `:159-179`, `:249-269`; `app/services/ai_reference.py:76-118`; `app/static/app.js:468-486`, `:521-533`, `:637-649`.

The new regex recognizes `Authorization: Bearer ...`, but not the ordinary JSON spelling `{"Authorization":"Bearer ..."}`: the quote after the key and quote before the value do not match that alternative. `provider_raw` is also absent from its provider marker alternatives, and a message/content provider envelope has neither `choices` nor `messages`. These are recognizable transport/diagnostic structures, not a demand to detect arbitrary secrets in ordinary prose. The same regex is duplicated in the frontend, so the downstream boundary repeats the miss.

Completed local probes used these exact synthetic strings as individual `possible_target_users` values:

```json
{"Authorization": "Bearer SYNTHETIC_REREVIEW_TOKEN"}
{"provider_raw": "SYNTHETIC_REREVIEW_PRIVATE"}
{"id": "msg_fake", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "SYNTHETIC_REREVIEW_PRIVATE"}], "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}
```

The API probe used temporary seeded SQLite, the real `create_app`/`TestClient`, a fake `generate_ai_reference` runtime, participant `test`, and a stopped local async worker. It POSTed `/api/projects/project_insightforge_demo/ai-reference`, GET the same route, and called the real reference service twice with the same idempotency key. The replay returned the same persisted ID, retaining the raw value:

```text
R1_API json_authorization post=201 get=200 public_raw=True loaded_raw=True replay_raw=True same_id=True
R1_API provider_raw post=201 get=200 public_raw=True loaded_raw=True replay_raw=True same_id=True
R1_API message_envelope post=201 get=200 public_raw=True loaded_raw=True replay_raw=True same_id=True
EXTERNAL_CONNECTION_ATTEMPTS=0
```

Each of the three strings was also independently **ACCEPTED** by `validate_guidance` in an otherwise valid card title, `validate_solution_response` in candidate 0's summary of a complete solution triplet, and `validate_document_draft` in document content. Those nine checks establish the shared validator weakness; they are not claimed as nine separate persisted API workflows.

Using the real `app.js` in the existing behavior-only fake DOM:

```text
R1_PROBE json_authorization adapter_accepted=true raw_rendered=true
R1_PROBE provider_raw adapter_accepted=true raw_rendered=true
R1_PROBE message_envelope adapter_accepted=true raw_rendered=true
R1_ADAPTER toEvidenceGuidanceViewModel accepted=true
R1_ADAPTER toSolutionsViewModel accepted=true
R1_ADAPTER toDocumentWorkspaceViewModel accepted=true
R1_DOCUMENT_EDITOR_RAW=true
```

The last four lines use the JSON authorization example. Reference rendering used `hooks.setTestAIReference` and inspected `#ai-reference-content`; document rendering used `hooks.renderDocumentWorkspace` and inspected `#document-editor`. These are actual application adapters/render functions, not a reimplementation of the regex. No real credential was used or discovered.

**Why this blocks R1:** The original bypass class remains: schema-valid content is saved as completed and disclosed through the public API and UI. Tests currently enumerate ten rejected strings in `tests/fixtures/whole_branch_value_cases.json:2-13`; the unquoted authorization fixture is insufficient to cover JSON serialization. The existing API denylist also recognizes `providerraw` (`tests/test_stage_b_api_contract.py:13-29`), but the new value regex does not.

**Required correction:** Reject recognizable serialized transport/private diagnostic structures in allowed values, including quoted authorization and the supported provider envelope forms, consistently across generation and replay/rendering. Add these counterexamples alongside ordinary-prose/ordinary-JSON controls. A bounded guard need not become a general secret detector, but its limitations do not close these concrete leaks.

### R1 metadata sub-result

`failure_public` now bounds quota to `RESERVED`/`RELEASED`/`CHARGED`, bounds failure stage to seven explicit transport/deadline values, accepts only `STAGE_A_SYNTHETIC` fixture origin, and derives its disclosure from `SAFE_FIXTURE_DISCLOSURE` (`generation_contracts.py:285-299`). Error code/message/actions come from `public_recovery_payload` (`app/errors.py:87-99`).

The five direct metadata tests in `test_whole_branch_fixes.py:95-108` passed, including replacing an arbitrary fixture disclosure with fixed application copy. An additional probe injected arbitrary synthetic strings into all four auxiliary fields, message, and actions in stored sync and async failures:

```text
R1_METADATA sync_replay http=503 private_echo=False auxiliary_fields=omitted error_code=MODEL_OUTPUT_CONTRACT_FAILED
R1_METADATA async_poll http=200 private_echo=False auxiliary_fields=omitted error_code=MODEL_OUTPUT_CONTRACT_FAILED
EXTERNAL_CONNECTION_ATTEMPTS=0
R1_FAILURE_METADATA_RENDERED=false
```

Sync replay calls `failure_public` at `app/main.py:1125`; async failure polling does so at `app/services/async_generation.py:88`. The frontend probe placed raw strings in the four auxiliary fields and called actual `showRecoveryPayload`; none appeared in `#runtime-disclosure` (`app/static/app.js:343-363`). The separate 12-case error-copy selection passed exception, sync replay, and async polling boundaries. This sub-verdict is limited to the named metadata/copy contract, not every conceivable failure or debug field.

## R2 — PASS — Optional reference categories are independent of mandatory Action Card lists

**Locations:** `app/static/app.js:485-493`, `:521-558`; `app/services/generation_contracts.py:167-189`.

`toAIReferenceViewModel` now passes `required: false` for each category. Omitted categories become empty lists; explicit non-array values still fail. The adapter still requires at least one populated category, matching the backend domain check. `toEvidenceGuidanceViewModel` retains required `who_or_where`, `action_steps`, `acceptable_artifacts`, and `fill_template`; `suggested_questions` remains optional.

Fresh evidence:

- Four ordinary-prose cases passed `test_partial_reference_generation_load_and_retry_preserve_ordinary_prose`: generation contains an empty `research_directions`, `get` equals the generated result, and idempotent replay equals it (`tests/test_whole_branch_fixes.py:110-118`).
- The real frontend load/generate/retry path accepts `{possible_target_users: ["唯一有效类别"]}`, renders its content, displays success, and records two mocked POSTs. The standalone harness also rejects `{}` and each of the four empty mandatory card lists (`tests/whole_branch_fix_harness.js:89-117`).
- The supplemental pytest selection passed all four empty/malformed reference cases and all eleven actionable-card negative cases in `tests/test_stage_b_output_contract.py:47-70`.

This closes the reported shared-helper regression. R1's content rejection weakness remains a separate obligation.

## R3 — PASS — Selected-B documents include required inherited fields and reach the editor

**Locations:** `app/services/generation.py:318-328`, `:429-447`, `:528-532`; `app/services/loop.py:317-334`; `app/static/app.js:701-735`.

Both generators now emit separate summary and core idea, target user, problem, value, and rationale. TechDoc collects and emits the selected MVP pages. Existing flow and feature emissions complete the set of literal inherited fields required by the current frontend adapter.

Fresh tests `test_generated_selected_b_document_passes_actual_frontend_adapter[prd/techdoc]` (`tests/test_whole_branch_fixes.py:121-136`) use distinct values for title, summary, core idea, user, problem, value, rationale, two flows, two features, and `UNIQUE_B_PAGE_1`/`UNIQUE_B_PAGE_2`. Both outputs pass the real section validator, actual `toDocumentWorkspaceViewModel`, and actual editor rendering.

`test_selected_b_persisted_documents_are_accepted_by_frontend_without_forced_validation` (`tests/test_whole_branch_fixes.py:221-240`) also passed. It generates three local candidates through the API, selects B after assigning two unique page names, generates PRD and TechDoc through the API, fetches persisted versions, checks exact content equality, and passes each persisted content/snapshot pair to the frontend adapter/editor. It does not set backend `validation_status='passed'`.

**Evidence boundary:** The JS `--document` harness reconstructs the version wrapper with `validation_status: 'not_run'` and current health (`tests/whole_branch_fix_harness.js:38-50`). It therefore proves frontend acceptance of actual generated/persisted content and snapshot terms, not preservation of every returned version metadata field, independent validator approval, confirmation/handoff readiness, or real-browser acceptance. Substring inheritance is not semantic proof. R4 remains independently capable of rejecting documents that state non-goals.

## F2 / R4 — P2 — Common exclusions still disappear, and non-goal headings can hide positive scope

**Locations:** `app/static/app.js:675-692`, `:717-735`, `:2022-2037`.

The new clause guard enumerates a few negative phrases. It recognizes `不支持` and `不会实现`, but not `不会支持` or `不集成`. Thus a document explicitly saying the approved excluded payment capability is absent is still classified as added scope. Conversely, inside an exclusion section, any clause without an enumerated positive verb is exempt: “支付功能将在本期完成” is accepted despite its clear positive commitment.

Actual frontend probe setup:

```javascript
hooks.state.snapshot = {
  solution: {title: "SELECTED_B", explicit_non_goals: ["不做支付"]},
  mvp: {pages: ["PAGE_B"]}
};
// Every document starts with "# SELECTED_B\nPAGE_B\n".
// workspace() supplies a valid version wrapper from the existing harness.
```

| Appended document content | Intended scope | Actual adapter/editor result |
|---|---|---|
| `明确不做支付。` | Honest exclusion, original case | Accepted; editor length 27 |
| `本期不会支持支付。` | Honest exclusion | Rejected; editor length 0 |
| `本期不集成支付。` | Honest exclusion | Rejected; editor length 0 |
| `本期支持支付。` | Positive scope drift, control | Rejected; editor length 0 |
| `## 非目标` followed by `- 支付功能将在本期完成。` | Positive scope drift despite heading | Accepted; editor length 40 |

The same two failures were reproduced for persisted-draft-shaped input based on an otherwise valid selected version:

```text
R4_DRAFT honest accepted=false editor_length=0 error={"code":"DOCUMENT_CONTENT_INVALID"}
R4_DRAFT positive accepted=true editor_length=40 error=null
```

These probes execute actual `toDocumentWorkspaceViewModel` and `renderDocumentWorkspace`. The failed honest case clears and disables the editor and its actions at `app.js:2031-2037`; it does not establish deletion from the database. Original exclusions and positive-commitment fixtures in the committed harness pass, but do not cover these ordinary formulations.

**Required correction:** Make the scope contract reliably distinguish approved exclusions from positive commitments, preferably with structured scope separated from narrative. If retaining a lexical check, add both counterexamples and positive/negative controls; do not treat a non-goal heading as sufficient permission for arbitrary assertions beneath it. Do not remove selected identity/page checks.

## Fresh bounded verification

Executed from the reviewed worktree, using the existing local runner after inspecting it. It removes provider/search-related environment settings and blocks non-loopback socket connections; local Windows event-loop socketpairs are permitted. The API transport is in-process and generation inputs are fake/deterministic. No real Provider/Search request or deployment was run.

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_whole_branch_fixes.py
```

**120 passed in 66.13s (0:01:06), exit 0; `EXTERNAL_CONNECTION_ATTEMPTS=0`.**

```powershell
py -3.12 -X utf8 .superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/run-r1-r4-local.py -q --tb=short -p no:cacheprovider tests/test_stage_b_output_contract.py::test_every_card_must_be_actionable_before_any_card_is_saved tests/test_stage_b_output_contract.py::test_reference_domain_rejection_is_typed_safe_and_never_persisted tests/test_stage_b_output_contract.py::test_public_success_fields_cannot_contain_diagnostic_objects tests/test_stage_b_api_contract.py::test_public_failure_text_is_app_owned_on_every_boundary
```

**28 passed in 26.10s, exit 0; `EXTERNAL_CONNECTION_ATTEMPTS=0`.**

| Other completed check | Result |
|---|---|
| `node tests/whole_branch_fix_harness.js` | 118 passed, 0 failed; also invoked within the first pytest selection, so not disjoint coverage |
| `node --check app/static/app.js` | Exit 0 |
| `git diff --check HEAD^ HEAD` | Exit 0 |
| Additional temporary SQLite/API and in-memory JS probes described above | Completed; F1/F2 counterexamples reproduced; metadata controls passed |

Supplementary probes were sent through PowerShell here-strings to `py -3.12 -X utf8 -` / `node`, without adding test/script files. Python used temporary seeded databases and the same outbound guard policy. The JS probes reused the prefix of `tests/whole_branch_fix_harness.js` before `if (process.argv.includes("--document"))`, loaded actual `app.js`, and invoked its adapter/render functions with the payloads above.

Initial supplementary-probe setup attempts failed because of a VM binding collision, a guard that also blocked Windows' local socketpair, and missing/uninitialized test participant context. These setup attempts are not product findings or passing checks. The completed probes corrected those harness issues; the real API probe set participant `test` after `TestClient` startup. No source correction was made.

The verification-before-completion skill guided the separation of completed tests, counterexamples, and unproved acceptance claims. No long broad suite was started. R5, repository-wide regression status, external model quality, deployment readiness, and historical baseline disposition remain unassessed here.

**Final scoped verdict: FAIL. Close F1/R1 and F2/R4 before approving R1–R4. R2 and the reported R3 defect pass this rereview.**
