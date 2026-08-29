# InsightForge 3.0 API Contract

All P0 project mutations are application-owned. An LLM adapter is never authorized to bypass human confirmation, evidence validation, artifact health, or project scope.

## Health

```http
GET /api/health
```

Returns release identity and runtime modes, including `version=3.0.0` and `structured_runtime_mode`.

## 1. Quick Value

### Create project + IdeaBrief

```http
POST /api/projects/quick-start
```

```json
{
  "idea": "帮小型便利店减少缺货",
  "target_user": null,
  "resources": [],
  "priority": "fast_mvp"
}
```

Returns `201`. The resulting IdeaBrief may contain at most one decision-critical clarification.

### Read/confirm/refine IdeaBrief

```http
GET  /api/projects/{project_id}/idea-brief
POST /api/projects/{project_id}/idea-brief/confirm
POST /api/projects/{project_id}/idea-brief/refine
```

Confirmation body:

```json
{"human_confirmed": true, "note": "确认系统理解"}
```

This confirms understanding, not market validation.

### Generate/list solutions

```http
POST /api/projects/{project_id}/solutions/generate
GET  /api/projects/{project_id}/solutions
```

Candidates contain mechanism, why-fit, user flow, MVP pages/features, inputs/outputs, decision logic, data requirements, technical components, implementation plan, acceptance cases, risks, unknowns, complexity, and validator dimensions.

### Select solution

```http
POST /api/projects/{project_id}/solutions/select
```

Single:

```json
{
  "strategy": "single",
  "candidate_ids": ["solution_id"],
  "rationale": "先验证最低依赖方案",
  "human_confirmed": true
}
```

Staged selection uses two or more existing ordered candidate IDs. It does not invent a fourth blended candidate.

## 2. Project Snapshot

```http
GET /api/projects/{project_id}/snapshot
GET /api/projects/{project_id}/snapshots
GET /api/project-snapshots/{snapshot_id}
```

Snapshot versions are immutable. `health` and `ux_state` describe current usability separately from historical content.

## 3. Project Claims and Evidence

```http
GET  /api/projects/{project_id}/claims
GET  /api/projects/{project_id}/claims/{claim_id}
POST /api/projects/{project_id}/evidence/analyze
GET  /api/projects/{project_id}/evidence/impact
```

Analyze request:

```json
{"claim_ids": ["claim_id"]}
```

The structured runtime can only propose relations. Persistence validates source/chunk scope, active state, source-type policy, exact `evidence_span`, and retrieval trace.

### Source library

```http
POST /api/projects/{project_id}/sources
POST /api/projects/{project_id}/sources/upload
GET  /api/projects/{project_id}/sources
POST /api/projects/{project_id}/sources/{source_id}/archive
POST /api/projects/{project_id}/sources/{source_id}/restore
```

Archive/restore uses dependency propagation; historical artifacts are not rewritten.

### Advanced retrieval

```http
POST /api/projects/{project_id}/retrieve
GET  /api/projects/{project_id}/retrieval-runs
GET  /api/retrieval/runs/{run_id}
GET  /api/retrieval/profiles
```

These endpoints expose traceable retrieval detail but are not the default user journey.

## 4. Change Proposals

```http
GET  /api/projects/{project_id}/change-proposals
POST /api/change-proposals/{proposal_id}/accept
POST /api/change-proposals/{proposal_id}/reject
POST /api/change-proposals/{proposal_id}/defer
```

All three decisions require explicit `human_confirmed=true`. Acceptance checks that `from_snapshot_id` is still the current Snapshot before creating the next immutable version.

## 5. Documents

### Generate from current Snapshot

```http
POST /api/projects/{project_id}/documents/generate
```

```json
{"doc_type": "prd", "idempotency_key": "optional-key"}
```

3.0 generation requires a current confirmed Snapshot and persists artifact dependencies/health.

### Read/validate/confirm/export

```http
GET  /api/documents/{version_id}
GET  /api/documents/{version_id}/claims
POST /api/documents/{version_id}/validate
POST /api/document-versions/{version_id}/confirm
GET  /api/documents/{version_id}/export?format=md|json|docx
```

Confirmation requires an active, validation-passed, healthy current version. The compatibility endpoint below remains but is deprecated:

```http
POST /api/documents/{version_id}/approve
```

## 6. Handoff

```http
GET  /api/projects/{project_id}/handoff/readiness
POST /api/projects/{project_id}/handoff/export
```

Readiness is `false` if the current Snapshot or current confirmed PRD/TechDoc is missing or unhealthy.

## 7. Legacy endpoints

The following Guided endpoints are deprecated and only operate when a legacy `guided_sessions` row already exists:

```http
GET  /api/projects/{project_id}/guide
POST /api/projects/{project_id}/guide/respond
POST /api/projects/{project_id}/guide/apply
POST /api/projects/{project_id}/guide/reset
POST /api/projects/{project_id}/guide/back
```

A new 3.0 project never creates a Guided session automatically.

Legacy Canvas endpoints remain for compatibility, but direct Canvas mutation is rejected for Snapshot-managed projects.

## 8. Error semantics

- `403` — explicit human confirmation required.
- `404` — project/artifact/legacy session not found.
- `409` — current-state conflict, stale Change Proposal, Snapshot-managed Canvas conflict, etc.
- `422` — invalid evidence scope/span/policy or invalid request behavior.
- `503` — selected structured runtime unavailable; no silent deterministic fallback.
