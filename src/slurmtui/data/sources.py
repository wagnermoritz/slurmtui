"""Wire the backend into a :class:`DataService` according to the configuration."""

from __future__ import annotations

from datetime import datetime, timedelta

from slurmtui.config.schema import Config
from slurmtui.data.service import DataService, Source
from slurmtui.model.derive import Deriver
from slurmtui.model.records import (
    Job,
    JobRecord,
    Node,
    Partition,
    RecentCounts,
    Reservation,
    SchedulerStats,
    ShareEntry,
    UsageRecord,
)
from slurmtui.slurm.backend import SlurmBackend
from slurmtui.units import parse_window


def window_delta(text: str, default: str) -> timedelta:
    delta = parse_window(text) if text.strip() else None
    if delta is None:
        delta = parse_window(default)
    assert delta is not None
    return delta


def build_service(config: Config, backend: SlurmBackend) -> DataService:
    service = DataService()
    deriver = Deriver(config)
    sources = config.sources

    async def partitions() -> list[Partition]:
        return await backend.partitions()

    async def nodes() -> list[Node]:
        raw = await backend.nodes()
        parts = await service.get("partitions")
        return deriver.derive_nodes(raw, parts)

    async def jobs() -> list[Job]:
        return deriver.derive_jobs(await backend.jobs())

    async def reservations() -> list[Reservation]:
        return await backend.reservations()

    async def shares() -> list[ShareEntry]:
        return await backend.shares()

    async def scheduler() -> SchedulerStats:
        return await backend.scheduler_stats()

    async def history(window: str) -> list[JobRecord]:
        since = datetime.now() - window_delta(window, sources.history.default_window)
        return await backend.job_history(backend.whoami(), since)

    async def recent_jobs() -> dict[str, RecentCounts]:
        since = datetime.now() - window_delta(sources.recent_jobs.window, "7d")
        return await backend.recent_job_counts(since)

    async def account_usage(window: str) -> list[UsageRecord]:
        since = datetime.now() - window_delta(window, sources.account_usage.default_window)
        return await backend.account_usage(since)

    service.register(Source("partitions", partitions, ttl=sources.partitions.ttl))
    service.register(Source("nodes", nodes, ttl=sources.nodes.ttl))
    service.register(Source("jobs", jobs, ttl=sources.jobs.ttl))
    service.register(
        Source("reservations", reservations, ttl=sources.reservations.ttl, enabled=sources.reservations.enabled)
    )
    service.register(Source("shares", shares, ttl=sources.shares.ttl))
    service.register(Source("scheduler", scheduler, ttl=sources.scheduler.ttl, enabled=sources.scheduler.enabled))
    service.register(Source("history", history, ttl=sources.history.ttl, enabled=sources.history.enabled))
    service.register(
        Source(
            "recent_jobs",
            recent_jobs,
            ttl=sources.recent_jobs.ttl,
            enabled=sources.recent_jobs.enabled,
            expensive=True,
        )
    )
    service.register(
        Source(
            "account_usage",
            account_usage,
            ttl=sources.account_usage.ttl,
            enabled=sources.account_usage.enabled,
            expensive=True,
        )
    )
    return service
