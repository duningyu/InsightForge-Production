# Server-bound provider acceptance authorization

Strict beta001 acceptance runs are authorized by a server-issued, single-use
record in `provider_acceptance_authorizations`. The record binds the project,
actor scope, beta instance, provider, model, forward-ledger epoch, operation,
expiry, and a sanitized evidence hash. It contains no credential material.

The normal generation endpoint accepts only the opaque authorization reference
(`X-Acceptance-Authorization-Id`). The server redeems it transactionally,
generates the `acceptance_execution_id`, and persists the reference and
dispatch context in `async_solution_generation_runs` before a worker can run.
Client-supplied execution IDs or ledger epochs never create dispatch
authority. Issuance is an internal/operator operation; no public issuance
route exists.

Redemption is single-use and scope-checked. The existing forward dispatch
ledger remains responsible for the at-most-one permit and provider lifecycle
events. Ordinary non-acceptance generation continues through its existing path
and retry policy.
