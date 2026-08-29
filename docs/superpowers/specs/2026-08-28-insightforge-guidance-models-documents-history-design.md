# InsightForge Guidance, Model Runtime, Documents, and History Design

**Date:** 2026-08-28  
**Status:** User-approved design, pending implementation plan  
**Current baseline:** InsightForge 3.0.0 local workspace  

## 1. Objective

Deliver five priority improvements as staged vertical slices:

1. actionable next-step guidance on the home page and inside projects;
2. one-click complete examples with an interactive walkthrough;
3. stable arbitrary-Idea generation through a secure multi-provider runtime and an honest local fallback;
4. online PRD/TechDoc editing, immutable versions, diffs, restore, and export;
5. a dedicated project-history center with search, filters, copy, and trash.

The iteration must preserve InsightForge's evidence and confirmation boundaries. A model may propose and explain, but it may not fabricate completed workflow state, upgrade unsupported evidence, reveal credentials, or silently perform network/write/delete actions.

## 2. Confirmed Product Decisions

- Generation uses a hybrid runtime: a configured remote model when available, otherwise an explicitly labelled local guidance mode.
- The product presents provider identities, not a misleading single “OpenAI settings” surface.
- Initial provider presets are Qwen/Alibaba Model Studio, Kimi/Moonshot, DeepSeek, GLM/Zhipu, OpenAI, and Custom.
- Global default model configuration may be overridden per project.
- API keys are write-only from the UI and API. The UI never displays any API-key characters.
- Windows Credential Manager stores secrets; SQLite stores metadata and an opaque credential reference only.
- Local read-only Agent tools may execute automatically. Network tools require confirmation. Write, delete, and export tools require confirmation.
- Next-step recommendations are chosen by a deterministic state machine. A model may only explain the recommendation.
- Complete examples remain immutable. Starting a walkthrough creates an editable project copy.
- Document editing uses autosaved drafts; only an explicit user action creates a formal version. Confirmed versions are immutable.
- History management uses a dedicated center. The home page continues to show the six most recent projects.
- Delivery uses staged vertical slices rather than simultaneous subsystem replacement.

## 3. Scope and Non-Goals

### In scope

- text-based product-Idea interpretation and solution generation;
- structured output and function/tool calling when the selected model supports them;
- provider/model profile CRUD, connection tests, capability probes, enable/disable, default selection, and project override;
- Markdown PRD/TechDoc editing with preview and section/line-oriented comparison;
- existing Markdown, JSON, and DOCX exports;
- project search, filters, sorting, copy, trash, restore, and guarded permanent deletion;
- desktop and mobile web interfaces;
- migration of an existing local SQLite database without losing current projects.

### Explicit non-goals

- claiming that a consumer chatbot subscription includes API access or credits;
- displaying, exporting, logging, auditing, or returning a saved API key;
- unrestricted autonomous agents, unlimited loops, arbitrary executable tools, or silent paid-model failover;
- automatic mutation of project claims, approved documents, or evidence status by a model;
- collaborative multi-user editing, comments, or permissions;
- a Word-like rich-text editor in this iteration; the editor is Markdown plus rendered preview;
- native support for every vendor-specific multimodal API. Unsupported models fail capability checks and remain disabled for solution generation;
- provider-native tools that bypass InsightForge's own tool permission policy.

## 4. Architecture

### 4.1 Components

`ModelProfileService`

- owns provider/profile metadata, revisions, default selection, and project overrides;
- returns sanitized response objects only;
- never receives a request to retrieve a key for display.

`CredentialStore`

- writes, replaces, resolves for immediate backend use, and deletes credentials;
- uses Windows Credential Manager through a narrow backend interface;
- returns only opaque credential references to application services;
- fails closed when the credential backend is unavailable;
- may read an environment-variable-backed profile, but never copies that secret into SQLite or an API response.

`ProviderRegistry`

- maps provider presets to a protocol adapter, default base URL, and safe configuration guidance;
- separates provider identity from wire protocol;
- initial protocol adapters are OpenAI-compatible Chat Completions and Anthropic-compatible Messages where supported;
- Qwen, Kimi, DeepSeek, GLM, and OpenAI presets may share an adapter without being presented as the same provider;
- Custom requires an explicit protocol and Base URL.

