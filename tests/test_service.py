import asyncio

import pytest

from slurmtui.data.service import DataService, Source, SourceDisabledError, SourceError
from slurmtui.slurm.backend import SlurmCommandError


async def test_ttl_and_dedupe():
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    service = DataService()
    service.register(Source("x", fetch, ttl=10))
    results = await asyncio.gather(service.get("x"), service.get("x"), service.get("x"))
    assert results == [1, 1, 1] and calls == 1
    assert await service.get("x") == 1
    assert await service.get("x", force=True) == 2
    assert service.status("x").updated_at is not None and service.is_fresh("x")


async def test_params_cached_separately():
    async def fetch(window):
        return f"data-{window}"

    service = DataService()
    service.register(Source("h", fetch, ttl=10))
    assert await service.get("h", "7d") == "data-7d"
    assert await service.get("h", "1d") == "data-1d"
    assert service.peek("h", "7d") == "data-7d"
    assert service.status("h", "7d").updated_at is not None


async def test_error_keeps_stale_value():
    fail = False

    async def fetch():
        if fail:
            raise SlurmCommandError(["squeue"], 1, "slurm_load_jobs error: Unable to contact slurm controller")
        return "ok"

    service = DataService()
    service.register(Source("jobs", fetch, ttl=0))
    assert await service.get("jobs") == "ok"
    fail = True
    assert await service.get("jobs") == "ok"
    status = service.status("jobs")
    assert status.last_error and "Unable to contact" in status.last_error and status.is_stale
    fail = False
    await service.get("jobs")
    assert service.status("jobs").last_error is None


async def test_error_without_value_raises():
    async def fetch():
        raise SlurmCommandError(["sinfo"], 1, "boom")

    service = DataService()
    service.register(Source("nodes", fetch, ttl=1))
    with pytest.raises(SourceError):
        await service.get("nodes")


async def test_disabled_source():
    async def fetch():
        return 1

    service = DataService()
    service.register(Source("exp", fetch, ttl=1, enabled=False))
    with pytest.raises(SourceDisabledError):
        await service.get("exp")


async def test_build_service_shares_fetches(service, backend):
    nodes = await service.get("nodes")
    jobs = await service.get("jobs")
    assert nodes and jobs
    assert service.is_fresh("partitions")  # fetched as a dependency of nodes
    assert all(node.node_group in {"z3", "GCP"} for node in nodes)


async def test_cancelled_caller_keeps_shared_fetch_alive():
    """A refresh worker that gets replaced must not cancel the fetch other tabs wait for."""
    started = asyncio.Event()

    async def fetch():
        started.set()
        await asyncio.sleep(0.1)
        return "value"

    service = DataService()
    service.register(Source("x", fetch, ttl=10))
    first = asyncio.ensure_future(service.get("x"))
    await started.wait()
    second = asyncio.ensure_future(service.get("x"))
    await asyncio.sleep(0)
    first.cancel()
    assert await second == "value"
    assert service.peek("x") == "value" and not service.status("x").in_flight
