# Async Provider Pre-existing Diff Audit

Execution: `insightforge_managed_multi_model_v1`

The uncommitted changes were audited before implementation. No file was reset.

| File | Decision | Rationale |
|---|---|---|
| `app/services/provider_adapters.py` | ADAPT | Keep the 10/5/15/60 phase timeout contract, safe attempt metadata, concrete timeout classification, and body-free cause. Add a separate async adapter; preserve the synchronous adapter for existing consumers. |
| `app/services/ai_runtime.py` | ADAPT | Keep the managed runtime, quota callbacks, and exception chaining. Add an explicit async managed call surface and pass durable run/intent identity to the async adapter. |
| `app/services/async_generation.py` | REPLACE | The worker currently invokes its executor synchronously. Replace the production executor bridge with an awaited coroutine executed by `asyncio.run` per claimed run, with explicit task cancellation on shutdown. |
| `tests/test_provider_timeout_observability.py` | KEEP/ADAPT | Preserve existing safe metadata assertions and extend them to the async adapter. |
| `tests/test_hybrid_provider_timeout_contract.py` | KEEP/ADAPT | Preserve effective phase timeout and cause-chain intent; add async runtime coverage without weakening current sync compatibility. |
| `tests/test_async_generation.py` | KEEP/ADAPT | Preserve durable queue/idempotency tests and add cancellation/replay/shutdown assertions. |

Current production gap: the durable queue exists, but its managed execution boundary is still synchronous `httpx.Client` code. An overall deadline around that call would stop only the caller's wait and could leave the transport thread running. The implementation therefore must make the managed worker path natively async; `asyncio.to_thread` is excluded.

No Provider request is made by this audit.
