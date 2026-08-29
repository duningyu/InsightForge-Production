# InsightForge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, locally runnable project knowledge base that ingests sources, performs project-scoped hybrid retrieval, generates cited PRD/TechDoc drafts, validates them in a bounded loop, manages versions, exports artifacts, and exposes a local MCP server.

**Architecture:** A FastAPI backend and SQLite database own projects, canvases, sources, chunks, document versions, generation runs, validation issues, and audit records. A deterministic local generator uses retrieved evidence and project canvas values to produce reproducible documents; an optional LLM adapter may replace text generation without bypassing citation and quality validators.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, SQLite, pytest, python-docx, pypdf, vanilla HTML/CSS/JavaScript, MCP Python SDK v2.

**Spec:** `docs/specs/insightforge-design.md`

## Global Constraints

- Default execution must not require an external API key.
- Retrieval and citations must be scoped to one `project_id`.
- Every source must retain a declared source type and authority score.
- `simulated_research` and `model_hypothesis` must never be presented as verified real-user findings.
- Automated document repair must stop after at most 2 rounds.
- Model-accessible tools must not publish externally, delete projects, or overwrite approved versions.
- MCP uses local STDIO by default and logs only to stderr.

---

### Task 1: Application skeleton, project database, and seed project

**Files:**
- Create: `insightforge/pyproject.toml`
- Create: `insightforge/app/__init__.py`
- Create: `insightforge/app/config.py`
- Create: `insightforge/app/db.py`
- Create: `insightforge/app/schemas.py`
- Create: `insightforge/tests/conftest.py`
- Create: `insightforge/tests/test_db.py`

**Interfaces:**
- Produces: `Settings`, `Database`, schema initialization, and idempotent demo seed with project `project_insightforge_demo`.

- [ ] **Step 1: Write failing database tests**

```python
def test_seed_contains_project_canvas_and_sources(db):
    db.seed_demo_data()
    assert len(db.fetch_all("SELECT * FROM projects")) == 1
    assert len(db.fetch_all("SELECT * FROM project_canvas")) == 1
    assert len(db.fetch_all("SELECT * FROM sources")) >= 4


def test_seed_is_idempotent(db):
    db.seed_demo_data(); db.seed_demo_data()
    assert len(db.fetch_all("SELECT * FROM projects")) == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd insightforge && pytest tests/test_db.py -q`
Expected: import failure because database modules are absent.

- [ ] **Step 3: Implement schema, connection helpers, canvas JSON storage, and explicit source authority fields**

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd insightforge && pytest tests/test_db.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add insightforge
git commit -m "feat(insightforge): add project database and seed data"
```

### Task 2: File ingestion, normalized chunks, and source-boundary preservation

**Files:**
- Create: `insightforge/app/ingestion.py`
- Create: `insightforge/app/services/__init__.py`
- Create: `insightforge/app/services/sources.py`
- Create: `insightforge/tests/test_ingestion.py`

**Interfaces:**
- Produces: `extract_text(filename, bytes)`, `chunk_text(text, max_chars, overlap)`, and `SourceService.add_source(...)`.
- Supported formats: TXT, MD, JSON, DOCX, PDF.

- [ ] **Step 1: Write failing ingestion tests**

```python
def test_chunk_text_is_deterministic_and_overlapping():
    chunks = chunk_text("第一段。第二段。第三段。" * 40, max_chars=120, overlap=20)
    assert len(chunks) > 1
    assert chunks == chunk_text("第一段。第二段。第三段。" * 40, 120, 20)


def test_source_type_is_preserved(db):
    source = SourceService(db).add_source(
        project_id="project_insightforge_demo", title="模拟访谈",
        source_type="simulated_research", authority=0.4,
        content="这是人工构造的访谈样本。", filename="sample.txt",
    )
    assert source["source_type"] == "simulated_research"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd insightforge && pytest tests/test_ingestion.py -q`
Expected: import failure because ingestion services are absent.

- [ ] **Step 3: Implement parsers, deterministic chunk IDs, overlap validation, source and chunk persistence**

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd insightforge && pytest tests/test_ingestion.py -q`
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add insightforge/app/ingestion.py insightforge/app/services insightforge/tests/test_ingestion.py
git commit -m "feat(insightforge): add multi-format source ingestion"
```

### Task 3: Project-scoped hybrid RAG and authority-aware evidence packages

**Files:**
- Create: `insightforge/app/retrieval.py`
- Create: `insightforge/app/services/retrieval_service.py`
- Create: `insightforge/tests/test_retrieval.py`

**Interfaces:**
- Produces: `HybridRetriever.search(...)` and `ProjectRetrievalService.retrieve_project_sources(project_id, query, top_k, source_types=None)`.
- Evidence includes source ID, chunk ID, source type, authority, content, and score components.

- [ ] **Step 1: Write failing retrieval tests**

```python
def test_retrieval_never_crosses_project_scope(db):
    service = ProjectRetrievalService(db)
    hits = service.retrieve_project_sources("project_insightforge_demo", "竞品分析", 8)
    assert hits
    assert {hit["project_id"] for hit in hits} == {"project_insightforge_demo"}


