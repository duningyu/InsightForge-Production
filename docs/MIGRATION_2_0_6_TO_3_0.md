# Migrating InsightForge 2.0.6 Data to 3.0.0

## Objective

3.0 uses an **additive** SQLite migration. Existing 2.x records are retained; the migration creates a conservative 3.0 Snapshot view only where traceable legacy state exists.

## What is retained

Legacy tables and records remain, including:

- projects;
- Canvas/current Canvas versions;
- Guided sessions/messages;
- sources/source chunks;
- retrieval runs/hits;
- documents/document versions;
- document Claims/evidence links;
- generation/validation/audit/handoff records.

Existing source IDs, chunk IDs, document IDs/version IDs, document Claim text, and historical document content are not rewritten as part of migration.

## What is added

3.0 adds the new IdeaBrief, solution, project Claim, Snapshot, Change Proposal, dependency, and artifact-health tables plus additive columns such as `projects.current_snapshot_id` and Decision version metadata.

## Legacy Snapshot creation

When a project has traceable legacy Canvas data and no prior migration Snapshot, startup migration can create:

```text
snapshot_origin = legacy_migration
```

The migration uses traceable project-owner Canvas fields to create **unverified** project Claims. It may reuse an existing confirmed legacy project Decision for historical traceability, or create a migration bookkeeping Decision if no such record exists.

The migration does **not** infer a new product solution from generated document prose.

## No invented evidence or market validation

Migration creates:

```text
project_claim_evidence_links = 0
```

for the migrated project unless such 3.0 links already existed through 3.0 behavior. Historical `document_claims` and old citations stay document-level historical records; they are never promoted into project evidence merely because they appeared in an old PRD.

Migrated project Claims use `verification_status=unverified` unless 3.0 evidence behavior later validates them.

## Guided sessions

Existing legacy Guided sessions remain readable/writable for backward compatibility.

3.0 does **not** automatically create a new `guided_sessions` row for a new project. Legacy Guided REST routes are marked deprecated and return 404 when no pre-existing legacy session exists.

## Canvas compatibility

Canvas remains because the existing document generator/validator consumes it. For native 3.0 projects, the formal direction is:

```text
confirmed Project Snapshot → deterministic Canvas projection
```

Direct independent Canvas mutation is not permitted for Snapshot-managed projects.

A migrated project preserves its existing Canvas. Migration itself does not pretend that Canvas fields are externally verified market evidence.

## Historical immutability

A later source or evidence change may alter `artifact_health`, but it does not silently rewrite old Snapshot or document content. New formal project changes create new Snapshot versions.

## Idempotency

Running migration repeatedly returns/reuses the same existing `legacy_migration` Snapshot instead of duplicating migration history. Automated tests exercise migration against an actual 2.0.6 schema fixture.

## Recommended upgrade procedure

1. Back up `data/insightforge.sqlite3`.
2. Install/run the 3.0 package against the copy first.
3. Start the application once so `db.init_schema()` applies additive migration and `LegacyMigrationService` creates eligible legacy Snapshots.
4. Run the application tests in a clean checkout.
5. Inspect migrated projects: verify `snapshot_origin=legacy_migration`, project Claims are `unverified`, and no project evidence links were invented.
6. Keep the backup until project/history review is complete.

SQLite migration support is for the local/single-instance product. This is not a zero-downtime clustered database migration guarantee.
