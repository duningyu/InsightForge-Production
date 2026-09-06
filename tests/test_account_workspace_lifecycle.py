"""Deterministic lifecycle controls; no Provider or production data."""
import asyncio
from contextlib import asynccontextmanager

from app import accounts
from test_open_accounts import portal, claim


def test_workspace_pool_idle_busy_leases_and_concurrent_initialization():
    assert hasattr(accounts, "WorkspacePool"), "Missing idle account workspace lifecycle"

    async def scenario():
        now = [0.0]
        started, stopped = [], []
        busy = set()

        @asynccontextmanager
        async def factory(account):
            started.append(account["id"])
            yield account["id"]
            stopped.append(account["id"])

        pool = accounts.WorkspacePool(factory, lambda child: child in busy,
                                      clock=lambda: now[0], idle_seconds=10)
        ready, release = asyncio.Event(), asyncio.Event()

        async def hold():
            async with pool.lease({"id": "A"}) as child:
                assert child == "A"
                ready.set()
                await release.wait()

        holder = asyncio.create_task(hold())
        await ready.wait()
        async with pool.lease({"id": "A"}):
            assert started == ["A"]
        now[0] = 20
        await pool.sweep()
        assert stopped == []  # in-flight request / streaming body
        release.set()
        await holder
        now[0] = 31
        busy.add("A")
        await pool.sweep()
        assert stopped == []  # queued/running work outlives the session
        busy.clear()
        await pool.sweep()
        assert stopped == ["A"]
        async with pool.lease({"id": "A"}):
            assert started == ["A", "A"]
        await pool.close()
        assert stopped == ["A", "A"]

    asyncio.run(scenario())


def test_actual_account_app_reuses_worker_and_recovers_persistent_project(portal):
    app, client = portal
    claim(app, client, 1)
    project = client.post("/api/projects", json={"title": "Synthetic persisted", "summary": "local"}).json()
    pool = app.state.workspace_pool
    account_id = client.get("/api/auth/me").json()["id"]
    entry = pool.entries[account_id]
    child = entry["child"]
    worker = child.state.async_generation_worker
    for _ in range(3):
        assert client.get(f"/api/projects/{project['id']}").status_code == 200
        assert pool.entries[account_id]["child"].state.async_generation_worker is worker
    assert client.post("/api/auth/logout").status_code == 200
    pool.clock = lambda: entry["last_used"] + 1801
    client.portal.call(pool.sweep)
    assert account_id not in pool.entries
    assert not worker._thread.is_alive()
    assert client.post("/api/auth/login", json={
        "username": "synthetic1", "password": "SYNTHETIC-only-passphrase!"
    }).status_code == 200
    reopened = client.get(f"/api/projects/{project['id']}")
    assert reopened.status_code == 200
    assert reopened.json()["title"] == "Synthetic persisted"
    assert pool.entries[account_id]["child"] is not child
    assert pool.entries[account_id]["child"].state.async_generation_repository.db.path == child.state.async_generation_repository.db.path


def test_workspace_pool_concurrent_first_access_has_one_owner():
    assert hasattr(accounts, "WorkspacePool"), "Missing idle account workspace lifecycle"

    async def scenario():
        starts = []
        entered, proceed = asyncio.Event(), asyncio.Event()

        @asynccontextmanager
        async def factory(account):
            starts.append(account["id"])
            entered.set()
            await proceed.wait()
            yield object()

        pool = accounts.WorkspacePool(factory, lambda child: False)
        async def visit():
            async with pool.lease({"id": "A"}) as child:
                return child
        first = asyncio.create_task(visit())
        await entered.wait()
        second = asyncio.create_task(visit())
        proceed.set()
        a, b = await asyncio.gather(first, second)
        assert a is b
        assert starts == ["A"]
        await pool.close()

    asyncio.run(scenario())
