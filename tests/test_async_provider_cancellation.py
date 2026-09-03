import asyncio

import httpx

from app.services.provider_adapters import AsyncModelAdapter, ProviderCallError


class BlockingTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.completed = False

    async def handle_async_request(self, request):
        self.started.set()
        gate = asyncio.Event()
        try:
            await gate.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        self.completed = True
        return httpx.Response(200, json={"choices": []}, request=request)


def test_async_provider_transport_receives_overall_deadline_cancellation():
    async def scenario():
        transport = BlockingTransport()
        adapter = AsyncModelAdapter(
                provider="glm", model="glm-5.2", api_key="test-only",
                client=httpx.AsyncClient(transport=transport),
            overall_timeout=0.05,
        )
        task = asyncio.create_task(adapter._request_async(system="", user="probe", structured=False))
        await transport.started.wait()
        try:
            await task
        except ProviderCallError as exc:
            assert exc.code == "timeout"
            assert isinstance(exc.__cause__, asyncio.TimeoutError)
        finally:
            await adapter.aclose()
        assert transport.cancelled.is_set()
        assert transport.completed is False

    asyncio.run(scenario())
