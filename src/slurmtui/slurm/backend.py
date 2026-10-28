"""The backend protocol every Slurm access implementation fulfils."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from slurmtui.model.records import (
    ActionResult,
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


class SlurmError(Exception):
    """Base class for backend failures."""


class SlurmCommandError(SlurmError):
    def __init__(self, argv: Sequence[str], returncode: int, stderr: str) -> None:
        self.argv = list(argv)
        self.returncode = returncode
        self.stderr = stderr.strip()
        first = self.stderr.splitlines()[0] if self.stderr else f"exit code {returncode}"
        super().__init__(f"{argv[0]} failed: {first}")


class SlurmTimeoutError(SlurmError):
    def __init__(self, argv: Sequence[str], timeout: float) -> None:
        self.argv = list(argv)
        super().__init__(f"{argv[0]} timed out after {timeout:g}s")


class SlurmNotFoundError(SlurmError):
    def __init__(self, binary: str) -> None:
        self.binary = binary
        super().__init__(f"{binary}: command not found (is Slurm on PATH? see [commands].path_prefix)")


class SlurmBackend(ABC):
    """Typed access to a Slurm cluster. Implementations never raise anything but SlurmError."""

    name: str = "abstract"

    @abstractmethod
    def whoami(self) -> str: ...

    @abstractmethod
    async def nodes(self) -> list[Node]: ...

    @abstractmethod
    async def partitions(self) -> list[Partition]: ...

    @abstractmethod
    async def jobs(self) -> list[Job]: ...

    @abstractmethod
    async def reservations(self) -> list[Reservation]: ...

    @abstractmethod
    async def shares(self) -> list[ShareEntry]: ...

    @abstractmethod
    async def scheduler_stats(self) -> SchedulerStats: ...

    @abstractmethod
    async def job_history(self, user: str, since: datetime) -> list[JobRecord]: ...

    @abstractmethod
    async def recent_job_counts(self, since: datetime) -> dict[str, RecentCounts]: ...

    @abstractmethod
    async def account_usage(self, since: datetime) -> list[UsageRecord]: ...

    @abstractmethod
    async def node_detail(self, name: str) -> str: ...

    @abstractmethod
    async def job_detail(self, job_id: str) -> str: ...

    @abstractmethod
    async def job_efficiency(self, job_id: str) -> str | None: ...

    @abstractmethod
    async def hold(self, job_id: str) -> ActionResult: ...

    @abstractmethod
    async def release(self, job_id: str) -> ActionResult: ...

    @abstractmethod
    async def cancel(self, job_id: str) -> ActionResult: ...

    async def version(self) -> str:
        return ""

    async def close(self) -> None:
        return None
