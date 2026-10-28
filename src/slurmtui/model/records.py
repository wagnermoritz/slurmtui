"""Typed records for every Slurm entity shown in the TUI.

Fields marked *derived* are filled by :mod:`slurmtui.model.derive` from the
site configuration after parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from slurmtui.model.states import NodeState
from slurmtui.model.tres import TRES


@dataclass(frozen=True)
class NodeReason:
    text: str
    user: str | None = None
    time: datetime | None = None


@dataclass(frozen=True)
class Node:
    name: str
    state: NodeState
    partitions: tuple[str, ...]
    cpus_total: int
    cpus_alloc: int
    cpu_load: float | None
    mem_total: int
    mem_alloc: int
    mem_free: int | None
    gpus_total: int
    gpus_alloc: int
    gpu_gres_type: str | None
    gpu_gres: str
    features: tuple[str, ...]
    arch: str | None
    sockets: int
    cores_per_socket: int
    threads_per_core: int
    reason: NodeReason | None
    cfg_tres: TRES
    alloc_tres: TRES
    # derived
    node_group: str = ""
    gpu_type: str | None = None
    cpu_type: str = ""
    max_time: timedelta | None = None
    avail: str = "up"
    jobs_running: int = 0  # running jobs on the node, attached by the NODES tab from the jobs source

    @property
    def cpus_free(self) -> int:
        return max(self.cpus_total - self.cpus_alloc, 0)

    @property
    def gpus_free(self) -> int:
        return max(self.gpus_total - self.gpus_alloc, 0)


@dataclass(frozen=True)
class Partition:
    name: str
    state: str
    max_time: timedelta | None
    default_time: timedelta | None
    is_default: bool
    nodes: tuple[str, ...]
    total_cpus: int
    total_nodes: int
    tres: TRES
    max_nodes: str = ""


@dataclass(frozen=True)
class Job:
    job_id: str
    raw_id: int
    array_job_id: int | None
    array_task: str | None
    task_count: int
    partition: str
    name: str
    user: str
    account: str
    qos: str
    state: str
    reason: str
    time_used: timedelta | None
    time_limit: timedelta | None
    submit_time: datetime | None
    start_time: datetime | None
    num_nodes: int
    cpus: int
    tasks: int
    mem_requested: int | None
    tres_alloc: TRES
    gpus_requested: int
    node_list: tuple[str, ...]
    sched_nodes: tuple[str, ...]
    priority: int
    dependency: str | None
    work_dir: str
    stdout: str | None
    stderr: str | None
    command: str | None
    # derived
    node_group: str = ""
    is_gpu_job: bool = False

    @property
    def is_running(self) -> bool:
        return self.state in {"RUNNING", "COMPLETING", "CONFIGURING"}

    @property
    def command_id(self) -> str:
        """The id to pass to scontrol/scancel: the array job id for a pending array group."""
        return str(self.raw_id) if "[" in self.job_id else self.job_id

    @property
    def is_pending(self) -> bool:
        return self.state == "PENDING"

    @property
    def gpus(self) -> int:
        return self.tres_alloc.gpu if self.tres_alloc.gpu else self.gpus_requested

    @property
    def memory(self) -> int | None:
        if self.tres_alloc.mem:
            return self.tres_alloc.mem
        return self.mem_requested

    @property
    def time_left(self) -> timedelta | None:
        if self.time_limit is None or self.time_used is None or self.time_limit == timedelta.max:
            return None
        return max(self.time_limit - self.time_used, timedelta(0))


@dataclass(frozen=True)
class Reservation:
    name: str
    state: str
    start: datetime | None
    end: datetime | None
    nodes: tuple[str, ...]
    node_spec: str
    users: tuple[str, ...]
    accounts: tuple[str, ...]
    flags: tuple[str, ...]

    @property
    def is_active(self) -> bool:
        return self.state.upper() == "ACTIVE"


@dataclass(frozen=True)
class ShareEntry:
    account: str
    user: str | None
    raw_shares: float | None
    norm_shares: float | None
    raw_usage: float | None
    effective_usage: float | None
    fairshare: float | None
    level_fs: float | None

    @property
    def is_account(self) -> bool:
        return not self.user


@dataclass(frozen=True)
class SchedulerStats:
    data_since: datetime | None = None
    server_threads: int | None = None
    jobs_submitted: int | None = None
    jobs_started: int | None = None
    jobs_completed: int | None = None
    jobs_canceled: int | None = None
    jobs_failed: int | None = None
    jobs_pending: int | None = None
    jobs_running: int | None = None
    queue_length: int | None = None
    mean_cycle_us: int | None = None
    last_cycle_us: int | None = None
    max_cycle_us: int | None = None
    total_cycles: int | None = None
    backfill_total_jobs: int | None = None
    backfill_last_cycle_jobs: int | None = None
    backfill_last_cycle_us: int | None = None
    backfill_mean_cycle_us: int | None = None
    backfill_depth_mean: int | None = None
    backfill_queue_length: int | None = None


@dataclass(frozen=True)
class JobRecord:
    """A finished (or running) job from the accounting database."""

    job_id: str
    raw_id: str
    name: str
    partition: str
    account: str
    user: str
    state: str
    exit_code: str
    elapsed: timedelta | None
    time_limit: timedelta | None
    alloc_cpus: int
    tres_alloc: TRES
    req_mem: int | None
    max_rss: int | None
    total_cpu: timedelta | None
    submit: datetime | None
    start: datetime | None
    end: datetime | None
    node_list: tuple[str, ...]
    stdout: str | None
    work_dir: str | None

    @property
    def mem_eff(self) -> float | None:
        if not self.req_mem or self.max_rss is None:
            return None
        return self.max_rss / self.req_mem

    @property
    def cpu_eff(self) -> float | None:
        if self.total_cpu is None or not self.elapsed or not self.alloc_cpus:
            return None
        wall = self.elapsed.total_seconds() * self.alloc_cpus
        return self.total_cpu.total_seconds() / wall if wall > 0 else None

    @property
    def gpus(self) -> int:
        return self.tres_alloc.gpu


@dataclass(frozen=True)
class UsageRecord:
    account: str
    partition: str
    tres_alloc: TRES
    node_list: tuple[str, ...]
    start: datetime | None
    end: datetime | None


@dataclass(frozen=True)
class RecentCounts:
    jobs_24h: int = 0
    jobs_7d: int = 0


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    command: str
    output: str


# Aggregated rows ------------------------------------------------------------


@dataclass(frozen=True)
class UserRow:
    user: str
    jobs_running: int
    jobs_pending: int
    jobs_other: int
    cpus: int
    gpus: int
    memory: int
    nodes: tuple[str, ...]
    partitions: tuple[str, ...]
    accounts: tuple[str, ...]
    usage: float | None
    raw_usage: float | None
    fairshare: float | None
    jobs_24h: int | None = None
    jobs_7d: int | None = None


@dataclass(frozen=True)
class AccountRow:
    account: str
    shares: float | None
    raw_usage: float | None
    usage: float | None
    level_fs: float | None
    fairshare: float | None
    jobs_running: int
    jobs_pending: int
    cpus: int
    gpus: int
    memory: int
    members: int
    members_active: int
    oldest_pending: timedelta | None
    cpu_hours: dict[str, float] = field(default_factory=dict)
    gpu_hours: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class UsageBarData:
    label: str
    used: int
    total: int


@dataclass(frozen=True)
class GroupOverview:
    group: str
    gpus: list[UsageBarData]
    cpus: list[UsageBarData]
    memory: UsageBarData
    node_states: dict[str, int]
    node_total: int
    running: int
    pending: int
    pending_reasons: list[tuple[str, int]]
    reservations: list[Reservation]
