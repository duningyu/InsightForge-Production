# Hybrid Async Generation v1 Design

## Goal

Move managed solution generation from a request-blocking operation to a durable,
pollable job without changing the existing provider, quota, model-selection, or
solution-domain contracts. This is an offline/gray implementation gate; no live
provider request is part of this change.

## Contract

`POST /api/projects/{project_id}/solutions/generate` with
`X-Generation-Mode: async` returns `202 Accepted` and a durable
`generation_run_id`, `generation_intent_id`, `status`, and `poll_after_ms`.
The client polls `GET /api/projects/{project_id}/solutions/generate/{generation_run_id}`.

One intent is the authority for one logical operation:

* one durable run;
* one quota reservation;
* at most one provider call;
* replay of `PENDING`, `RUNNING`, `SUCCEEDED`, or `FAILED` returns the existing run;
* only an explicit new-generation action creates a new intent.

The existing synchronous endpoint remains available for compatibility and is not
used by the async browser path.

## Persistence

Add `async_solution_generation_runs`, keyed by `generation_run_id`, with a unique
`generation_intent_id`, participant/project/model provenance, lifecycle status,
safe result metadata, quota reservation state, provider-call count, and timestamps.
All transitions are conditional SQL updates so a second worker cannot claim the
same pending run. No prompt, completion, API key, Authorization header, or raw
provider response is persisted.

## Worker

An application-lifecycle worker claims pending jobs from SQLite and executes the
existing solution-domain generation service outside the HTTP request. The worker
has a bounded poll loop, clean shutdown, and records terminal success/failure.
The provider adapter uses the existing concrete timeout observability and the
approved hybrid timeout contract: connect 10s, pool 5s, write 15s, read 60s,
overall attempt deadline 75s. Automatic retry and fallback are disabled for this
path.

## UI

Async submission immediately shows “正在生成方案…”, disables duplicate submit,
and polls at the server-provided interval. Terminal success renders the existing
solutions view. Terminal failure preserves input and shows the existing friendly
recovery message plus an explicit “重新生成” action. A failed intent is never
automatically retried.

## Safety and compatibility

Quota is reserved once and released on provider/application failure; successful
delivery is charged once. Existing participant isolation, Basic Auth, Caddy,
Cloudflare, databases, and managed credentials are untouched. Existing sync tests
must remain green. All new tests use mocks or local fixtures and assert zero live
provider calls.

## Gray gate

Before any live acceptance, verify schema, worker lifecycle, idempotent replay,
timeout metadata, quota behavior, API status polling, browser state transitions,
secret scans, and full regression. The only next action after the offline gate is
explicit authorization for one real GLM-5.2 async Solutions acceptance.
