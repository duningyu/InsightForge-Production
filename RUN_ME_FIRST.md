# Run InsightForge 3.0 First

## 1. Start the application

### Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start.ps1
```

### macOS/Linux

```bash
chmod +x scripts/start.sh scripts/start_mcp.sh
./scripts/start.sh
```

Open `http://127.0.0.1:8000`.

The local default uses `deterministic_demo` for frozen semantic examples and a deterministic document generator. No cloud API key is required. Demo output is explicitly limited to frozen cases; unsupported arbitrary ideas fail instead of pretending they were understood.

## 2. Use the 3.0 first-value path

1. On the first screen, enter one rough product Idea.
2. Review the generated IdeaBrief. If the ambiguity is decision-critical, answer the one clarification question; otherwise continue with explicit unknowns.
3. Confirm that the system understood the Idea. This does **not** confirm market demand.
4. Generate 2–3 domain-specific solution candidates. At least one low-AI/non-LLM baseline is required unless the problem inherently requires an LLM core.
5. Select a single solution or a staged path and explicitly confirm the decision.
6. Review **Project Snapshot v1**: target user, problem, chosen solution, MVP, inputs/outputs, technical plan, unknowns, and the next-best validation action.

## 3. Add evidence only when it reduces uncertainty

Open **证据 / Evidence**:

- `关键判断` shows project-level Claims and their current evidence status;
- `影响记录` shows material evidence changes and Change Proposals;
- `资料库` contains sources and archive/restore controls.

Evidence must point to an exact source/chunk span. New evidence may support, contradict, or contextualize a Claim; it cannot silently rewrite a formal Snapshot. Accepting a material Change Proposal creates a new Snapshot version.

## 4. Generate and confirm documents

Open **文档 / Documents**:

1. Generate PRD or TechDoc from the current Snapshot plus project evidence context.
2. Read validation issues and artifact health.
3. Use **确认此版本 / Confirm this version** only when the version is validation-passed and healthy.

If an underlying source is later archived, dependent document health can become `stale_evidence`; historical content remains immutable.

## 5. Handoff

Open **开发交接 / Handoff**. The system fails closed until:

- the current Project Snapshot is healthy;
- one current Snapshot-bound PRD is confirmed and healthy;
- one current Snapshot-bound TechDoc is confirmed and healthy.

When ready, export the AI Coding ZIP. It includes the current Snapshot, MVP scope, unresolved risks, confirmed context/documents, sources, claim ledger, retrieval trace, acceptance cases, implementation tasks, `AGENTS.md`, and a SHA-256 manifest.

## 6. Optional provider-backed structured generation

Open **Settings**, create a provider profile, enter the write-only API key, test the connection, and set the profile as the global default or a project override. Environment variables such as `OPENAI_API_KEY` do not select a provider. Provider failures preserve the Idea and return explicit recovery actions; the system never silently switches to another paid profile.

## 7. Optional local MCP

```text
python -m app.mcp_server
```

MCP is a local STDIO handoff/read interface. It cannot bypass artifact health or human confirmation.

## 8. Verify the checkout

```bash
pytest -q
python -m compileall -q app tests
node --check app/static/app.js
```

See `VERIFICATION_REPORT.md` and `docs/MIGRATION_2_0_6_TO_3_0.md` for release evidence and migration boundaries.