def test_authority_breaks_close_score_ties():
    docs = [
        {"chunk_id": "low", "content": "目标用户需要结构化 PRD", "authority": 0.2},
        {"chunk_id": "high", "content": "目标用户需要结构化 PRD", "authority": 0.9},
    ]
    assert HybridRetriever().search("结构化 PRD", docs, 1)[0]["chunk_id"] == "high"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd insightforge && pytest tests/test_retrieval.py -q`
Expected: import failure because retrieval modules are absent.

- [ ] **Step 3: Implement BM25, TF-IDF cosine, normalization, authority weighting, source filters, and citation payloads**

Use `0.55 * bm25 + 0.30 * cosine + 0.15 * authority` after normalizing retrieval components.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd insightforge && pytest tests/test_retrieval.py -q`
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add insightforge/app/retrieval.py insightforge/app/services/retrieval_service.py insightforge/tests/test_retrieval.py
git commit -m "feat(insightforge): add authority-aware project RAG"
```

### Task 4: Cited document generation and bounded quality loop

**Files:**
- Create: `insightforge/app/services/generation.py`
- Create: `insightforge/app/services/validation.py`
- Create: `insightforge/app/services/loop.py`
- Create: `insightforge/tests/test_generation_loop.py`

**Interfaces:**
- Produces: `LocalDocumentGenerator.generate(doc_type, canvas, evidence)`, `DocumentValidator.validate(...)`, and `DocumentLoop.run(...)`.
- Document types: `prd`, `techdoc`.
- Terminal states: `completed`, `needs_human_review`, `budget_exhausted`.

- [ ] **Step 1: Write failing generation-loop tests**

```python
def test_generated_prd_contains_citations_and_source_labels(db):
    result = DocumentLoop(db).run("project_insightforge_demo", "prd")
    assert "[source:" in result["content"]
    assert "simulated_research" in result["content"]


def test_validator_rejects_unqualified_real_research_claim():
    issues = DocumentValidator().validate(
        content="真实用户调研证明所有用户都需要该功能。",
        valid_citations={}, canvas={}
    )
    assert any(issue["code"] == "unsupported_real_research_claim" for issue in issues)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd insightforge && pytest tests/test_generation_loop.py -q`
Expected: import failure because generation and loop services are absent.

- [ ] **Step 3: Implement reproducible templates, citation map, required-section validator, claim-boundary validator, repair pass, version persistence, and two-round stop**

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd insightforge && pytest tests/test_generation_loop.py -q`
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add insightforge/app/services insightforge/tests/test_generation_loop.py
git commit -m "feat(insightforge): add cited document quality loop"
```

### Task 5: Strict Function Calling registry and FastAPI endpoints

**Files:**
- Create: `insightforge/app/tools.py`
- Create: `insightforge/app/main.py`
- Create: `insightforge/tests/test_tools.py`
- Create: `insightforge/tests/test_api.py`

**Interfaces:**
- Tools: `retrieve_project_sources`, `get_project_canvas`, `create_document_draft`, `run_document_validator`, `export_artifact`, `approve_document_version`.
- Endpoints: `/api/health`, `/api/projects`, `/api/projects/{id}`, `/api/projects/{id}/canvas`, `/api/projects/{id}/sources`, `/api/projects/{id}/retrieve`, `/api/projects/{id}/generate`, `/api/documents/{version_id}`, `/api/documents/{version_id}/validate`, `/api/documents/{version_id}/approve`, `/api/audit`.

- [ ] **Step 1: Write failing tool and API tests**

```python
def test_tool_schemas_are_strict(registry):
    for tool in registry.schemas():
        assert tool["function"]["strict"] is True
        assert tool["function"]["parameters"]["additionalProperties"] is False


