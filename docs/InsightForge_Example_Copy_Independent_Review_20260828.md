# InsightForge Example Copy — Independent Review

- Review time (UTC): 2026-08-28T02:56:09.192964+00:00
- Source baseline: `InsightForge_Current_Runnable_WIP_20260828_071251.zip`
- Targeted test return code: `0`
- Targeted test duration: `17.6` seconds

## Review scope

The review checks project/example copy behavior, independent identity/lineage fields, and targeted regression coverage.
It does not treat UI screenshots alone as proof of database isolation.

## Relevant implementation and test locations

### `tests/test_example_copy.py`

- L8: `from app.services.example_copies import ExampleCopyService`
- L77: `) VALUES ('parent','child','example_copy','now')"""`
- L87: `"relation_type": "example_copy",`
- L92: `def test_copy_creates_fresh_ids_and_rewrites_the_complete_example_graph(examples_db):`
- L93: `copied = ExampleCopyService(examples_db).copy(CANONICAL_ID, actor="tour_user")`
- L99: `assert copied["relation_type"] == "example_copy"`
- L236: `def test_seed_rerun_preserves_canonical_ids_and_does_not_touch_copy_or_ordinary_project(examples_db):`
- L244: `child_id = ExampleCopyService(examples_db).copy(CANONICAL_ID, actor="tour_user")["id"]`
- L271: `def test_full_copy_keeps_independent_selected_solution_and_handoff_readiness(examples_db):`
- L274: `copied = ExampleCopyService(examples_db).copy(CANONICAL_ID, actor="tour_user")`
- L288: `service = ExampleCopyService(examples_db)`
- L312: `def test_copy_rejects_noncanonical_projects_and_blank_actors(examples_db):`
- L313: `service = ExampleCopyService(examples_db)`
- L321: `def test_copy_rolls_back_every_row_when_the_final_audit_write_fails(examples_db, monkeypatch):`
- L322: `service = ExampleCopyService(examples_db)`

### `app/db.py`

- L69: `relation_type TEXT NOT NULL CHECK(relation_type IN ('example_copy','project_copy')),`

### `app/main.py`

- L25: `ExampleCopyResponse,`
- L62: `from app.services.example_copies import ExampleCopyService`
- L134: `application.state.example_copies = ExampleCopyService(db)`
- L297: `response_model=ExampleCopyResponse,`
- L299: `def copy_canonical_example(`
- L303: `return application.state.example_copies.copy(example_id, actor=x_actor)`

### `app/schemas.py`

- L48: `class ExampleCopyResponse(StrictModel):`
- L57: `relation_type: Literal["example_copy"]`

### `app/services/example_copies.py`

- L32: `class ExampleCopyService:`
- L33: `"""Create an editable, independently keyed copy of a canonical example."""`
- L116: `def copy(self, example_id: str, actor: str) -> dict[str, Any]:`
- L304: `idempotency_key=f"example-copy:{child_id}:{uuid.uuid4().hex}",`
- L391: `) VALUES (?,?,'example_copy',?)""",`
- L402: `"relation_type": "example_copy",`
- L415: `"relation_type": "example_copy",`

### `docs/superpowers/plans/2026-08-28-stage-4-history-center.md`

- L7: `**Architecture:** `ProjectHistoryService` builds parameterized SQLite queries and cursor pagination. `ProjectCopyService` performs a deep transactional copy with lineage; the new UI is a separate history view while the home page retains six recent cards.`
- L29: `- [ ] Write failing tests with literal projects for title/summary search, active/example/example-copy/trashed filters, three sorts, limit bounds, stable same-timestamp ordering, cursor continuation, and SQL-injection strings.`
- L35: `### Task 2: Deep Project Copy and Lineage`
- L41: `- [ ] Write failing tests for fresh project/canvas/source/chunk/document/version/snapshot/claim/decision IDs, copied content, independent later edits, lineage, and rejection of trashed source projects.`

### `docs/superpowers/plans/2026-08-28-stage-2-guidance-and-example-tour.md`

- L5: `**Goal:** Give users one trustworthy next action and a copy-on-start walkthrough of two complete examples.`
- L7: `**Architecture:** `GuidanceService` maps persisted lifecycle state to one action code. `ExampleCopyService` transactionally clones immutable examples, while `TourService` stores progress and highlights the real workspace UI.`
- L34: `### Task 2: Example Copy and Lineage`
- L36: `**Files:** Modify `app/db.py`; create `app/services/example_copies.py`; modify `app/schemas.py app/main.py`; test `tests/test_example_copy.py`.`
- L38: `**Interfaces:** `ExampleCopyService.copy(example_id, actor) -> dict`; table `project_relations(parent_project_id, child_project_id, relation_type, created_at)`.`
- L42: `- [ ] Add idempotent schema and a single copy transaction. Generate fresh IDs and rewrite internal foreign keys; record `example_copy` lineage.`
- L52: `- [ ] Write failing tests for start-only-on-example-copy, next/back/skip/restart, invalid step rejection, and restart persistence.`

### `docs/superpowers/specs/2026-08-28-insightforge-guidance-models-documents-history-design.md`

- L29: `- Complete examples remain immutable. Starting a walkthrough creates an editable project copy.`
- L116: `- provides server-side search, filters, stable sorting, cursor pagination, copy lineage, and existing trash operations;`
- L194: `- `relation_type` (`example_copy` or `project_copy`)`
- L197: `This table records lineage without coupling later edits.`
- L272: `The home page shows two canonical complete examples. “Start walkthrough” creates a new editable copy and opens seven steps:`
- L301: `- filters for active/example copy/canonical example/trashed;`
- L307: `The home page continues to show the latest six active/example-copy projects and links to the center.`
- L354: `- immutable examples, copy creation, and lineage;`
- L369: `- copy and lineage;`
- L396: `- copies retain lineage and independent mutable data;`

## Targeted test output

```text
Spreadsheet runtime warmup failed during python startup
Traceback (most recent call last):
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/patches/warm_spreadsheet_runtime_on_startup.py", line 26, in warm_spreadsheet_runtime_on_startup
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py", line 772, in warm_spreadsheet_runtime
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/connection.py", line 37, in get_or_create_client
  File "/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/daemon.py", line 124, in start_daemon
TimeoutError: Timed out waiting for artifact tool daemon socket. Set ARTIFACT_TOOL_RPC_DAEMON_STARTUP_TIMEOUT_S=<seconds> to increase the limit.
[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m.[0m[32m                                                                [100%][0m
[32m[32m[1m9 passed[0m[32m in 9.50s[0m[0m
```

## Conclusion

- Targeted copy/example tests completed with return code 0.
- The implementation contains explicit copy/clone/lineage-related code paths listed above.
- This supports an engineering claim that copy behavior and lineage are covered by the current package.
- It does not by itself prove production-scale concurrency, cross-tenant authorization, or long-term retention behavior.
