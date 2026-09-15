# IF Guide R1.1 — M0 Workspace Map

Status: repository-grounded map created during M0. This document records the
current implementation boundary; it does not replace the existing product
contracts or authorize Provider/Search execution.

## Runtime and startup

- Application factory: `app/main.py:create_app`.
- Persistence bootstrap: `app/db.py:Database.init_schema`, which applies the
  base schema, existing Real Idea evaluation migrations, and the M1
  `app/migrations/if_guide_m1.py` migration in one database initialization path.
- Local test bootstrap: `tests/conftest.py` creates an isolated SQLite database,
  initializes the schema, optionally seeds demo data, and creates a FastAPI
  `TestClient`.
- Account mode: `app/accounts.py:create_account_app` creates an account-scoped
  child application with an account-specific database. The account middleware
  injects the authoritative `X-Actor`; client-supplied database/workspace/actor
  overrides are not a supported isolation mechanism.

## Project and history model

- Project service: `app/services/projects.py:ProjectService`.
- Public project creation: `POST /api/projects` in `app/main.py`; its request
  schema is `ProjectCreateRequest` and currently accepts only title/summary.
- Project identity: `projects.id`, title, summary, status, snapshots, and
  timestamps. Existing evaluation projects use the existing `project_origin`
  and `exclude_from_beta_metrics` fields through internal service contracts.
- History/trash: `ProjectService.history`, `move_to_trash`,
  `restore_from_trash`, and `purge_from_trash`.
- Project graph: `project_snapshots`, claims/decisions, sources, document
  versions, handoff records, and artifact health tables are connected by
  project IDs and current-version/snapshot fields. M1 must not rewrite these
  older artifacts.

## IdeaBrief and downstream product path

- QuickStart entry: `POST /api/projects/quick-start` handled by
  `app/services/quick_start.py:QuickStartService`.
- IdeaBrief persistence/confirmation: the same service exposes the current
  brief, refinement, and official confirmation paths; the `idea_briefs` table
  stores version, semantic fields, provenance, clarification state, and
  confirmation status.
- Solutions: `app/services/solution_design.py:SolutionDesignService`, with
  structured runtime/provider dispatch, validation, persistence, and existing
  Stage B one-shot/evaluation controls. M1 does not call or alter it.
- Snapshot: `app/services/snapshots.py:SnapshotService`, used to carry stable
  project/selection context into later artifacts.
- Documents: `app/services/document_versions.py`, `app/services/loop.py`,
  `app/services/generation.py`, and `app/services/document_workspace.py` cover
  document generation, versioning, editing, validation, and restore flows.
- Handoff: `app/services/handoff.py:HandoffService` assembles the existing
  handoff package from bound project artifacts; M1 does not change it.

## Current quality and evaluation reuse map

The repository already has an evaluation-only quality subsystem and it is the
reuse boundary for later M2–M4 work:

| Existing capability | Source | M1 reuse decision |
| --- | --- | --- |
| Immutable artifact quality evaluation, revision, P0/P1/P2, safe evidence hash | `app/services/real_idea_metrics.py`, `app/migrations/real_idea_evaluation_v1.py` | Reuse the concepts and safe-metadata discipline; do not create a second artifact-quality ledger. |
| Requirement gold set, mappings, claims, decisions, inheritance, quality metrics | `app/services/real_idea_metrics.py` | Preserve for later quality evaluation; M1 action cards are deterministic and do not write model-generated gold data. |
| Stage B evaluation receipts and provider telemetry | `app/services/stage_b_evaluation.py`, `app/services/provider_dispatch_ledger.py`, `app/db.py` | Reuse only for read-only accounting/audit; M1 must remain Provider/Search-free. |
| Artifact binding and version integrity | `artifact_dependencies`, document/snapshot services | M1 records no downstream artifact and must not loosen existing binding rules. |
| Existing negative/integrity matrix | `tests/test_real_idea_quality_negative.py`, related Real Idea tests | Run only relevant regression after M1; do not mix M1 evidence with Real Idea Batch evidence. |

## M1 implementation boundary

M1 adds a deterministic, local Purpose → First Action Card slice. The domain
boundary is `app/services/project_intent.py:ProjectIntentService` plus its
versioned template registry and validator. Persistence is owned by
`app/migrations/if_guide_m1.py`; the service binds the first writer to the
project actor, enforces expected revisions with HTTP 409 conflicts, and is the
only mutation path used by these routes:

- `GET /api/projects/{project_id}/intent`
- `PUT /api/projects/{project_id}/intent`
- `POST /api/projects/{project_id}/actions/first`
- `PATCH /api/projects/{project_id}/actions/{task_id}`
- `POST /api/projects/{project_id}/actions/{task_id}/confirm`

It does not change project origin, generate an artifact, call
QuickStart/Provider/Search, or claim that an action was executed or validated.

Required action fields are `goal`, `why_now`, `inputs`, `steps`,
`expected_artifact`, `checks`, `branches`, `stop_condition`, and
`prohibited_actions`. Structural coverage and required-field completeness are
deterministic P0 signals; semantic quality is a later review concern.

## Frontend and compatibility

- Main UI: `app/static/index.html`, `app/static/app.js`, and
  `app/static/styles.css`.
- Project loading fetches the M1 intent/action state through
  `loadProjectIntent`; the explicit-submit Purpose/First Action panel is
  rendered by `renderProjectIntent` without replacing existing navigation.
- Existing project/document routes remain compatible. Opening a project must
  remain read-only with respect to M1 until the user submits the explicit
  Purpose/Action form.

## M0 evidence and M1 verification

- M0 evidence: this map is grounded in the files and symbols above; no public
  API or persistent Stage B data was changed during mapping.
- M1 targeted verification completed with 11 passing tests covering all four
  purposes, template/action structure, deterministic purpose guards,
  save/reopen persistence, ownership, stale revision conflicts, idempotent
  first-card creation, source identity preservation, no Provider/Search calls,
  and public project-route compatibility. Additional related QuickStart,
  account-isolation, and project/account regression completed with 37 passing
  tests. Real Chromium browser E2E in isolated temporary storage completed
  purpose/raw-idea/first-action save, reload/reopen, confirmation, API
  readback, and external-connection tripwire checks with zero
  Provider/Search/generation activity. `node --check app/static/app.js`,
  `compileall app`, and `git diff --check` also pass.
- M2–M4 are intentionally out of scope for this execution. No Real Idea Batch,
  budget extension, reservation, user sample, or quality evaluation row is
  created by M0/M1.
