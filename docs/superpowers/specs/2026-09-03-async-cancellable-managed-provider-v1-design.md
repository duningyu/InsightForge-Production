# Async Cancellable Managed Provider V1 Design

## A. Current problem

The durable generation worker runs in a daemon thread but calls the managed provider through synchronous `httpx.Client`. A caller-side deadline cannot prove that the underlying provider transport stopped, which weakens cost, quota, and idempotency guarantees.

## B. Sync-to-async boundary

Existing synchronous `ModelAdapter` consumers remain unchanged. Managed asynchronous generation uses a dedicated `AsyncModelAdapter` backed by `httpx.AsyncClient`; it never calls synchronous provider I/O and never uses `asyncio.to_thread`.

## C. Worker lifecycle

The existing durable worker claims one run, calls `asyncio.run(execute_generation_run_async(run))`, waits for the coroutine to finish, and then claims the next run. No task is left pending between runs.

## D. Async adapter contract

The async adapter builds the same provider payload and schema contract as the sync adapter, performs HTTP through `AsyncClient`, records safe attempt metadata, parses the existing Pydantic schema, and closes only clients it owns.

## E. Managed runtime async contract

Managed runtime exposes explicit async operation methods. It creates the async adapter with provider, model, timeout, observer, generation intent, and generation run identity. Quota reservation and release remain around the same operation boundary.

## F. Overall deadline semantics

Each provider attempt is enclosed by `asyncio.timeout(75.0)`. Expiry cancels the local coroutine and produces `ProviderOverallDeadline`; it is not mislabeled as an HTTPX read timeout.

## G. Phase timeout semantics

The `httpx.Timeout` values are connect 10 seconds, pool 5 seconds, write 15 seconds, and read 60 seconds. Concrete `ConnectTimeout`, `PoolTimeout`, `WriteTimeout`, and `ReadTimeout` types remain distinguishable in safe diagnostics and cause chains.

## H. Cancellation propagation

Cancellation is allowed to reach the `AsyncClient` transport and is tested with a blocked custom async transport. The system claims local task/transport cancellation only; it does not claim that remote Bailian computation is necessarily stopped.

## I. Provider attempt accounting

Every started attempt retains durable safe metadata: attempt, generation intent/run, model, safe endpoint host, payload sizes, schema size, timeout configuration, timestamps, elapsed time, timeout class, terminal stage, response-header observation, and HTTP status. Prompt, response, API key, and Authorization values are excluded.

## J. Quota lifecycle

Successful persisted use charges once. Provider, parse, validation, persistence, timeout, and cancellation failures release the reservation. A provider call that started remains represented in the attempt ledger.

## K. Durable idempotency

The existing SQLite intent/run uniqueness remains authoritative. Replays of PENDING, RUNNING, SUCCEEDED, or FAILED runs do not start another provider call. Explicit retry creates a new intent.

## L. Restart/crash semantics

PENDING runs remain claimable. A run whose provider call started is recovered as an interrupted terminal failure rather than automatically replayed. Its reservation is released; explicit user retry is required.

## M. Error and cause-chain mapping

The async adapter preserves concrete transport exceptions as body-free causes of `ProviderCallError`; managed runtime raises `StructuredRuntimeRecoveryError` from that error. User messages remain stable and do not expose transport internals.

## N. Security and safe telemetry

Only allowlisted metadata is persisted. Secret-bearing runtime inspection is not used. Secret scans cover code, logs, reports, receipts, and test artifacts.

## O. Compatibility with existing sync consumers

Sync routes, deterministic fixtures, profile runtimes, and existing tests continue to use the synchronous adapter. Only the managed async generation worker changes execution path.

## P. Deployment strategy

After offline tests and fresh regression pass, build a successor image, take a fresh beta001 SQLite-safe backup, deploy beta001 only, and verify runtime identity. beta002 and beta003 remain unchanged.

## Q. Acceptance gates

Offline gates require cancellation transport proof, phase timeout coverage, cause-chain proof, success/error/quota/idempotency/restart tests, and zero secret findings. Deployment gates require the expected image, healthy beta001, async runtime evidence, unchanged quota, and no real Provider requests. Real GLM acceptance is a separate user-authorized next gate.
