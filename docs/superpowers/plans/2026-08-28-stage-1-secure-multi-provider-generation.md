# Secure Multi-Provider Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add write-only model credentials, provider profiles, capability-aware adapters, bounded Agent tools, and an honest local fallback for arbitrary Ideas.

**Architecture:** SQLite owns non-secret profile metadata and revisions; Windows Credential Manager owns API keys. A provider registry selects protocol adapters, while a hybrid runtime resolves global/project profiles and maps provider failures to stable recovery responses.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, `keyring` Windows backend, OpenAI SDK compatibility layer, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-28-insightforge-guidance-models-documents-history-design.md`

## Global Constraints

- Never persist or return any API-key character; API responses expose only `credential_status`.
- Presets: `qwen`, `kimi`, `deepseek`, `glm`, `openai`, `custom`.
- No silent paid-model failover; maximum Agent rounds remain bounded.
- Local read tools may auto-run; network/write/delete/export require explicit confirmation.
- Existing SQLite databases migrate additively and idempotently.
- Current deployment directory is not a Git repository. Commit steps apply only after execution occurs in an initialized Git worktree; otherwise record the test checkpoint without initializing Git implicitly.

---

### Task 1: Profile Schema and Migration

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_model_profile_schema.py`

**Interfaces:**
- Produces tables `model_profiles`, `model_profile_revisions`, `project_model_profiles`.
- Produces `Database.init_schema()` migration compatible with existing databases.

- [ ] **Step 1: Write failing schema tests** asserting all three tables exist, no secret column exists, one default profile is enforced by service logic, and repeated `init_schema()` preserves rows.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_model_profile_schema.py`; expect missing-table failures.
- [ ] **Step 3: Add schema** with exact columns from the spec. Use `credential_ref TEXT`, `capabilities_json TEXT NOT NULL DEFAULT '{}'`, integer booleans, revision timestamps, and foreign keys; never add `api_key`, `secret`, or masked-key columns.
- [ ] **Step 4: Run the schema test** and `python -m pytest -q tests/test_v3_schema_migration.py`; expect PASS.
- [ ] **Step 5: Checkpoint** the schema and test files; if in Git, commit `feat: add model profile metadata schema`.

### Task 2: Write-Only Credential Store

**Files:**
- Create: `app/services/credential_store.py`
- Modify: `pyproject.toml`
- Test: `tests/test_credential_store.py`

**Interfaces:**
- Produces `CredentialStore.put(profile_id: str, value: str) -> str`.
- Produces `CredentialStore.resolve(credential_ref: str) -> str`, backend-only.
- Produces `CredentialStore.delete(credential_ref: str) -> None` and `CredentialStore.configured(ref: str|None) -> bool`.

- [ ] **Step 1: Write failing tests** using an in-memory test backend. Assert `put()` returns `insightforge:model-profile:<id>`, replace overwrites, delete removes, and `repr()`/serialized metadata never contains sentinel `sk-SENTINEL-DO-NOT-LEAK`.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_credential_store.py`; expect import failure.
- [ ] **Step 3: Implement** a narrow backend protocol and `KeyringCredentialStore` using service name `InsightForge`. Raise `CredentialBackendUnavailable` instead of falling back to plaintext. Add `keyring>=25,<26` to dependencies.
- [ ] **Step 4: Run tests**; expect PASS without touching the real Windows vault because tests inject the in-memory backend.
- [ ] **Step 5: Checkpoint**; if in Git, commit `feat: add write-only credential store`.

### Task 3: Provider Registry, Adapters, and Capability Probe

**Files:**
- Create: `app/services/model_providers.py`
- Create: `app/services/provider_adapters.py`
- Create: `app/services/capability_probe.py`
- Test: `tests/test_provider_adapters.py`

**Interfaces:**
- Produces `ProviderPreset(provider, protocol, default_base_url)` and `ProviderRegistry.get(provider)`.
- Produces `ModelAdapter.interpret_idea(...)`, `design_solutions(...)`, and `probe() -> CapabilityReport`.
- `CapabilityReport` contains `basic_chat`, `structured_json`, `function_calling`, `streaming`, `checked_at`.

- [ ] **Step 1: Write failing table-driven tests** for six presets and literal official default URLs; test Custom rejects a missing protocol/Base URL.
- [ ] **Step 2: Write adapter contract tests** with local `httpx.MockTransport` responses for success, 401, 402/insufficient quota, 404 model, 429, timeout, malformed JSON, and schema-invalid content.
- [ ] **Step 3: Run** `python -m pytest -q tests/test_provider_adapters.py`; expect missing-module failures.
- [ ] **Step 4: Implement registry and adapters.** Keep provider identity separate from `openai_chat_completions` or `anthropic_messages`. Convert exceptions into `ProviderCallError(code, safe_message, retryable)` without response-body leakage.
- [ ] **Step 5: Implement probe** without guessing from model names. Record unsupported/unknown separately and make probe execution explicit because it may consume quota.
- [ ] **Step 6: Run adapter tests**; expect PASS.
- [ ] **Step 7: Checkpoint**; if in Git, commit `feat: add provider adapter registry`.

