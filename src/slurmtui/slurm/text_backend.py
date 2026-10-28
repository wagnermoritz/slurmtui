"""Base of the backends that answer from command output text: the demo and the test suite."""

from __future__ import annotations

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
from slurmtui.slurm.backend import SlurmBackend, SlurmCommandError
from slurmtui.slurm.commands import DELIMITER, SQUEUE_FIELD_NAMES
from slurmtui.slurm.parsers.common import parse_kv_line
from slurmtui.slurm.parsers.jobs import parse_jobs
from slurmtui.slurm.parsers.nodes import parse_nodes
from slurmtui.slurm.parsers.partitions import parse_partitions
from slurmtui.slurm.parsers.reservations import parse_reservations
from slurmtui.slurm.parsers.sacct import parse_history, parse_recent_counts, parse_usage
from slurmtui.slurm.parsers.sdiag import parse_sdiag
from slurmtui.slurm.parsers.shares import parse_shares


class TextBackend(SlurmBackend):
    """A backend that parses text supplied by :meth:`_read`.

    Query names: ``nodes``, ``partitions``, ``jobs``, ``reservations``, ``shares``,
    ``scheduler``, ``history``, ``recent_jobs``, ``account_usage``, ``version``.
    Detail texts are synthesised from the bulk outputs; hold, release and cancel
    are kept in memory.
    """

    name = "text"

    def __init__(self, user: str) -> None:
        self._user = user
        self._held: set[str] = set()
        self._cancelled: set[str] = set()

    def _read(self, name: str) -> str:
        raise NotImplementedError

    async def _text(self, name: str) -> str:
        return self._read(name)

    def whoami(self) -> str:
        return self._user

    async def nodes(self) -> list[Node]:
        return parse_nodes(await self._text("nodes"))

    async def partitions(self) -> list[Partition]:
        return parse_partitions(await self._text("partitions"))

    async def jobs(self) -> list[Job]:
        jobs = parse_jobs(await self._text("jobs"))
        if self._cancelled:
            jobs = [job for job in jobs if job.job_id not in self._cancelled]
        return jobs

    async def reservations(self) -> list[Reservation]:
        return parse_reservations(await self._text("reservations"))

    async def shares(self) -> list[ShareEntry]:
        return parse_shares(await self._text("shares"))

    async def scheduler_stats(self) -> SchedulerStats:
        return parse_sdiag(await self._text("scheduler"))

    async def job_history(self, user: str, since: datetime) -> list[JobRecord]:
        records = parse_history(await self._text("history"))
        return [record for record in records if record.user == user or not record.user]

    async def recent_job_counts(self, since: datetime) -> dict[str, RecentCounts]:
        return parse_recent_counts(await self._text("recent_jobs"))

    async def account_usage(self, since: datetime) -> list[UsageRecord]:
        return parse_usage(await self._text("account_usage"))

    async def version(self) -> str:
        return (await self._text("version")).strip() or "unknown"

    # -- synthesised details --------------------------------------------------

    async def node_detail(self, name: str) -> str:
        for line in (await self._text("nodes")).splitlines():
            if line.startswith(f"NodeName={name} "):
                return _kv_block(parse_kv_line(line))
        raise SlurmCommandError(["scontrol", "show", "node", name], 1, f"Node {name} not found")

    async def job_detail(self, job_id: str) -> str:
        for line in (await self._text("jobs")).splitlines():
            cells = [cell.strip() for cell in line.split(DELIMITER)]
            if len(cells) < len(SQUEUE_FIELD_NAMES):
                continue
            fields = dict(zip(SQUEUE_FIELD_NAMES, cells))
            if fields["JobArrayID"] == job_id or fields["JobID"] == job_id:
                mapping = {
                    "JobId": fields["JobID"],
                    "ArrayJobId": fields["ArrayJobID"],
                    "ArrayTaskId": fields["ArrayTaskID"],
                    "JobName": fields["Name"],
                    "UserId": fields["UserName"],
                    "Account": fields["Account"],
                    "QOS": fields["QOS"],
                    "JobState": "PENDING" if fields["JobID"] in self._held else fields["State"],
                    "Reason": "JobHeldUser" if fields["JobID"] in self._held else fields["Reason"],
                    "Dependency": fields["Dependency"],
                    "Priority": fields["PriorityLong"],
                    "RunTime": fields["TimeUsed"],
                    "TimeLimit": fields["TimeLimit"],
                    "SubmitTime": fields["SubmitTime"],
                    "StartTime": fields["StartTime"],
                    "Partition": fields["Partition"],
                    "NodeList": fields["NodeList"],
                    "SchedNodeList": fields["SchedNodes"],
                    "NumNodes": fields["NumNodes"],
                    "NumCPUs": fields["NumCPUs"],
                    "NumTasks": fields["NumTasks"],
                    "MinMemory": fields["MinMemory"],
                    "AllocTRES": fields["tres-alloc"],
                    "TresPerJob": fields["tres-per-job"],
                    "TresPerNode": fields["tres-per-node"],
                    "TresPerTask": fields["tres-per-task"],
                    "Command": fields["Command"],
                    "WorkDir": fields["WorkDir"],
                    "StdErr": fields["StdErr"],
                    "StdOut": fields["StdOut"],
                }
                return _kv_block(mapping)
        raise SlurmCommandError(["scontrol", "show", "job", job_id], 1, f"Invalid job id specified: {job_id}")

    async def job_efficiency(self, job_id: str) -> str | None:
        for record in parse_history(await self._text("history")):
            if record.job_id == job_id:
                lines = [
                    f"Job ID: {record.raw_id}",
                    f"User/Group: {record.user}/-",
                    f"State: {record.state} (exit code {record.exit_code.split(':')[0]})",
                    f"Cores: {record.alloc_cpus}",
                ]
                if record.cpu_eff is not None:
                    lines.append(f"CPU Efficiency: {100 * record.cpu_eff:.2f}%")
                if record.mem_eff is not None:
                    lines.append(f"Memory Efficiency: {100 * record.mem_eff:.2f}%")
                return "\n".join(lines)
        return None

    # -- simulated actions ----------------------------------------------------

    async def hold(self, job_id: str) -> ActionResult:
        self._held.add(job_id.split("_")[0])
        return ActionResult(ok=True, command=f"scontrol hold {job_id}", output="OK (simulated)")

    async def release(self, job_id: str) -> ActionResult:
        self._held.discard(job_id.split("_")[0])
        return ActionResult(ok=True, command=f"scontrol release {job_id}", output="OK (simulated)")

    async def cancel(self, job_id: str) -> ActionResult:
        self._cancelled.add(job_id)
        return ActionResult(ok=True, command=f"scancel {job_id}", output="OK (simulated)")


def _kv_block(fields: dict[str, str]) -> str:
    """Render key=value pairs roughly like multi-line scontrol output."""
    lines: list[str] = []
    current: list[str] = []
    for key, value in fields.items():
        current.append(f"{key}={value}")
        if len(current) == 3 or len(" ".join(current)) > 70:
            lines.append("   " + " ".join(current))
            current = []
    if current:
        lines.append("   " + " ".join(current))
    if lines:
        lines[0] = lines[0].lstrip()
    return "\n".join(lines) + "\n"
