# InsightForge Railway Stage A

This document describes a Railway-like, single-service deployment. It is a
readiness contract, not a deployment receipt. This task does not create a
Railway project, upload secrets, create a domain, or call a Provider/Search
service.

## Architecture

- One Railway Web Service built from `deploy/beta/Dockerfile` (the Dockerfile
  used by the Stage A service).
- One Railway Volume mounted at `/app/data`.
- One replica only. SQLite and in-process tasks are not a multi-replica contract.
- The container startup command reads Railway's injected `PORT` and binds
  `0.0.0.0:${PORT}`. When `PORT` is absent for local Docker, the default is
  `8000`. Do not set `PORT=8000` manually in Railway; the platform must own
  that value.
- `GET /api/health` is the unauthenticated, lightweight healthcheck.
- Stage A does not depend on Tailscale Funnel, Caddy Basic Auth, or a beta
  participant identity.

## Volume and persistence

Set `INSIGHTFORGE_DATA_ROOT=/app/data`. The application derives:

| Data | Path | Policy |
| --- | --- | --- |
| SQLite application database | `/app/data/insightforge.sqlite3` | MUST_PERSIST |
| Runtime uploads, exports, handoff files and task scratch | `/app/data/runtime/` | MUST_PERSIST for user artifacts |
| Account registry when accounts are enabled | `/app/data/accounts/accounts.sqlite3` | MUST_PERSIST in the future account mode |
| Python/OS temporary files | container temp directories | TEMP_ONLY |

Do not run more than one replica until the storage and task model are migrated
away from the current SQLite/in-process contract.

## Variables

Start from [`env.example`](env.example). `PORT` is supplied by Railway; the
application must not be assigned a fixed public port. `INSIGHTFORGE_DATA_ROOT`
is the persistent root. Search remains disabled when no Search configuration is
provided, and the UI must continue to say that online lookup is not enabled.

Provider credentials, if later approved, are Railway secret Variables only.
They must never be placed in Git, the Docker image, the example file, or logs.

Stage A leaves `INSIGHTFORGE_ACCOUNTS_ENABLED=false`. Formal multi-user account
productionization is a separate gate documented in
`ACCOUNT_PRODUCTIONIZATION_GAPS.md`.

## Stage A Safe Fixture

For the isolated Stage A acceptance run only, the service may enable
`INSIGHTFORGE_SAFE_FIXTURE_MODE=true` and optionally set
`INSIGHTFORGE_SAFE_FIXTURE_SCENARIO=solution_generation_fail_once`. The
application additionally requires accounts to remain disabled and the Stage A
participant identity (`railway_stage_a`); otherwise it fails closed. The fixture
uses the normal generation and persistence pipeline, but it is deterministic and
is not a real AI or Search result. Generated references, evidence cards, and
solutions are labelled `Stage A 演示结果 · 非真实 AI 生成`; Provider dispatch and
real Search calls remain zero. Keep the mode unset or `false` in beta, Stage B,
and production. This is not an authentication bypass or a public fixture API.

## Healthcheck and first boot

Configure the Railway healthcheck path as `/api/health`. It must return 2xx
after application startup and required data directories/database readiness.
It does not perform Provider, Search, login, or user-content reads.

An empty `/app/data` volume must be usable on first boot; the application creates
its database parent and runtime subdirectories. Do not SSH into a service to
pre-create directories.

## Backup, rollback, and domain

Use Railway Volume backups with a daily and weekly schedule. Take a manual
backup before a release. A rollback restores the prior image and keeps the
volume unchanged; verify `/api/health` and the representative read-only pages
afterward.

For Stage A, use the generated `*.up.railway.app` domain first. Add a custom
domain only after the temporary-domain smoke passes; follow Railway's current
CNAME/TXT and TLS instructions at that time.

## Known limitations

- This is not formal multi-user production readiness.
- `BETA_SESSION_COOKIE_SECURE` and the account lifecycle remain future account
  mode concerns; do not enable beta account mode as a shortcut.
- In-process work can be interrupted by a container restart. The current task
  contract does not add Redis, Celery, or another external worker.
- Real Provider/Search acceptance is a separate, explicitly authorized task.
