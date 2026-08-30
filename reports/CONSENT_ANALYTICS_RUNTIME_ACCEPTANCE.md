# Consent + Analytics Runtime Acceptance

- execution_id: `insightforge_closed_beta_20260830_20260830_010000`
- scope: existing Phase A staging only
- formal directory modified: false
- live provider requests: 0

## Browser acceptance

- first Beta visit: consent dialog visible
- accept: dialog dismissed
- refresh: dialog remained dismissed
- application restart: persisted consent remained valid
- non-Beta instance: consent dialog never shown
- blocking console errors: 0
- screenshots: `reports/browser/consent/beta_first_visit.png`, `beta_consented_after_restart.png`, `non_beta_no_consent.png`

## Automated verification

- targeted consent/analytics/isolation: 19 passed
- full regression: 370 passed
- compileall: PASS
- `app/static/app.js`: PASS
- `app/static/model-settings.js`: PASS
- beta001 SQLite integrity: ok; foreign-key issues: 0
- beta002 SQLite integrity: ok; foreign-key issues: 0

## Privacy audit

The retained automated test exercises real quick-start and Source persistence routes, a mocked model document-generation route, and the production event writer. Event properties and captured logs were scanned for:

- `UNIQUE_SECRET_IDEA_123`
- `UNIQUE_PRD_TEXT_456`
- `UNIQUE_EVIDENCE_TEXT_789`
- `UNIQUE_PROMPT_SECRET_ABC`
- `UNIQUE_COMPLETION_SECRET_XYZ`
- the test API-key marker
- Authorization/Bearer material

Result: `analytics_sensitive_content_violation_count = 0`.

Analytics failures are caught after successful business persistence and log only event name, exception class, and anonymous participant id. They do not log rejected values or raw payloads.
