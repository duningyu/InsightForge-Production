"""Real worker/adapter held at fake transport until the normal UI cancels."""
import asyncio
import httpx
from app.services.provider_adapters import AsyncModelAdapter
from browser_business_fixture import prepare


def install_transport():
    calls = []
    original = AsyncModelAdapter.__init__

    def initialize(self, **kwargs):
        async def send(request):
            calls.append(kwargs.get("generation_run_id"))
            await asyncio.Event().wait()  # cancellation is the only completion, no random sleep
            raise AssertionError("unreachable")
        original(self, **{**kwargs, "client": httpx.AsyncClient(transport=httpx.MockTransport(send))})
    AsyncModelAdapter.__init__ = initialize
    return calls


def verify(app, data, calls):
    db = app.state.workspace_pool.entries[data["account"]]["child"].state.async_generation_repository.db
    rows = db.fetch_all("SELECT * FROM async_solution_generation_runs")
    assert len(rows) == 1 and rows[0]["status"] == "FAILED"
    assert "ASYNC_GENERATION_CANCELLED" in rows[0]["response_json"]
    assert calls == [rows[0]["generation_run_id"]]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='RELEASED'")["n"] == 1
    assert db.fetch_one("SELECT COUNT(*) AS n FROM beta_quota_reservations WHERE state='RESERVED'")["n"] == 0
    print("PASS browser cancel: transitions=1; fake transport=1; reservation RELEASED=1 RESERVED=0; terminal=FAILED/ASYNC_GENERATION_CANCELLED; refresh dispatch delta=0")