`CapabilityProbeService`

- checks authentication/connectivity and the capabilities required by InsightForge;
- records `basic_chat`, `structured_json`, `function_calling`, and `streaming` as supported, unsupported, or unknown;
- never infers capabilities solely from a model-name substring;
- expires results when the profile changes and after a bounded time-to-live;
- a test may incur provider usage, so the UI must label the action before execution.

`AgentRuntime`

- resolves the project override or global default profile;
- obtains the credential only for the duration of the provider request;
- enforces a maximum number of model/tool rounds;
- exposes only registered tools allowed by the current permission level;
- validates every final result against the existing IdeaBrief/Solution schemas;
- does not persist partial model output as a complete solution set.

`GuidanceService`

- computes home and project next actions from persisted workflow state;
- supplies a stable action code, explanation inputs, target view, and target control;
- may use the configured model to rewrite explanatory prose, but never to select the action code.

`DocumentDraftService`

- maintains one mutable draft per project/document type/user-local workspace;
- creates immutable document versions only on explicit “Save as new version”;
- detects stale draft bases and rejects silent overwrites;
- restores an older version by copying it into a new version.

`ProjectHistoryService`

- provides server-side search, filters, stable sorting, cursor pagination, copy lineage, and existing trash operations;
- copying creates a new project ID and records its source; it does not share mutable rows with the source project.

### 4.2 Request flow for arbitrary Ideas

```text
Idea submission
  -> persist original user input
  -> resolve project override or global default model profile
  -> if no usable profile: local guidance response
  -> load credential in backend memory
  -> call provider through selected protocol adapter
  -> optional bounded calls to allowed tools
  -> validate IdeaBrief and 2-3 distinct SolutionCandidates
  -> bounded repair retry for schema failures
  -> persist only a complete validated result
  -> on terminal failure: keep Idea and return a Chinese recovery action
```

There is no silent transition to a different paid model. The user must select another profile explicitly.

## 5. Data Model

### 5.1 `model_profiles`

- `id`
- `display_name`
- `provider`
- `protocol`
- `base_url`
- `model_id`
- `credential_ref`
- `enabled`
- `is_default`
- `capabilities_json`
- `capabilities_checked_at`
- `last_test_status`
- `last_tested_at`
- `revision`
- `created_at`
- `updated_at`

No secret or recoverable secret fragment is stored. The API exposes `credential_status: configured|missing`, not `credential_ref`.

### 5.2 `model_profile_revisions`

Stores non-secret configuration snapshots and timestamps for generation provenance. It never stores `credential_ref` or secret values.

### 5.3 `project_model_profiles`

Maps a project to an optional enabled profile. Missing mapping means “use the current global default.” Generation audit records still capture the exact profile revision used.

### 5.4 `document_drafts`

- `project_id`
- `doc_type`
- `base_version_id`
- `content`
- `draft_revision`
- `updated_at`

A unique constraint covers project and document type. Draft updates use optimistic concurrency through `draft_revision`.

### 5.5 `project_tour_progress`

- `project_id`
- `tour_id`
- `current_step`
- `completed_steps_json`
- `dismissed_at`
- `updated_at`

Only example copies may start the standard example tour.

### 5.6 `project_relations`

- `parent_project_id`
- `child_project_id`
- `relation_type` (`example_copy` or `project_copy`)
- `created_at`

This table records lineage without coupling later edits.

## 6. APIs

### 6.1 Model settings

- `GET /api/settings/model-profiles`
- `POST /api/settings/model-profiles`
- `PATCH /api/settings/model-profiles/{profile_id}`
- `DELETE /api/settings/model-profiles/{profile_id}`
- `POST /api/settings/model-profiles/{profile_id}/test`
- `POST /api/settings/model-profiles/{profile_id}/set-default`
- `PUT /api/projects/{project_id}/model-profile`

Create/update requests may contain a new API key. Responses never contain it. An empty key on update means keep the existing credential; an explicit replace action supplies a new one.

Deletion is rejected while a profile is the default or is explicitly selected by a project. The user must reassign those references first.

### 6.2 Guidance and examples