def test_generate_endpoint_returns_version(client):
    response = client.post("/api/projects/project_insightforge_demo/generate", json={"doc_type": "prd"})
    assert response.status_code == 200
    assert response.json()["version_id"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd insightforge && pytest tests/test_tools.py tests/test_api.py -q`
Expected: import failure because tools and app are absent.

- [ ] **Step 3: Implement strict schemas, risk gates, route models, file uploads, validation errors, and audit events**

L2 approval requires `human_confirmed=true`; approved versions cannot be overwritten.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd insightforge && pytest tests/test_tools.py tests/test_api.py -q`
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add insightforge/app/tools.py insightforge/app/main.py insightforge/tests
git commit -m "feat(insightforge): add strict tools and API"
```

### Task 6: Browser UI, artifact exports, MCP server, optional LLM adapter, and documentation

**Files:**
- Create: `insightforge/app/static/index.html`
- Create: `insightforge/app/static/styles.css`
- Create: `insightforge/app/static/app.js`
- Create: `insightforge/app/exporters.py`
- Create: `insightforge/app/mcp_server.py`
- Create: `insightforge/app/llm.py`
- Create: `insightforge/scripts/start.sh`
- Create: `insightforge/scripts/start.ps1`
- Create: `insightforge/scripts/start_mcp.sh`
- Create: `insightforge/scripts/start_mcp.ps1`
- Create: `insightforge/.env.example`
- Create: `insightforge/README.md`
- Create: `insightforge/docs/ARCHITECTURE.md`
- Create: `insightforge/docs/API.md`
- Create: `insightforge/docs/RAG_AND_SOURCE_GOVERNANCE.md`
- Create: `insightforge/docs/FUNCTION_CALLING.md`
- Create: `insightforge/docs/MCP.md`
- Create: `insightforge/docs/CLAIM_BOUNDARY.md`
- Create: `insightforge/tests/test_exports_and_mcp.py`

**Interfaces:**
- Export formats: Markdown, JSON, DOCX.
- MCP resources: `project://{project_id}/canvas`, `project://{project_id}/documents/{version_id}`, `project://{project_id}/sources/{source_id}`.
- MCP tools: `retrieve_project_sources`, `create_artifact_draft`, `get_document_version`.

- [ ] **Step 1: Write failing export and MCP business-function tests**

```python
def test_markdown_and_docx_export_are_nonempty(exporter, completed_version):
    assert exporter.to_markdown(completed_version).startswith("#")
    assert len(exporter.to_docx_bytes(completed_version)) > 500


def test_mcp_retrieval_wrapper_is_project_scoped(mcp_functions):
    result = mcp_functions.retrieve_project_sources("project_insightforge_demo", "项目目标", 5)
    assert result["items"]
    assert {item["project_id"] for item in result["items"]} == {"project_insightforge_demo"}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd insightforge && pytest tests/test_exports_and_mcp.py -q`
Expected: import failure because exporters and MCP wrappers are absent.

- [ ] **Step 3: Implement exports, UI, pure MCP business wrappers, MCP decorators, optional OpenAI adapter, scripts, and operating docs**

Use `mcp.run(transport="stdio")`; no `print()` calls in the STDIO server.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd insightforge && pytest tests/test_exports_and_mcp.py -q`
Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add insightforge
git commit -m "feat(insightforge): add UI exports MCP and docs"
```

### Task 7: Full verification and distributable archive

**Files:**
- Copy: `ai_pm_rag_mcp_prd/InsightForge_PRD_RAG_MCP_FunctionCalling_Loop融合规划版_v0.4.docx` to `insightforge/docs/PRD_InsightForge.docx`
- Create: `insightforge/Makefile`
- Create: `insightforge/docker-compose.yml`
- Create: `insightforge/Dockerfile`
- Create: `insightforge/.dockerignore`

**Interfaces:**
- Produces a source archive excluding environments, databases, caches, generated artifacts, and secrets.

- [ ] **Step 1: Run complete tests**

Run: `cd insightforge && pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Run compile verification**

Run: `cd insightforge && python -m compileall -q app`
Expected: exit code 0.

- [ ] **Step 3: Run API smoke test**

Start Uvicorn, call health, project list, retrieval, generation, and Markdown export endpoints, then stop it.
Expected: HTTP 200 and a generated version with valid citations.

- [ ] **Step 4: Verify archive contents and create SHA-256**

Create `InsightForge_Complete_Runnable.zip`, ensure no `.env`, database, cache, virtual environment, or generated private source is present, and compute SHA-256.

- [ ] **Step 5: Commit**

```bash
git add insightforge
git commit -m "build(insightforge): add reproducible distribution package"
```
