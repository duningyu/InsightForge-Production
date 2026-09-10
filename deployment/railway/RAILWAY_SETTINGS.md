# Railway Dashboard Settings Runbook

Use this only for a future isolated Stage A project. Do not run `railway up`
or `railway config apply` as part of the readiness audit.

1. Create a new Railway project.
2. Deploy from the repository and select `deploy/beta/Dockerfile`.
3. Add the variables from `deployment/railway/env.example`; let Railway inject
   `PORT` and set `INSIGHTFORGE_DATA_ROOT=/app/data`. Do not add a manual
   `PORT=8000`; local Docker uses 8000 only when `PORT` is absent.
4. Add one Volume and mount it at `/app/data`.
5. Set the healthcheck path to `/api/health`.
6. Keep replicas at `1`.
7. Generate a temporary `*.up.railway.app` domain.
8. Run the read-only smoke: health, root/static assets, empty-volume boot, and
   persistence restart. Confirm Provider/Search counters remain unchanged.
9. Configure daily and weekly Volume backups; take a manual release backup.
10. Consider a custom domain only after Stage A smoke and rollback evidence are
    accepted.

Do not put passwords, API keys, invite data, cookies, database files, or beta
Caddy/Funnel settings in this runbook.