- `GET /api/home/next-action`
- `GET /api/projects/{project_id}/next-action`
- `GET /api/examples`
- `POST /api/examples/{example_id}/copies`
- `GET /api/projects/{project_id}/tour`
- `PATCH /api/projects/{project_id}/tour`

### 6.3 Document drafts and diffs

- `GET /api/projects/{project_id}/documents/{doc_type}/draft`
- `PUT /api/projects/{project_id}/documents/{doc_type}/draft`
- `POST /api/projects/{project_id}/documents/{doc_type}/versions`
- `GET /api/document-versions/{left_id}/diff/{right_id}`
- `POST /api/document-versions/{version_id}/restore-as-new`

Existing export routes remain canonical for Markdown, JSON, and DOCX.

### 6.4 History center

Extend `GET /api/projects` with `q`, `status`, `kind`, `sort`, `limit`, and `cursor`. Add:

- `POST /api/projects/{project_id}/copies`

Existing trash, restore, and permanent-delete routes remain canonical. Permanent deletion remains available only for already-trashed projects and requires an explicit confirmation in the UI.

## 7. User Experience

### 7.1 Home next action

The home page displays one primary recommendation:

1. continue the most recently updated incomplete active project;
2. otherwise start a complete example if no example tour has been completed;
3. otherwise create a new Idea.

The card states what to do, why it matters now, and one direct action. It does not display a competing list of recommendations.

### 7.2 Project next action state machine

Priority order:

1. confirm or refine inferred IdeaBrief;
2. generate solutions;
3. select a solution;
4. address the highest-priority unverified project claim;
5. generate or update PRD;
6. generate or update TechDoc;
7. confirm current healthy document versions;
8. export development handoff;
9. when all gates pass, show the project as ready without inventing a new task.

Each action deep-links to the relevant view/control. Persisted state, not model prose, determines completion.

### 7.3 Complete-example walkthrough

The home page shows two canonical complete examples. “Start walkthrough” creates a new editable copy and opens seven steps:

1. Idea interpretation;
2. compare three solution mechanisms;
3. choose MVP;
4. inspect key claims;
5. add/understand evidence;
6. edit PRD and TechDoc;
7. inspect development handoff.

The tour supports next, back, skip, and restart. It highlights the real product UI rather than rendering a separate fake workflow. Example copies are clearly labelled and may be trashed like other user projects.

### 7.4 Model settings

The settings center lists sanitized profile cards with provider, model, enabled/default state, capability status, and last connection result. Forms provide provider presets and an advanced area for protocol/Base URL.

The API-key field is blank on every edit. The only displayed secret-related text is “密钥已配置” or “尚未配置密钥.” There is no reveal, copy, masked-value, or last-four-character display.

### 7.5 Document workspace

PRD and TechDoc have separate tabs. The initial editor is a split Markdown editor and rendered preview. Autosave updates the draft only. “Save as new version” requires explicit confirmation and creates the next immutable version.

The version panel supports selection of any two active versions. The diff response provides unchanged, inserted, and deleted blocks. Restoring creates a new version whose provenance records the restored source version. Confirmed versions cannot be edited in place.

### 7.6 History center

The accepted layout is a dedicated management page:

- top search field;
- filters for active/example copy/canonical example/trashed;
- updated-time sorting;
- paginated project cards or rows;
- open, copy, and move-to-trash actions;
- a fixed Trash section with restore and guarded permanent deletion.

The home page continues to show the latest six active/example-copy projects and links to the center.

## 8. Agent and Tool Safety

Tool classes:

- `local_read`: may run automatically;
- `network_read`: requires user confirmation immediately before execution;
- `local_write`: requires user confirmation;
- `delete`: requires user confirmation and existing lifecycle guards;
- `export`: requires user confirmation.

The runtime permits only tools registered for the current task. It rejects unknown tool names and invalid arguments before execution. The maximum loop count is fixed by configuration and recorded in the generation trace. Tool results are treated as evidence inputs with provenance, not automatically as validated business facts.

API keys are injected into the provider client only. They are excluded from messages, tool schemas, tool arguments, exceptions returned to the client, audit payloads, and telemetry.

## 9. Failure Handling

All provider failures map to stable internal error codes and Chinese recovery messages:

