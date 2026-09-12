# Stage B Output Contract Implementation Plan

> **For the implementing agent:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Establish a single safe boundary from provider output to validated product domain objects, with typed failures and zero raw provider/JSON leakage.

**Architecture:** L1 raw provider data stays in private adapter diagnostics. L2 normalization produces a typed normalized result. L3 Pydantic/domain validation produces only complete product objects. L4 API DTOs and frontend renderers consume allowlisted fields. Structured tasks fail closed; plain-text tasks retain a separate non-JSON contract.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, httpx, pytest, vanilla JavaScript, Chromium/Playwright harnesses.

**Spec:** `STAGE_B_AI_SURFACE_MATRIX.md`; current implementation in `app/services/provider_adapters.py`, `app/services/ai_reference.py`, `app/services/evidence_coach.py`, `app/services/solution_design.py`, `app/services/async_generation.py`, `app/main.py`, and `app/static/app.js`.

## Global Constraints

- Do not change beta001/002/003, database choice, frontend framework, provider set, or public debug endpoints.
- Real Provider requests and Search requests remain zero during B1/B2.
- Every production change follows RED, confirmed failure cause, minimal GREEN, regression, and one focused commit.
- No production fallback returns raw model text after structured parsing failure.

## Tasks

### 1. Add failing provider output-contract fixtures and tests

Files: `tests/fixtures/stage_b_provider_outputs.json` (new), `tests/test_stage_b_output_contract.py` (new), `tests/test_provider_adapters.py`.

Use a fake httpx transport around `ModelAdapter._generate` and `AsyncModelAdapter._generate_async`. Cover `PLAIN_TEXT_GOOD`, `STRUCTURED_GOOD`, fenced JSON, leading/trailing explanatory text, malformed JSON, empty output, provider error JSON, nested JSON string, escaped Unicode, markdown-wrapped JSON, multiple objects, missing fields, wrong types, wrong schema. Assert the current implementation fails at least one required contract test and save the command plus actual failure in `artifacts/stage-b-red-output-contract.txt`.

Run: `python -m pytest tests/test_stage_b_output_contract.py -q` and record RED before modifying application code. Commit: `test: reproduce ai output contract failures`.

### 2. Implement normalization and typed structured failure

Files: `app/services/provider_adapters.py`, `app/errors.py`, `app/services/ai_runtime.py`, `tests/test_stage_b_output_contract.py`, `tests/test_provider_adapters.py`.

Add an explicit internal normalization helper adjacent to `ModelAdapter._content_from_response` and use it from `_generate` and `_generate_async`. It strips BOM and surrounding whitespace, accepts one complete JSON payload or one supported JSON fence/wrapper, rejects ambiguous extra prose, multiple objects, empty output, and provider-native error payloads. Preserve only hash/byte-count/classification in safe diagnostics. Map parser failures to a stable typed error with user-safe Chinese message; keep raw bytes private.

Run targeted adapter tests and `python -m pytest tests/test_provider_adapters.py tests/test_stage_b_output_contract.py -q`. Commit: `fix: prevent raw structured output leakage`.

### 3. Add schema/domain completeness validation

Files: `app/schemas.py`, `app/services/ai_reference.py`, `app/services/evidence_coach.py`, `app/services/solution_design.py`, `app/services/async_generation.py`, new `app/services/generation_contracts.py`, and tests `tests/test_stage_b_output_contract.py`, `tests/test_v3_solution_design.py`, `tests/test_ai_reference_no_source.py`.

Create surface-specific completeness validators. Require non-empty AI reference body; require every Action Card to contain confirmation target, actor/location, executable steps, artifacts, template, decision impact, fallback, and limitations; require exactly three valid solutions for the Stage B product contract and at least two interpretable difference dimensions; require document section completeness and snapshot bindings. Return typed domain failures instead of Pydantic dumps. Ensure `AsyncRun.public()` and ordinary routes expose only allowlisted success/error fields.

Run the targeted backend suite and inspect serialized success/failure payloads for `raw_response`, `provider_payload`, authorization, prompts, traceback, and exception dumps. Commit: `test: cover ai generation surface contracts` after tests are expanded.

### 4. Add API raw-field denylist and failure response tests

Files: `tests/test_stage_b_api_contract.py` (new), `app/main.py`, `app/errors.py`, `tests/test_api_error_contract.py`.

Exercise AI reference, evidence guidance, solution generation, document generation, and async polling using deterministic/fake runtimes. Recursively assert public responses never contain raw response, provider payload, authorization, debug prompt, system prompt, traceback, `JSONDecodeError`, `ValidationError`, or Python exception text. Assert parse/schema/provider failures explain what happened, whether content was written, and whether retry is allowed.

Run: `python -m pytest tests/test_stage_b_api_contract.py tests/test_api_error_contract.py -q`. Commit: `test: add stage-b api leak contracts`.

### 5. Verify B1 engineering gate

Files: `tests/fixtures/stage_b_provider_outputs.json`, `artifacts/stage-b-red-output-contract.txt`, `STAGE_B_AI_SURFACE_MATRIX.md`.

Run backend targeted tests, full pytest, frontend harnesses that do not call external services, `git diff --check`, and the repository secret scan command discovered from `Makefile`/scripts. Record exact pass/fail counts. Do not run real-provider scripts. The gate is ready only when parser, schema validation, user-safe errors, API denylist, raw JSON leak, provider leak, and empty-success checks pass.

## Acceptance criteria

- One normalization boundary is used by synchronous and asynchronous structured adapters.
- Structured parse/schema failures never return raw model text to a public response.
- Private diagnostics contain only classification, hash, byte count, and approved operator metadata.
- A response is not `SUCCEEDED` unless its surface completeness validator passes.
- B1 result is reported as `STAGE_B_AI_GENERATION_ENGINEERING_READY` only with fresh evidence.
