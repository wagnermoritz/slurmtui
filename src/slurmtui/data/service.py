"""A TTL cache in front of the backend with in-flight deduplication."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from slurmtui.slurm.backend import SlurmError

log = logging.getLogger(__name__)
T = TypeVar("T")
Params = tuple[Any, ...]


class SourceDisabledError(RuntimeError):
    pass


class SourceError(RuntimeError):
    """A fetch failed and no cached value exists."""


@dataclass
class Entry[T]:
    value: T
    monotonic: float
    wall_time: datetime
    duration: float


@dataclass
class SourceStatus:
    name: str
    enabled: bool
    updated_at: datetime | None = None
    age: float | None = None
    duration: float | None = None
    last_error: str | None = None
    error_at: datetime | None = None
    in_flight: bool = False

    @property
    def is_stale(self) -> bool:
        return self.last_error is not None and self.updated_at is not None


@dataclass
class Source[T]:
    name: str
    fetch: Callable[..., Awaitable[T]]
    ttl: float
    enabled: bool = True
    expensive: bool = False
    max_entries: int = 2
    entries: dict[Params, Entry[T]] = field(default_factory=dict)
    in_flight: dict[Params, asyncio.Future[T]] = field(default_factory=dict)
    last_error: str | None = None
    error_at: datetime | None = None


class DataService:
    def __init__(self) -> None:
        self._sources: dict[str, Source[Any]] = {}
        self._listeners: list[Callable[[str], None]] = []

    def register(self, source: Source[Any]) -> None:
        self._sources[source.name] = source

    def source(self, name: str) -> Source[Any]:
        try:
            return self._sources[name]
        except KeyError as exc:
            raise KeyError(f"unknown data source {name!r}") from exc

    @property
    def names(self) -> list[str]:
        return list(self._sources)

    def on_update(self, callback: Callable[[str], None]) -> None:
        self._listeners.append(callback)

    def is_enabled(self, name: str) -> bool:
        return self.source(name).enabled

    # -- cache access ---------------------------------------------------------

    def peek(self, name: str, *params: Any) -> Any | None:
        entry = self.source(name).entries.get(params)
        return entry.value if entry else None

    def status(self, name: str, *params: Any) -> SourceStatus:
        source = self.source(name)
        entry = source.entries.get(params)
        status = SourceStatus(name=name, enabled=source.enabled, in_flight=params in source.in_flight)
        if entry is not None:
            status.updated_at = entry.wall_time
            status.age = time.monotonic() - entry.monotonic
            status.duration = entry.duration
        status.last_error = source.last_error
        status.error_at = source.error_at
        return status

    def is_fresh(self, name: str, *params: Any) -> bool:
        source = self.source(name)
        entry = source.entries.get(params)
        return entry is not None and time.monotonic() - entry.monotonic < source.ttl

    def invalidate(self, name: str) -> None:
        self.source(name).entries.clear()

    async def get(self, name: str, *params: Any, force: bool = False) -> Any:
        """Return the value, fetching when missing, stale or forced.

        Concurrent callers share one fetch, which runs in its own task behind
        ``asyncio.shield`` so that a cancelled caller (a replaced refresh worker)
        leaves it running for the others. After a failed fetch the previous value
        is returned and the error recorded in the status; without a previous value
        SourceError is raised.
        """
        source = self.source(name)
        if not source.enabled:
            raise SourceDisabledError(f"data source {name!r} is disabled in the configuration")
        if not force and self.is_fresh(name, *params):
            return source.entries[params].value
        pending = source.in_flight.get(params)
        if pending is None:
            pending = asyncio.ensure_future(self._fetch(source, name, params))
            pending.add_done_callback(_retrieve_exception)
            source.in_flight[params] = pending
        return await asyncio.shield(pending)

    async def _fetch(self, source: Source[Any], name: str, params: Params) -> Any:
        started = time.monotonic()
        try:
            try:
                value = await source.fetch(*params)
            except (SlurmError, SourceError, OSError, ValueError) as exc:
                source.last_error = str(exc)
                source.error_at = datetime.now()
                log.warning("source %s%s failed: %s", name, params or "", exc)
                previous = source.entries.get(params)
                if previous is None:
                    raise SourceError(str(exc)) from exc
                return previous.value
            duration = time.monotonic() - started
            source.entries[params] = Entry(
                value=value, monotonic=time.monotonic(), wall_time=datetime.now(), duration=duration
            )
            while len(source.entries) > source.max_entries:
                oldest = min(source.entries, key=lambda key: source.entries[key].monotonic)
                del source.entries[oldest]
            source.last_error = None
            source.error_at = None
            log.debug("source %s%s fetched in %.2fs", name, params or "", duration)
        finally:
            source.in_flight.pop(params, None)
        for listener in self._listeners:
            try:
                listener(name)
            except Exception:  # listeners must never break a fetch
                log.exception("data listener failed")
        return value


def _retrieve_exception(task: asyncio.Future[Any]) -> None:
    """Retrieve the exception of a fetch nobody awaited, which silences asyncio's warning."""
    if not task.cancelled():
        task.exception()
