# Security policy

## Deployment boundary

InsightForge is local-first and does not provide multi-user authorization or tenant isolation.
Do not expose an unprotected instance to the internet. For a private single-user deployment,
set both `INSIGHTFORGE_ACCESS_USERNAME` and `INSIGHTFORGE_ACCESS_PASSWORD` to enable HTTP Basic
authentication. Keep `.env`, SQLite databases, uploaded sources, and API keys out of Git.

The `/api/health` endpoint intentionally remains unauthenticated for platform health checks and
returns no filesystem path or secret value.

## Reporting a vulnerability

Do not open a public issue containing credentials, private source material, or exploit details.
Use the repository owner's private security-reporting channel when one is configured.

