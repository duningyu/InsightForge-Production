# Participant Mutable Path Audit (Phase A checkpoint)

| Path / code location | Current behavior | Mutable | Participant isolated | Required change |
|---|---|---:|---:|---|
| `app/config.py:Settings.database_path` | Reads `INSIGHTFORGE_DATABASE_PATH`, defaults to `data/insightforge.sqlite3` | yes | configuration only | Use one per-participant mounted volume in Beta |
| `app/db.py:Database` | All service connections use the injected `Database.path`; `sqlite3.connect` is centralized here | yes | yes when path differs | Add automated A/B instance test |
| `app/ingestion.py:extract_text` | Upload bytes parsed in memory; no filesystem write | no | n/a | No change required |
| `app/services/handoff.py:_build_v3_zip` | Handoff is built in memory and returned as HTTP ZIP | no | n/a | No shared export directory found |
| `app/services/document_workspace.py` | Document content is stored in SQLite | yes | follows DB | Verify with per-participant DB |
| `runtime/`, `uploads/`, `tmp/`, `cache/` | No application writes found in code search | no | n/a | Keep container runtime volume reserved for future artifacts |
| `scripts/deploy_windows.ps1` | Deployment backup/migration utility writes under deployment workspace | yes | host deployment only | Exclude from participant runtime |
| `scripts/backup_beta_instances.py` / `restore_beta_instance.py` | Explicit operator backup/restore paths | yes | participant argument required | Add integration test before release |

## Findings

1. SQLite initialization is centralized in `app/db.py` and receives the path from `create_app(database_path=...)` / `INSIGHTFORGE_DATABASE_PATH`.
2. Source uploads and handoff exports are currently memory-only; no shared upload/export path was found.
3. The application does not yet enforce participant identity or prevent a caller from reaching another instance. Isolation therefore depends on separate containers, volumes, and server-side environment configuration and remains an unreleased Gate.
4. No second hard-coded business SQLite connection was found; the backup/restore scripts intentionally open operator-selected files.
