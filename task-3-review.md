# B2 Task 3 Independent Review

## Verdict

**FAIL** for `0d35c4f..296010d`.

The backend generation path is fail-closed for incomplete Evidence Action Cards, and the AI-reference/evidence provenance and no-source behavior are largely correct. However, the actual frontend DTO/render adapter accepts empty arrays for fields that the DTO contract and approved plan define as required. A malformed, legacy, or otherwise nonconforming response can therefore render as a complete actionable card.

## Scope and materials reviewed

- `0d35c4f..296010d`
- `.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/review-0d35c4f..296010d.diff`
- `.superpowers/sdd/2026-09-12-stage-b-ai-generation-ux/task-3-report.md`
- `docs/superpowers/plans/2026-09-12-stage-b-ai-generation-ux.md`
- `docs/superpowers/plans/2026-09-12-stage-b-output-contract.md`
- `STAGE_B_AI_SURFACE_MATRIX.md`
- actual schemas, generation validators, public adapters, services, API error handlers, and render code

The commit is scope-limited to the Task 3 report, AI-reference/evidence services, the frontend surface, and focused tests. No unrelated production file, Provider, Search, deployment, or B3 implementation was added. The pre-existing untracked `task-2-rereview2.md` was preserved.

## Finding 1 — required Action Card lists are not enforced at the render boundary

**Unresolved — P1/P2 contract failure.**

The approved output contract requires non-empty `who_or_where`, `action_steps`, `acceptable_artifacts`, and `fill_template`; only `suggested_questions` is optional. The backend correctly implements that requirement in `validate_guidance()` (`app/services/generation_contracts.py:126-134`).

The frontend adapter attempts to mirror it at `app/static/app.js:517-532`, but calls:

```js
viewStringList(card[key], {required: key !== "suggested_questions", maxItems: 20})
```

`viewStringList()` (`app/static/app.js:473-478`) checks type, item count, and item text, but never rejects `value.length === 0` when `required` is true. Consequently, a card with empty arrays for all four required list fields is accepted by `toEvidenceGuidanceViewModel()` and passed to the renderer. `appendEvidenceGuidanceBlock()` then supplies the placeholder `可按实际情况补充问题。`, making missing required evidence-collection instructions look present.

Independent minimal fake-DOM reproduction against the reviewed checkout:

```text
EMPTY_REQUIRED_LIST_ACCEPTED
```

The probe supplied a card with empty `who_or_where`, `action_steps`, `acceptable_artifacts`, and `fill_template`; the adapter accepted it and the renderer emitted the placeholder. This violates the stated fail-closed DTO/render contract and the Task 3 report's claim that required fields are rejected when missing. The normal fresh service path does not mask the issue: backend validation prevents newly generated incomplete cards, but the frontend boundary must also protect persisted/legacy/forged/nonconforming API payloads.

Required follow-up: make `viewStringList()` return `null` for an empty list when `required` is true (or add an equivalent explicit length check), and add a fake-DOM regression assertion for every required list field. Do not weaken the backend validator.

## Contract checks

### AI reference visibility and provenance — PASS

- `AIReferenceService.generate()` rejects an entirely empty reference before persistence through `validate_reference()`.
- The service sets an application-owned notice stating `AI参考/待验证`, that the content is model suggestions, and that it is not research, market, or user fact (`app/services/ai_reference.py:28-29, 86-110`).
- The frontend ignores an untrusted server notice and renders the same fixed provenance copy (`app/static/app.js:432, 502-514`).
- Rendered AI-reference content uses typed DOM nodes and `textContent`; the focused browser harness checks a visible nonempty item and the provenance notice.

### Action Card completeness and actionability — FAIL

The renderer exposes the required labeled blocks and the optional suggested-question block (`app/static/app.js:1794-1804`), but the adapter gap in Finding 1 means completeness is not guaranteed at the actual render contract. Fresh backend-generated cards passed the positive tests; the negative empty-required-list case failed to fail closed.

### Evidence optional and no source without evidence — PASS

- Evidence guidance is stored as guidance, not as a source.
- Service results and audit payloads explicitly set `is_evidence=False` and `source_created=False` (`app/services/evidence_coach.py:83-124`).
- No source-generation call is made by the guidance service; its prompt boundary explicitly says not to browse or generate sources (`app/services/evidence_coach.py:34-40`).
- Focused tests verify zero sources and the false evidence/source flags.

### Unsupported claim semantics — PASS with a bounded detector

- Fresh AI-reference and Action Card outputs are checked before persistence with the shared `reject_unsupported_claims()` path (`app/services/ai_reference.py:41-46`; `app/services/evidence_coach.py:64-82`).
- The focused tests reject assertive research/user claims and verify that no result is persisted.
- The detector is intentionally limited to obvious Chinese/English research, market, and universal-user patterns; it is not a general semantic truth detector. The safety case therefore depends on the fixed provenance/disclosure that labels the whole output as unverified model suggestions, which is present for both surfaces.

### Raw leak and safe errors — PASS

- Public adapters project only allowlisted DTO fields (`reference_public()` and `guidance_public()`).
- UI rendering uses `textContent` for the reviewed surfaces.
- Structured contract failures are mapped to application-owned recovery payloads; provider diagnostics, prompt text, and raw exception text are not returned by the public error contract.
- Existing API error and Stage-B contract tests passed.

### Scope and regressions — PASS, subject to Finding 1

The diff is limited to the intended Task 3 services, frontend surface, report, and tests. No evidence source is created, no real external integration was exercised, and no B3 behavior is claimed. `git diff --check` passed.

## Verification

All verification was local and used fake/deterministic runtimes or intercepted transport only:

- `py -3.12 -m pytest -q tests/test_ai_reference_no_source.py tests/test_evidence_guidance.py tests/test_evidence_coach.py` — **12 passed**
- `py -3.12 -m pytest -q tests/test_task3_review_contracts.py` — **38 passed**
- `py -3.12 -m pytest -q tests/test_api_error_contract.py tests/test_stage_b_api_contract.py` — **53 passed**
- `node --check app/static/app.js` — **PASS**
- `node tests/stage_b_generation_surface_harness.js` — **15/15 PASS**
- `node tests/generation_recovery_behavior_harness.js` — **PASS**
- `node tests/document_evidence_ux_behavior_harness.js` — **PASS**
- `git diff --check 0d35c4f..296010d` — **PASS**
- independent fake-DOM empty-required-list probe — **accepted malformed card**, confirming Finding 1

The requested legacy fake Chromium runner was attempted but did not complete within the bounded wait and was stopped. The known legacy blocker is the fixture imported from `_solution_payload()`, which returns two candidates while the existing B2 contract requires exactly three complete candidates. The implementer report records that the AI-reference and Evidence-guidance paths were reached and passed in the prior run. This is recorded as a legacy Chromium timeout/skip, not as evidence of real-browser success. No real Provider, Search, transport, deployment, or B3 run was performed.

## Final decision

**FAIL pending the frontend fail-closed fix and regression test for empty required Action Card lists.** The commit does support the requested provenance, optional/no-source semantics, unsupported-claim boundary, safe error behavior, and scope isolation, but the Action Card render contract is not complete as reviewed.
