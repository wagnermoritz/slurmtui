"""Backend that runs the Slurm command line tools."""

from __future__ import annotations

import asyncio
import functools
import getpass
import logging
import os
import re
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from slurmtui.config.schema import CommandsConfig
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
from slurmtui.slurm import commands
from slurmtui.slurm.backend import SlurmBackend, SlurmCommandError, SlurmNotFoundError, SlurmTimeoutError
from slurmtui.slurm.parsers.jobs import parse_jobs
from slurmtui.slurm.parsers.nodes import parse_nodes
from slurmtui.slurm.parsers.partitions import parse_partitions
from slurmtui.slurm.parsers.reservations import parse_reservations
from slurmtui.slurm.parsers.sacct import parse_history, parse_recent_counts, parse_usage
from slurmtui.slurm.parsers.sdiag import parse_sdiag
from slurmtui.slurm.parsers.shares import parse_shares

log = logging.getLogger(__name__)
T = TypeVar("T")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.\-\[\],%+]+$")

# Per-tool defaults from the user's shell (SQUEUE_USERS, SQUEUE_FORMAT2, SCONTROL_ALL, ...)
# would filter or reformat the output. SLURM_CONF and SLURM_CLUSTERS select the cluster and stay.
_DROPPED_ENV_PREFIXES = ("SQUEUE_", "SACCT_", "SCONTROL_", "SSHARE_", "SDIAG_")
_FIXED_ENV = {
    "LC_ALL": "C",
    "SLURM_TIME_FORMAT": "standard",  # ISO timestamps
    "SLURM_BITSTR_LEN": "0",  # full array task lists ("[1-5000]" instead of "[1-64,...]")
}


def command_environment(base: dict[str, str], overrides: dict[str, str]) -> dict[str, str]:
    """Process environment minus the per-tool defaults, plus the fixed settings and ``[commands].env``."""
    env = {key: value for key, value in base.items() if not key.startswith(_DROPPED_ENV_PREFIXES)}
    env.update(_FIXED_ENV)
    env.update(overrides)
    return env


def check_identifier(value: str, what: str) -> str:
    """Guard for values spliced into command lines as separate arguments."""
    if not value or not _IDENTIFIER_RE.match(value) or value.startswith("-"):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


class CliBackend(SlurmBackend):
    name = "cli"

    def __init__(self, config: CommandsConfig, capture_dir: Path | None = None, max_rss_unit: str = "auto") -> None:
        self.config = config
        self.capture_dir = capture_dir
        self.max_rss_unit = max_rss_unit
        self._user = getpass.getuser()

    def whoami(self) -> str:
        return self._user

    # -- running commands -----------------------------------------------------

    def _argv(self, argv: Sequence[str]) -> list[str]:
        resolved = list(argv)
        if self.config.path_prefix:
            resolved[0] = os.path.join(self.config.path_prefix, resolved[0])
        return resolved

    async def run(
        self,
        argv: Sequence[str],
        *,
        ok_returncodes: Sequence[int] = (0,),
        capture_as: str | None = None,
        timeout: float | None = None,
    ) -> str:
        """Run argv and return stdout. Raises SlurmError subclasses on failure."""
        resolved = self._argv(argv)
        env = command_environment(dict(os.environ), self.config.env)
        timeout = timeout or self.config.timeout_seconds
        log.debug("run %s", " ".join(resolved))
        try:
            proc = await asyncio.create_subprocess_exec(
                *resolved,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                env=env,
            )
        except FileNotFoundError as exc:
            raise SlurmNotFoundError(resolved[0]) from exc
        except OSError as exc:
            raise SlurmCommandError(resolved, -1, str(exc)) from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise SlurmTimeoutError(resolved, timeout) from exc
        text = stdout.decode("utf-8", errors="replace")
        if proc.returncode not in ok_returncodes:
            raise SlurmCommandError(resolved, proc.returncode or -1, stderr.decode("utf-8", errors="replace"))
        if self.capture_dir is not None and capture_as:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / f"{capture_as}.txt").write_text(text, encoding="utf-8")
        return text

    async def _query(self, argv: Sequence[str], parser: Callable[[str], T], capture_as: str) -> T:
        text = await self.run(argv, capture_as=capture_as)
        return await asyncio.to_thread(parser, text)

    # -- queries --------------------------------------------------------------

    async def nodes(self) -> list[Node]:
        return await self._query(commands.nodes(), parse_nodes, "nodes")

    async def partitions(self) -> list[Partition]:
        return await self._query(commands.partitions(), parse_partitions, "partitions")

    async def jobs(self) -> list[Job]:
        return await self._query(commands.jobs(), parse_jobs, "jobs")

    async def reservations(self) -> list[Reservation]:
        return await self._query(commands.reservations(), parse_reservations, "reservations")

    async def shares(self) -> list[ShareEntry]:
        return await self._query(commands.shares(), parse_shares, "shares")

    async def scheduler_stats(self) -> SchedulerStats:
        return await self._query(commands.scheduler(), parse_sdiag, "scheduler")

    async def job_history(self, user: str, since: datetime) -> list[JobRecord]:
        check_identifier(user, "user name")
        parse = functools.partial(parse_history, max_rss_unit=self.max_rss_unit)
        return await self._query(commands.history(user, since), parse, "history")

    async def recent_job_counts(self, since: datetime) -> dict[str, RecentCounts]:
        return await self._query(commands.recent_jobs(since), parse_recent_counts, "recent_jobs")

    async def account_usage(self, since: datetime) -> list[UsageRecord]:
        return await self._query(commands.account_usage(since), parse_usage, "account_usage")

    async def node_detail(self, name: str) -> str:
        check_identifier(name, "node name")
        return await self.run(commands.node_detail(name))

    async def job_detail(self, job_id: str) -> str:
        check_identifier(job_id, "job id")
        return await self.run(commands.job_detail(job_id))

    async def job_efficiency(self, job_id: str) -> str | None:
        check_identifier(job_id, "job id")
        try:
            text = await self.run(commands.job_efficiency(job_id), ok_returncodes=(0, 1))
        except SlurmNotFoundError:
            return None
        except SlurmCommandError:
            return None
        return text.strip() or None

    async def version(self) -> str:
        try:
            return (await self.run(commands.version())).strip()
        except SlurmCommandError:
            return ""

    # -- actions --------------------------------------------------------------

    async def _action(self, argv: Sequence[str]) -> ActionResult:
        command = " ".join(argv)
        try:
            output = await self.run(argv)
            return ActionResult(ok=True, command=command, output=output.strip() or "OK")
        except SlurmCommandError as exc:
            return ActionResult(ok=False, command=command, output=exc.stderr or str(exc))
        except (SlurmNotFoundError, SlurmTimeoutError) as exc:
            return ActionResult(ok=False, command=command, output=str(exc))

    async def hold(self, job_id: str) -> ActionResult:
        return await self._action(commands.hold(check_identifier(job_id, "job id")))

    async def release(self, job_id: str) -> ActionResult:
        return await self._action(commands.release(check_identifier(job_id, "job id")))

    async def cancel(self, job_id: str) -> ActionResult:
        return await self._action(commands.cancel(check_identifier(job_id, "job id")))