- invalid credential -> replace the key;
- insufficient balance/quota -> select another profile or use local guidance;
- unknown model -> edit model ID or select a known model;
- rate limit/timeout -> bounded retry, then retry later or use local guidance;
- unsupported structured output -> plain completion followed by strict schema parsing;
- unsupported function calling -> continue without tools when the task allows it, otherwise explain the missing capability;
- repeated schema failure -> retain the Idea and show missing/invalid sections; never save a fake complete result;
- unavailable credential backend -> disable stored-secret profiles and explain how to repair local credential storage.

Provider response bodies are sanitized before logging or returning. The UI preserves all user-entered Idea fields across failures.

## 10. Delivery Stages

### Stage 1: Secure multi-provider generation

- schema migration for model profiles/revisions/project overrides;
- Windows credential backend;
- provider registry and protocol adapters;
- provider settings UI;
- connection/capability tests;
- hybrid runtime and friendly failure mapping;
- generation provenance and secret-leak tests.

### Stage 2: Guidance and complete examples

- home/project next-action state machine;
- next-action UI cards and deep links;
- immutable examples, copy creation, and lineage;
- seven-step walkthrough and persisted progress.

### Stage 3: Document workspace

- draft storage and optimistic concurrency;
- Markdown editor/preview;
- explicit version creation;
- version diff and restore-as-new;
- existing export integration.

### Stage 4: History center

- server-side query/filter/sort/pagination;
- dedicated history UI;
- copy and lineage;
- trash, restore, and guarded permanent deletion;
- home recent-project integration.

Each stage is independently deployable and must leave the full test suite green before the next begins.

## 11. Verification and Acceptance

### Security

- API responses, SQLite content, audit rows, logs, exceptions, exports, and handoff packages contain no submitted API key or recoverable fragment.
- Updating without a new key preserves the credential; replacing changes it; deletion removes it from Windows Credential Manager.
- a model profile cannot be deleted while referenced as default or by a project.

### Provider/runtime

- adapter contract tests cover Qwen, Kimi, DeepSeek, GLM, OpenAI, and Custom profiles without live paid calls;
- optional live smoke tests run only with explicit user authorization and report possible cost;
- arbitrary Idea failures preserve input and return a recovery action;
- schema-invalid output never becomes a completed IdeaBrief/solution set;
- Agent loop and tool permissions cannot be bypassed by model output.

### Guidance/examples

- every lifecycle state maps to exactly one expected next action;
- deep links focus the intended view/control;
- canonical examples remain unchanged after walkthrough activity;
- copies retain lineage and independent mutable data;
- tour progress survives restart and supports skip/restart.

### Documents

- autosave changes only the draft;
- stale draft revisions produce a conflict instead of overwriting;
- formal save creates a monotonically increasing immutable version;
- diff labels additions/deletions correctly;
- restore creates a new version;
- Markdown, JSON, and DOCX exports use the selected version.

### History

- search covers title and summary;
- filters and stable sorting work with pagination;
- copied projects have new IDs and independent data;
- trash excludes projects from active lists;
- restore returns them;
- permanent deletion works only from trash after explicit confirmation.

### System verification

- migrations run against a copy of the existing SQLite database;
- `PRAGMA integrity_check` returns `ok` and `foreign_key_check` returns no rows;
- all automated tests pass;
- Python compile and JavaScript syntax checks pass;
- desktop and mobile browser workflows pass with no console errors;
- the actual `start.bat` entry starts successfully against the migrated local database.

## 12. Risks and Controls

- **Provider drift:** presets and capability probes are versioned; unknown capabilities fail closed.
- **Secret leakage:** credential storage is isolated and covered by sentinel-secret scans across every persistence/output boundary.
- **Unexpected cost:** no silent model failover; connection tests and network tool calls are explicit; retry counts are bounded.
- **False domain confidence:** local fallback is labelled guidance, and schema completeness is not presented as market evidence.
- **Migration damage:** migration is additive, transactional, idempotent, and first tested on a copied database.
- **History clutter from examples:** example copies are labelled and filterable, and may be moved to trash.
- **Document version explosion:** autosave writes drafts; only explicit save creates a formal version.

