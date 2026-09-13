# AI Reference Structured Output Contract Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. After each task, run the specified verification before proceeding.

## Goal

Make the Provider-facing AI Reference structured response require at least one substantive reference item, while mapping that response deterministically into the unchanged `AIReferenceDraft` domain model. Preserve the existing completeness gate, safe-shape diagnostics, ordinary product route, retry/fallback behavior, and public leakage protections.

## Architecture

The Provider adapter will validate a dedicated envelope containing `references` and an optional `uncertainty_notice`. Each reference item will use `REFERENCE_FIELDS` as its category constraint and a non-empty content string. A small mapper will group envelope items into the existing `AIReferenceDraft` list fields and copy the notice. The adapter will continue to return `AIReferenceDraft` to callers, so runtime, service, persistence, and UI contracts remain unchanged. Safe diagnostics will inspect the envelope before mapping and the normalized domain model after mapping without storing values.

## Tech Stack

Python 3.12 runtime, Pydantic v2, pytest, existing synchronous/asynchronous provider adapters, existing `AIReferenceDraft` and generation-contract helpers.

## Spec

- Provider response schema: `references` is a non-empty list of `{category, content}` items; `category` is constrained from the source `REFERENCE_FIELDS`; `content` is non-blank; `uncertainty_notice` is optional.
- `uncertainty_notice` is supplemental and never becomes a substantive reference field.
- The mapper must reject malformed categories/content and produce only existing `AIReferenceDraft` fields.
- Existing direct/fake runtime callers and ordinary HTTP AI Reference behavior remain compatible.
- Notice-only domain fixtures continue to fail `validate_reference`.
- No real Provider or Search request is allowed during this task.

## Global Constraints

- Do not modify `AIReferenceDraft`, `REFERENCE_FIELDS`, `validate_reference`, prompt semantics outside the Provider-facing contract, model/provider configuration, transport, retry, fallback, dispatch, budget, UI, frontend, Stage A, or beta surfaces.
- Do not persist or print response values, previews, raw payloads, prompts, credentials, or authorization headers.
- Do not modify historical receipts or Railway state.
- Follow RED → GREEN → regression; run fresh verification before claiming readiness.

## Tasks

### 1. Add failing contract tests

Files: `tests/test_ai_reference_generation_contract.py`, a focused new envelope test module if needed.

- Assert the Provider-facing output model requires a non-empty `references` collection and valid category/content pairs.
- Assert a notice-only payload is rejected by the Provider-facing schema before domain mapping.
- Assert a valid envelope maps into unchanged `AIReferenceDraft` fields and preserves the supplemental notice.
- Run only these tests and record the expected RED failure against the current direct `AIReferenceDraft` contract.

### 2. Implement the focused envelope and mapper

Files: `app/services/generation_contracts.py` and/or the existing service module according to source conventions.

- Define the Provider-facing Pydantic models with strict extra handling and source-derived category constraints.
- Add a deterministic envelope-to-domain mapper with no raw fallback and no value persistence in diagnostics.
- Keep existing domain validation and public projection unchanged.

### 3. Route sync and async Provider AI Reference generation through the envelope

File: `app/services/provider_adapters.py`.

- Use the envelope output model and strengthened Provider instructions for both sync and async methods.
- Map the validated envelope to `AIReferenceDraft` before returning to runtime callers.
- Preserve existing transport, dispatch, retry, fallback, error, and budget behavior.

### 4. Preserve and extend diagnostics safely

Files: `app/services/generation_contracts.py`, related diagnostics tests.

- Capture envelope shape before mapping and normalized domain shape after mapping using only keys, types, and lengths.
- Ensure notice-only, empty, malformed, unknown-category, and valid-envelope cases remain distinguishable without values or previews.

### 5. Run focused and related regressions

- Run envelope, AI Reference, Provider adapter, safe-shape, output-contract, linkage, operator, API leak, and frontend-relevant tests.
- Run `compileall`, JavaScript syntax checks, `git diff --check`, and fallback static secret scan.
- Compare failures with the known baseline and require zero new failures.

### 6. Review and final verification

- Perform a fresh review focused on schema enforcement, deterministic mapping, no raw fallback, no domain/completeness changes, and no cross-surface behavior changes.
- Verify the worktree and candidate commit are clean and that Provider/Search calls remain zero.
