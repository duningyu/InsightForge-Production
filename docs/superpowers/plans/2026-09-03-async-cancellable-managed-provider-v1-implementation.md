# Async Cancellable Managed Provider V1 Implementation Plan

## Task 1 — Reconcile existing diff

Files: `app/services/provider_adapters.py`, `app/services/ai_runtime.py`, timeout tests, async tests.

RED: add async contract tests and run them; expected failure is missing async adapter/worker path.

GREEN: retain safe timeout metadata and cause-chain behavior while adapting it to async code. Re-run targeted tests.

## Task 2 — Async adapter

Files: `app/services/provider_adapters.py`, `tests/test_async_provider_cancellation.py`.

RED: blocked `AsyncBaseTransport` must observe `CancelledError` under a short overall deadline.

GREEN: implement `AsyncModelAdapter` with `AsyncClient`, shared payload/schema semantics, safe metadata, concrete timeout mapping, and `aclose`.

## Task 3 — Async managed runtime

Files: `app/services/ai_runtime.py`, runtime tests.

RED: async managed solutions call must not invoke a sync adapter.

GREEN: add explicit async methods, preserve quota callbacks and cause chains, and pass durable identity.

## Task 4 — Overall cancellation

Files: adapter/runtime tests.

RED: short test deadline must cancel the custom transport and leave no local provider task.

GREEN: use `asyncio.timeout(75)` in production and a configurable short deadline only in tests.

## Task 5 — Worker integration

Files: `app/services/async_generation.py`, `app/main.py`, worker tests.

RED: async executor is awaited and shutdown cancels the active task.

GREEN: use `asyncio.run` per claimed run, preserve durable finish/quota semantics, and keep old test executor compatibility without using it for production Provider I/O.

## Task 6 — Exceptions and cause chain

Files: adapter/runtime tests.

RED: concrete HTTPX subtype and outer deadline cause assertions.

GREEN: retain body-free subtype causes and map overall deadline separately.

## Task 7 — Quota and idempotency regression

Files: async repository/worker tests.

RED: timeout, replay, success, and failure cases expose duplicate calls or incorrect reservation state.

GREEN: durable state remains authoritative and same-intent replay never calls Provider twice.

## Task 8 — Restart and shutdown

Files: worker/recovery tests.

RED: active cancellation is not observable or leaves a run unsafe.

GREEN: terminal shutdown classification is durable and restart-safe.

## Task 9 — Full integration

Commands: targeted pytest, full pytest, compileall, JavaScript check, diff check, secret scan.

GREEN requires all current and new tests to pass with zero real Provider requests.

## Task 10 — Build and deployment

Build successor image, record digest, fresh-backup beta001, deploy beta001 only, verify async runtime and unchanged beta002/003. Stop before real GLM acceptance and request the separate authorization gate.
