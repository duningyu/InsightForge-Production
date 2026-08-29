# MCP Boundary and Resources — InsightForge 3.0

InsightForge ships a **local STDIO MCP server** for reading current handoff context. MCP is an optional interoperability layer after the product definition is stable; it is not the core differentiator and does not verify truth.

Run:

```text
python -m app.mcp_server
```

## Resources

```text
insightforge://projects/{project_id}/snapshot/current
insightforge://projects/{project_id}/documents/prd/current
insightforge://projects/{project_id}/documents/techdoc/current
insightforge://projects/{project_id}/mvp-scope
insightforge://projects/{project_id}/unresolved-risks
```

Document resources return only current confirmed healthy versions. A stale dependency cannot be hidden by the MCP transport.

## Tools

```text
get_current_project_context(project_id)
build_handoff_manifest(project_id, target_client)
```

These tools read or prepare a non-binary manifest. They do not confirm decisions, accept Change Proposals, publish, delete, or overwrite artifacts.

## Security/product boundary

Implemented scope:

- local process STDIO;
- application-owned SQLite/project scope;
- current Snapshot + healthy confirmed handoff context;
- no protocol path around normal service rules.

Not implemented/claimed:

- remote MCP deployment;
- OAuth authorization flow;
- enterprise tenant/RBAC administration;
- production ATS/Notion/Figma/Codex remote integration;
- multi-client synchronization;
- MCP as a source of market or semantic truth.

If Markdown/ZIP handoff is sufficient in real use, remote MCP remains unnecessary.
