# Account productionization gaps

Railway Stage A keeps `INSIGHTFORGE_ACCOUNTS_ENABLED=false`. Enabling the
account mode is a separate productionization project, not a readiness shortcut.

Before enabling it, the system needs verified contracts for:

- account and workspace provisioning without admin/read-all privilege;
- invite issuance, expiry, rotation, and safe revocation;
- account disable/re-enable and invalidation of all active sessions;
- application auth cookie `Secure=true`, `HttpOnly=true`, and the approved
  SameSite policy under HTTPS;
- analytics and quota exclusion/labeling for synthetic verification identities;
- verification-account lifecycle and credential rotation;
- workspace/project authorization tests across accounts;
- restart-safe session and background-task behavior;
- multi-user acceptance tests for documents, drafts, handoffs, Evidence Coach,
  Provider boundaries, and Search-disabled behavior.

The current single-participant beta contract must not be presented as a
multi-user production contract.