### Task 4: Model Profile Service and Sanitized APIs

**Files:**
- Create: `app/services/model_profiles.py`
- Modify: `app/schemas.py`
- Modify: `app/main.py`
- Test: `tests/test_model_profile_api.py`

**Interfaces:**
- Produces `ModelProfileService.create/update/delete/set_default/set_project_override/test_connection`.
- API responses use `credential_status` and exclude `credential_ref`.

- [ ] **Step 1: Write failing API tests** for CRUD, replacement versus keep-existing-key, default uniqueness, referenced-profile deletion conflict, project override, disabled profile rejection, and capability-test status.
- [ ] **Step 2: Add a sentinel leak test** that recursively searches JSON responses, SQLite text columns, audit payloads, and captured logs for the submitted sentinel key.
- [ ] **Step 3: Run** `python -m pytest -q tests/test_model_profile_api.py`; expect 404 routes.
- [ ] **Step 4: Add strict request models** `ModelProfileCreateRequest`, `ModelProfileUpdateRequest`, and `ProjectModelProfileRequest`. `api_key` is accepted only in create/replace requests and never appears in response models.
- [ ] **Step 5: Implement service transactions and routes** exactly as specified. Audit provider/model/revision/action only.
- [ ] **Step 6: Run tests**; expect PASS.
- [ ] **Step 7: Checkpoint**; if in Git, commit `feat: expose sanitized model profile api`.

### Task 5: Hybrid Structured Runtime and Bounded Tool Policy

**Files:**
- Create: `app/services/hybrid_runtime.py`
- Modify: `app/services/ai_runtime.py`
- Modify: `app/services/quick_start.py`
- Modify: `app/services/solution_design.py`
- Modify: `app/tools.py`
- Modify: `app/errors.py`
- Test: `tests/test_hybrid_runtime.py`

**Interfaces:**
- Produces `HybridStructuredRuntime.for_project(project_id: str|None) -> StructuredAIRuntime`.
- Produces recovery payload `{error_code, message, recovery_actions, preserved_input}`.
- Tool specs gain `permission_class: local_read|network_read|local_write|delete|export`.

- [ ] **Step 1: Write failing tests** for global selection, project override, absent profile local fallback, invalid key recovery, bounded schema repair, no paid failover, unknown tool rejection, and confirmation requirements.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_hybrid_runtime.py`; expect failures on current single-runtime construction.
- [ ] **Step 3: Implement runtime resolution** per request rather than one startup singleton. Preserve deterministic frozen cases, but unknown Ideas return a saved local-guidance result instead of raw `DETERMINISTIC_DEMO_UNSUPPORTED`.
- [ ] **Step 4: Implement tool permission enforcement** before handlers run. Keep existing L0/L1/L2 behavior compatible while mapping it to the new permission classes.
- [ ] **Step 5: Run tests** plus `tests/test_v3_quick_start.py tests/test_tools.py`; expect PASS.
- [ ] **Step 6: Checkpoint**; if in Git, commit `feat: add hybrid generation runtime`.

### Task 6: Settings UI and Stage Verification

**Files:**
- Create: `app/static/model-settings.js`
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`
- Test: `tests/test_model_settings_ui.py`

**Interfaces:**
- Adds a Settings entry and provider-profile management view.
- Consumes sanitized model-profile APIs only.

- [ ] **Step 1: Write failing UI contract tests** for provider choices, blank edit-key field, configured/missing labels, test/default/disable/delete actions, and absence of reveal/copy-key controls.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_model_settings_ui.py`; expect missing UI failures.
- [ ] **Step 3: Implement focused module** `model-settings.js`; never retain keys in global state after a successful request and clear key inputs in `finally`.
- [ ] **Step 4: Run targeted UI tests and** `node --check app/static/model-settings.js app/static/app.js`.
- [ ] **Step 5: Run full verification:** `python -m pytest -q`, `python -m compileall -q app tests`, start an isolated server/database, test sanitized CRUD and one explicitly authorized live provider only if the user approves possible cost, then run SQLite integrity/foreign-key checks.
- [ ] **Step 6: Checkpoint**; if in Git, commit `feat: add secure provider settings ui`.

