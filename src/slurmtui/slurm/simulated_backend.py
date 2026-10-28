"""The simulated cluster behind ``slurmtui --demo``.

An in-memory model of 18 nodes, three partitions and a queue that moves with
the wall clock: jobs arrive, start when resources free up and finish;
hold/release/cancel act on the model. Each query renders the model as the
text the Slurm tools would print, so :class:`TextBackend` parses it like a
real cluster.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from importlib import resources
from pathlib import Path

from slurmtui.model.records import ActionResult
from slurmtui.slurm.commands import DELIMITER, SACCT_HISTORY_FIELDS, SQUEUE_FIELDS, SSHARE_DELIMITER
from slurmtui.slurm.parsers import hostlist
from slurmtui.slurm.text_backend import TextBackend

WHOAMI = "demo"
ACCOUNTS: dict[str, list[str]] = {
    "physics": ["alice", "bob"],
    "biology": ["carol", "dave", "grace"],
    "mlgroup": ["erin", "frank", WHOAMI],
}
USERS = [user for members in ACCOUNTS.values() for user in members]
USER_ACCOUNT = {user: account for account, members in ACCOUNTS.items() for user in members}
JOB_NAMES = ["train", "eval", "preprocess", "sweep", "simulate", "align", "bench", "analysis", "fold", "render"]
PARTITIONS: dict[str, tuple[str, bool]] = {
    "cpu": ("2-00:00:00", True),
    "long": ("7-00:00:00", False),
    "gpu": ("2-00:00:00", False),
}
FINAL_STATES = ["COMPLETED"] * 16 + ["FAILED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY"]
SLURM_VERSION = "24.11.7"


def demo_config_path() -> Path:
    """The site configuration that ``--demo`` uses instead of the installed one."""
    return Path(str(resources.files("slurmtui").joinpath("demo", "site-config.toml")))


def _ts(when: datetime | None) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S") if when else "Unknown"


def _dur(delta: timedelta) -> str:
    total = max(int(delta.total_seconds()), 0)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    if days:
        return f"{days}-{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _parse_dur(text: str) -> timedelta:
    days, _, clock = text.rpartition("-")
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return timedelta(days=int(days or 0), hours=hours, minutes=minutes, seconds=seconds)


def _contract_ints(values: list[int]) -> str:
    ranges: list[str] = []
    for value in sorted(values):
        if ranges and ranges[-1].endswith(f"-{value - 1}"):
            ranges[-1] = ranges[-1].rsplit("-", 1)[0] + f"-{value}"
        elif ranges and ranges[-1] == str(value - 1):
            ranges[-1] = f"{value - 1}-{value}"
        else:
            ranges.append(str(value))
    return ",".join(ranges)


@dataclass
class SimNode:
    name: str
    partitions: tuple[str, ...]
    cpus: int
    mem_mb: int
    gpus: int
    gpu_type: str | None
    features: str
    sockets: int
    cores: int
    boot: datetime
    down: str | None = None  # reason while DOWN
    drain: str | None = None  # reason while DRAIN

    @property
    def usable(self) -> bool:
        return self.down is None and self.drain is None


@dataclass
class SimJob:
    job_id: int
    name: str
    user: str
    account: str
    partition: str
    cpus: int
    mem_mb: int
    gpus: int
    time_limit: timedelta
    run_time: timedelta
    final_state: str
    submit: datetime
    priority: int
    cpu_eff: float
    mem_frac: float
    gpu_type: str | None = None  # requested GPU type (--gres=gpu:h200:2), None for any
    alloc_gpu_type: str | None = None  # type of the GPUs the job runs on
    dependency: int | None = None
    array_job_id: int | None = None
    array_task: int | None = None
    array_parent: bool = False  # the pending array; its tasks become jobs of their own when they start
    array_pending: list[int] = field(default_factory=list)
    array_throttle: int = 0
    start: datetime | None = None
    end: datetime | None = None
    node: str | None = None
    state: str = "PENDING"
    reason: str = "Priority"
    held: bool = False

    @property
    def is_pending(self) -> bool:
        return self.state == "PENDING"

    @property
    def is_running(self) -> bool:
        return self.state == "RUNNING"

    @property
    def is_done(self) -> bool:
        return not (self.is_pending or self.is_running)

    @property
    def display_id(self) -> str:
        if self.array_pending:
            throttle = f"%{self.array_throttle}" if self.array_throttle else ""
            return f"{self.job_id}_[{_contract_ints(self.array_pending)}{throttle}]"
        if self.array_task is not None:
            return f"{self.array_job_id}_{self.array_task}"
        return str(self.job_id)

    @property
    def work_dir(self) -> str:
        return f"/home/{self.user}/{self.name.split('_')[0]}"


class SimulatedBackend(TextBackend):
    """The ``--demo`` backend."""

    name = "simulated"

    def __init__(
        self, seed: int = 7, clock: Callable[[], datetime] | None = None, history: timedelta = timedelta(hours=3)
    ) -> None:
        super().__init__(WHOAMI)
        self._clock = clock or datetime.now
        self._rng = random.Random(seed)
        now = self._clock()
        self._started = now - history
        self._time = self._started
        self._next_arrival = self._started
        self._next_id = 1000
        self._nodes = self._build_nodes(self._started)
        self._jobs: list[SimJob] = []
        self._counters = {"submitted": 0, "started": 0, "completed": 0, "canceled": 0, "failed": 0}
        self._advance(now)

    # -- the model ------------------------------------------------------------

    def _build_nodes(self, boot: datetime) -> list[SimNode]:
        # (names, partitions, cpus, mem_mb, gpus, gpu type, features, sockets, cores)
        classes: list[tuple[range, tuple[str, ...], int, int, int, str | None, str, int, int]] = [
            (range(1, 5), ("cpu", "long"), 64, 256000, 0, None, "Intel,Xeon,Gold6338,Infiniband", 2, 16),
            (range(5, 9), ("cpu", "long"), 64, 512000, 0, None, "AMD,EPYC7543,Infiniband", 2, 32),
            (range(9, 13), ("cpu",), 96, 768000, 0, None, "AMD,EPYC9454,Infiniband", 2, 48),
        ]
        gpu_classes: list[tuple[range, tuple[str, ...], int, int, int, str | None, str, int, int]] = [
            (range(1, 3), ("gpu",), 64, 512000, 4, "a100", "AMD,EPYC7543,A100,A100-40GB,Infiniband", 2, 32),
            (
                range(3, 7),
                ("gpu",),
                96,
                2048000,
                4,
                "h200",
                "Intel,Xeon,Platinum8568Y,H200,H200-141GB,Infiniband",
                2,
                48,
            ),
        ]
        nodes = [
            SimNode(f"{prefix}{i:02d}", parts, cpus, mem, gpus, gpu_type, features, sockets, cores, boot)
            for prefix, group in (("n", classes), ("g", gpu_classes))
            for numbers, parts, cpus, mem, gpus, gpu_type, features, sockets, cores in group
            for i in numbers
        ]
        nodes[10].down = "Not responding"
        nodes[11].drain = "Memory errors"
        return nodes

    def _new_job(self, submit: datetime) -> SimJob:
        rng = self._rng
        user = WHOAMI if rng.random() < 0.15 else rng.choice(USERS)
        partition = rng.choices(["cpu", "long", "gpu"], [55, 15, 30])[0]
        gpu_type = None
        if partition == "gpu":
            gpus = rng.choice([1, 1, 2, 4])
            cpus = gpus * 8
            mem_mb = cpus * 4000
            if rng.random() < 0.35:
                gpu_type = rng.choice(["a100", "h200", "h200"])
        else:
            gpus = 0
            cpus = rng.choice([4, 8, 16, 32, 64])
            mem_mb = cpus * rng.choice([2000, 4000, 8000])
        limit_minutes = rng.choice([30, 60, 120, 240]) if partition != "long" else rng.choice([480, 1440, 2880])
        limit = timedelta(minutes=limit_minutes)
        final = rng.choice(FINAL_STATES)
        if final == "TIMEOUT" and limit_minutes > 30:
            final = "COMPLETED"
        run_time = limit if final == "TIMEOUT" else timedelta(seconds=rng.uniform(90, min(limit.total_seconds(), 2400)))
        self._next_id += rng.randint(1, 3)
        job = SimJob(
            job_id=self._next_id,
            name=rng.choice(JOB_NAMES) + rng.choice(["", "", f"_{rng.randint(1, 30)}", "-v2"]),
            user=user,
            account=USER_ACCOUNT[user],
            partition=partition,
            cpus=cpus,
            mem_mb=mem_mb,
            gpus=gpus,
            gpu_type=gpu_type,
            time_limit=limit,
            run_time=run_time,
            final_state=final,
            submit=submit,
            priority=int(100000 - (submit - self._started).total_seconds() / 60) + rng.randint(-300, 300),
            cpu_eff=rng.uniform(0.2, 0.98),
            mem_frac=1.05 if final == "OUT_OF_MEMORY" else rng.uniform(0.05, 0.9),
        )
        own_jobs = [other for other in self._jobs if other.user == user and not other.is_done]
        if own_jobs and rng.random() < 0.1:
            job.dependency = own_jobs[-1].job_id
        elif rng.random() < 0.06:
            job.array_parent = True
            job.array_pending = list(range(1, rng.randint(6, 24) + 1))
            job.array_throttle = rng.choice([0, 4, 4, 8])
        return job

    def _free(self) -> dict[str, list[int]]:
        free = {node.name: [node.cpus, node.mem_mb, node.gpus] for node in self._nodes if node.usable}
        for job in self._jobs:
            if job.is_running and job.node in free:
                slot = free[job.node]
                slot[0] -= job.cpus
                slot[1] -= job.mem_mb
                slot[2] -= job.gpus
        return free

    def _start(self, job: SimJob, node: str, when: datetime, free: dict[str, list[int]]) -> None:
        job.start, job.node, job.state, job.reason = when, node, "RUNNING", "None"
        job.alloc_gpu_type = next(n.gpu_type for n in self._nodes if n.name == node) if job.gpus else None
        free[node][0] -= job.cpus
        free[node][1] -= job.mem_mb
        free[node][2] -= job.gpus
        self._counters["started"] += 1

    def _fit(self, job: SimJob, free: dict[str, list[int]]) -> str | None:
        for node in self._nodes:
            slot = free.get(node.name)
            if slot is None or job.partition not in node.partitions:
                continue
            if job.gpu_type is not None and node.gpu_type != job.gpu_type:
                continue
            if slot[0] >= job.cpus and slot[1] >= job.mem_mb and slot[2] >= job.gpus:
                return node.name
        return None

    def _schedule(self, when: datetime) -> None:
        free = self._free()
        by_id = {job.job_id: job for job in self._jobs}
        blocked = False
        for job in sorted((job for job in self._jobs if job.is_pending), key=lambda job: -job.priority):
            if job.held:
                job.reason = "JobHeldUser"
                continue
            if job.dependency is not None:
                dependency = by_id.get(job.dependency)
                if dependency is not None and not dependency.is_done:
                    job.reason = "Dependency"
                    continue
                if dependency is not None and dependency.state != "COMPLETED":
                    job.reason = "DependencyNeverSatisfied"
                    continue
            if job.array_pending:
                running = sum(1 for other in self._jobs if other.array_job_id == job.job_id and other.is_running)
                while job.array_pending and (not job.array_throttle or running < job.array_throttle):
                    node = self._fit(job, free)
                    if node is None:
                        break
                    task = job.array_pending.pop(0)
                    self._next_id += 1
                    child = SimJob(
                        **{
                            **job.__dict__,
                            "job_id": self._next_id,
                            "array_parent": False,
                            "array_pending": [],
                            "dependency": None,
                        }
                    )
                    child.array_job_id, child.array_task = job.job_id, task
                    child.run_time = job.run_time * self._rng.uniform(0.7, 1.3)
                    child.priority = job.priority
                    self._jobs.append(child)
                    self._start(child, node, when, free)
                    running += 1
                if not job.array_pending:
                    job.state, job.end, job.reason = "COMPLETED", when, "None"  # the array parent is done
                else:
                    job.reason = (
                        "JobArrayTaskLimit" if job.array_throttle and running >= job.array_throttle else "Resources"
                    )
                continue
            node = self._fit(job, free)
            if node is not None:
                self._start(job, node, when, free)
            else:
                job.reason = "Priority" if blocked else "Resources"
                blocked = True

    def _finish_due(self, until: datetime) -> None:
        for job in self._jobs:
            if job.is_running and job.start is not None and job.start + job.run_time <= until:
                job.end = job.start + job.run_time
                job.state = job.final_state
                self._counters["completed" if job.final_state == "COMPLETED" else "failed"] += 1

    def _advance(self, now: datetime) -> None:
        """Replay arrivals, completions and scheduling decisions up to ``now``, event by event."""
        while True:
            next_end = min(
                (job.start + job.run_time for job in self._jobs if job.is_running and job.start), default=None
            )
            event = self._next_arrival if next_end is None else min(self._next_arrival, next_end)
            if event > now:
                break
            self._time = event
            self._finish_due(event)
            if event >= self._next_arrival:
                self._jobs.append(self._new_job(self._next_arrival))
                self._counters["submitted"] += 1
                pending = sum(1 for job in self._jobs if job.is_pending)
                self._next_arrival += timedelta(seconds=self._rng.uniform(20, 70) * (1 + pending / 15))
            self._schedule(event)
        self._time = now
        self._jobs = [job for job in self._jobs if not (job.is_done and job.end and now - job.end > timedelta(days=7))]

    # -- rendering ------------------------------------------------------------

    def _read(self, name: str) -> str:
        now = self._clock()
        self._advance(now)
        renderers: dict[str, Callable[[datetime], str]] = {
            "nodes": self._nodes_text,
            "partitions": self._partitions_text,
            "jobs": self._jobs_text,
            "reservations": self._reservations_text,
            "shares": self._shares_text,
            "scheduler": self._sdiag_text,
            "history": self._history_text,
            "recent_jobs": self._recent_text,
            "account_usage": self._usage_text,
            "version": lambda _now: f"slurm {SLURM_VERSION}\n",
            "whoami": lambda _now: WHOAMI + "\n",
        }
        renderer = renderers.get(name)
        return renderer(now) if renderer else ""

    def _nodes_text(self, now: datetime) -> str:
        alloc: dict[str, list[int]] = {node.name: [0, 0, 0] for node in self._nodes}
        for job in self._jobs:
            if job.is_running and job.node in alloc:
                alloc[job.node][0] += job.cpus
                alloc[job.node][1] += job.mem_mb
                alloc[job.node][2] += job.gpus
        lines = []
        for node in self._nodes:
            cpus, mem, gpus = alloc[node.name]
            if node.down:
                state = "DOWN"
            else:
                state = "ALLOCATED" if cpus >= node.cpus else "MIXED" if cpus else "IDLE"
                if node.drain:
                    state += "+DRAIN"
            gres = f"gpu:{node.gpu_type}:{node.gpus}(S:0-1)" if node.gpus else "(null)"
            idx = "N/A" if not gpus else "0" if gpus == 1 else f"0-{gpus - 1}"
            gres_used = f"gpu:{node.gpu_type}:{gpus}(IDX:{idx})" if node.gpus else ""
            cfg = f"cpu={node.cpus},mem={node.mem_mb}M,billing={node.cpus}"
            alloc_tres = f"cpu={cpus},mem={mem}M" if cpus else ""
            if node.gpus:
                cfg += f",gres/gpu={node.gpus},gres/gpu:{node.gpu_type}={node.gpus}"
                if gpus:
                    alloc_tres += f",gres/gpu={gpus},gres/gpu:{node.gpu_type}={gpus}"
            reason = node.down or node.drain
            reason_text = f" Reason={reason} [root@{_ts(node.boot + timedelta(hours=5))}]" if reason else ""
            load = f"{cpus * 0.92:.2f}" if not node.down else "0.00"
            free_mem = node.mem_mb - mem - 4000 if not node.down else 0
            lines.append(
                f"NodeName={node.name} Arch=x86_64 CoresPerSocket={node.cores} CPUAlloc={cpus} CPUEfctv={node.cpus} "
                f"CPUTot={node.cpus} CPULoad={load} AvailableFeatures={node.features} ActiveFeatures={node.features} "
                f"Gres={gres} GresDrain=N/A GresUsed={gres_used} NodeAddr={node.name} NodeHostName={node.name} "
                f"Version={SLURM_VERSION} OS=Linux 6.12.0 #1 SMP RealMemory={node.mem_mb} AllocMem={mem} "
                f"FreeMem={max(free_mem, 0)} Sockets={node.sockets} Boards=1 State={state} ThreadsPerCore=1 TmpDisk=0 "
                f"Weight=1 Owner=N/A MCS_label=N/A Partitions={','.join(node.partitions)} BootTime={_ts(node.boot)} "
                f"SlurmdStartTime={_ts(node.boot)} LastBusyTime={_ts(now - timedelta(minutes=3))} ResumeAfterTime=None "
                f"CfgTRES={cfg} AllocTRES={alloc_tres} CurrentWatts=0 AveWatts=0{reason_text}"
            )
        return "\n".join(lines) + "\n"

    def _partitions_text(self, now: datetime) -> str:
        lines = []
        for name, (max_time, default) in PARTITIONS.items():
            members = [node for node in self._nodes if name in node.partitions]
            cpus = sum(node.cpus for node in members)
            mem = sum(node.mem_mb for node in members)
            gpus = sum(node.gpus for node in members)
            tres = f"cpu={cpus},mem={mem}M,node={len(members)},billing={cpus}"
            if gpus:
                by_type: dict[str, int] = {}
                for node in members:
                    if node.gpus and node.gpu_type:
                        by_type[node.gpu_type] = by_type.get(node.gpu_type, 0) + node.gpus
                tres += f",gres/gpu={gpus}" + "".join(
                    f",gres/gpu:{kind}={count}" for kind, count in sorted(by_type.items())
                )
            lines.append(
                f"PartitionName={name} AllowGroups=ALL AllowAccounts=ALL AllowQos=ALL AllocNodes=ALL "
                f"Default={'YES' if default else 'NO'} QoS=N/A DefaultTime=01:00:00 DisableRootJobs=NO "
                f"ExclusiveUser=NO GraceTime=0 Hidden=NO MaxNodes=UNLIMITED MaxTime={max_time} MinNodes=0 LLN=NO "
                f"MaxCPUsPerNode=UNLIMITED Nodes={hostlist.contract([node.name for node in members])} "
                f"PriorityJobFactor=1 PriorityTier=1 RootOnly=NO "
                f"ReqResv=NO OverSubscribe=NO OverTimeLimit=NONE PreemptMode=OFF State=UP TotalCPUs={cpus} "
                f"TotalNodes={len(members)} SelectTypeParameters=NONE JobDefaults=(null) DefMemPerNode=UNLIMITED "
                f"MaxMemPerNode=UNLIMITED TRES={tres}"
            )
        return "\n".join(lines) + "\n"

    def _reservations_text(self, now: datetime) -> str:
        start = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        return (
            f"ReservationName=maintenance StartTime={_ts(start)} EndTime={_ts(start + timedelta(hours=4))} "
            f"Duration=04:00:00 "
            f"Nodes=n[09-10] NodeCnt=2 CoreCnt=128 Features=(null) PartitionName=(null) Flags=MAINT,SPEC_NODES "
            f"TRES=cpu=128 Users=(null) Groups=(null) Accounts=root Licenses=(null) State=INACTIVE BurstBuffer=(null) "
            f"MaxStartDelay=(null)\n"
        )

    def _tres_alloc(self, job: SimJob) -> str:
        tres = f"cpu={job.cpus},mem={job.mem_mb}M,node=1,billing={job.cpus}"
        if job.gpus:
            tres += f",gres/gpu={job.gpus},gres/gpu:{job.alloc_gpu_type or 'gpu'}={job.gpus}"
        return tres

    def _jobs_text(self, now: datetime) -> str:
        lines = []
        for job in sorted(self._jobs, key=lambda job: job.job_id):
            if job.is_done:
                continue
            tasks = (
                f"[{_contract_ints(job.array_pending)}{'%' + str(job.array_throttle) if job.array_throttle else ''}]"
            )
            row = {
                "JobArrayID": job.display_id,
                "JobID": str(job.job_id),
                "ArrayJobID": str(job.array_job_id or job.job_id)
                if (job.array_pending or job.array_task is not None)
                else "N/A",
                "ArrayTaskID": tasks
                if job.array_pending
                else str(job.array_task)
                if job.array_task is not None
                else "N/A",
                "Partition": job.partition,
                "Name": job.name,
                "UserName": job.user,
                "Account": job.account,
                "QOS": "normal",
                "State": job.state,
                "Reason": job.reason,
                "TimeUsed": _dur(now - job.start) if job.start else "0:00",
                "TimeLimit": _dur(job.time_limit),
                "SubmitTime": _ts(job.submit),
                "StartTime": _ts(job.start) if job.start else "N/A",
                "NumNodes": "1",
                "NumCPUs": str(job.cpus),
                "NumTasks": "1",
                "MinMemory": f"{job.mem_mb}M",
                "tres-alloc": self._tres_alloc(job) if job.is_running else "N/A",
                "tres-per-job": "N/A",
                "tres-per-node": (f"gres/gpu:{job.gpu_type}:{job.gpus}" if job.gpu_type else f"gres/gpu:{job.gpus}")
                if job.gpus
                else "N/A",
                "tres-per-task": "N/A",
                "PriorityLong": str(job.priority),
                "NodeList": job.node or "",
                "SchedNodes": "(null)",
                "Dependency": f"afterok:{job.dependency}" if job.dependency else "(null)",
                "WorkDir": job.work_dir,
                "StdOut": f"{job.work_dir}/slurm-{job.job_id}.out",
                "StdErr": f"{job.work_dir}/slurm-{job.job_id}.out",
                "Command": f"{job.work_dir}/run.sh",
            }
            lines.append("".join(f"{row[name]}{DELIMITER}" for name, _ in SQUEUE_FIELDS))
        return "\n".join(lines) + "\n"

    def _raw_usage(self) -> dict[str, float]:
        usage = {user: 0.0 for user in USERS}
        for job in self._jobs:
            if job.start is not None and not job.array_parent:
                end = job.end or self._time
                usage[job.user] += (end - job.start).total_seconds() * (job.cpus + 20 * job.gpus)
        return usage

    def _shares_text(self, now: datetime) -> str:
        base = {
            "alice": 4.1e6,
            "bob": 1.2e6,
            "carol": 2.5e6,
            "dave": 0.4e6,
            "grace": 3.3e6,
            "erin": 5.2e6,
            "frank": 0.9e6,
            WHOAMI: 1.6e6,
        }
        usage = {user: base[user] + value for user, value in self._raw_usage().items()}
        total = sum(usage.values())
        lines = [SSHARE_DELIMITER.join(["root", "", "", "1.000000", str(int(total)), "1.000000", "", ""])]
        for account, members in ACCOUNTS.items():
            account_usage = sum(usage[user] for user in members)
            eff = account_usage / total if total else 0
            norm = 1 / len(ACCOUNTS)
            level_fs = norm / eff if eff else float("inf")
            lines.append(
                SSHARE_DELIMITER.join(
                    [
                        f" {account}",
                        "",
                        "1",
                        f"{norm:.6f}",
                        str(int(account_usage)),
                        f"{eff:.6f}",
                        "",
                        f"{level_fs:.6f}",
                    ]
                )
            )
            for user in members:
                user_eff = usage[user] / account_usage if account_usage else 0
                fairshare = max(0.0, min(1.0, 1 - user_eff * 1.5))
                lines.append(
                    SSHARE_DELIMITER.join(
                        [
                            f"  {account}",
                            user,
                            "1",
                            f"{norm / len(members):.6f}",
                            str(int(usage[user])),
                            f"{user_eff:.6f}",
                            f"{fairshare:.6f}",
                            "",
                        ]
                    )
                )
        return "\n".join(lines) + "\n"

    def _sdiag_text(self, now: datetime) -> str:
        pending = sum(1 for job in self._jobs if job.is_pending)
        running = sum(1 for job in self._jobs if job.is_running)
        counters = self._counters
        return (
            "*******************************************************\n"
            f"sdiag output at {now.strftime('%a %b %d %H:%M:%S %Y')} ({int(now.timestamp())})\n"
            f"Data since      {self._started.strftime('%a %b %d %H:%M:%S %Y')} ({int(self._started.timestamp())})\n"
            "*******************************************************\n"
            "Server thread count:  3\nAgent queue size:     0\nAgent count:          0\nDBD Agent queue size: 0\n\n"
            f"Jobs submitted: {counters['submitted']}\nJobs started:   {counters['started']}\n"
            f"Jobs completed: {counters['completed']}\nJobs canceled:  {counters['canceled']}\n"
            f"Jobs failed:    {counters['failed']}\nJobs pending:   {pending}\nJobs running:   {running}\n\n"
            "Main schedule statistics (microseconds):\n\tLast cycle:   1823\n\tMax cycle:    41235\n"
            f"\tTotal cycles: {counters['submitted'] * 3}\n\tMean cycle:   2210\n\tMean depth cycle:  12\n"
            f"\tCycles per minute: 18\n\tLast queue length: {pending}\n\n"
            "Backfilling stats\n"
            f"\tTotal backfilled jobs (since last slurm start): {counters['started'] // 3}\n"
            "\tTotal backfilled jobs (since last stats cycle start): 4\n\tTotal cycles: 812\n"
            "\tLast cycle: 15234\n\tMax cycle:  98765\n\tMean cycle: 21345\n\tLast depth cycle: 23\n"
            f"\tDepth Mean: 19\n\tLast queue length: {pending}\n\tQueue length mean: 14\n"
        )

    def _history_rows(self, job: SimJob, now: datetime) -> list[str]:
        end = job.end
        elapsed = (end or now) - job.start if job.start else timedelta(0)
        state = "CANCELLED by 1000" if job.state == "CANCELLED" else job.state
        exit_code = {"FAILED": "1:0", "OUT_OF_MEMORY": "0:125"}.get(job.state, "0:0")
        total_cpu = timedelta(seconds=elapsed.total_seconds() * job.cpus * job.cpu_eff)
        job_id = job.display_id if job.array_task is not None else str(job.job_id)
        base = {
            "JobID": job_id,
            "JobIDRaw": str(job.job_id),
            "JobName": job.name,
            "Partition": job.partition,
            "Account": job.account,
            "User": job.user,
            "State": state,
            "ExitCode": exit_code,
            "Elapsed": _dur(elapsed),
            "Timelimit": _dur(job.time_limit),
            "AllocCPUS": str(job.cpus),
            "AllocTRES": self._tres_alloc(job) if job.start else "",
            "ReqMem": f"{job.mem_mb}M",
            "MaxRSS": "",
            "TotalCPU": _dur(total_cpu),
            "Submit": _ts(job.submit),
            "Start": _ts(job.start) if job.start else "Unknown",
            "End": _ts(end),
            "NodeList": job.node or "None assigned",
            "StdOut": f"{job.work_dir}/slurm-%j.out",
            "WorkDir": job.work_dir,
        }
        rows = [DELIMITER.join(base[field_name] for field_name in SACCT_HISTORY_FIELDS)]
        if job.start is not None:
            rss = int(job.mem_mb * job.mem_frac * 1024 * 1024)
            for step, step_name, step_rss in ((".batch", "batch", 12_000_000), (".0", "python", rss)):
                row = dict(
                    base,
                    JobID=job_id + step,
                    JobIDRaw=str(job.job_id) + step,
                    JobName=step_name,
                    User="",
                    ReqMem="",
                    MaxRSS=str(step_rss),
                    StdOut="",
                    WorkDir="",
                    Timelimit="",
                    State=state.split()[0],
                )
                rows.append(DELIMITER.join(row[field_name] for field_name in SACCT_HISTORY_FIELDS))
        return rows

    def _history_text(self, now: datetime) -> str:
        rows: list[str] = []
        for job in sorted(self._jobs, key=lambda job: job.job_id):
            if job.user == WHOAMI and not job.is_pending and not job.array_parent:
                rows.extend(self._history_rows(job, now))
        return "\n".join(rows) + "\n"

    def _recent_text(self, now: datetime) -> str:
        rows = [
            f"{job.user}{DELIMITER}{_ts(job.end)}"
            for job in self._jobs
            if job.start is not None and not job.array_parent
        ]
        return "\n".join(rows) + "\n"

    def _usage_text(self, now: datetime) -> str:
        rows = [
            DELIMITER.join(
                (job.account, job.partition, self._tres_alloc(job), job.node or "", _ts(job.start), _ts(job.end))
            )
            for job in self._jobs
            if job.start is not None and not job.array_parent
        ]
        return "\n".join(rows) + "\n"

    # -- actions --------------------------------------------------------------

    def _find(self, job_id: str) -> SimJob | None:
        raw = int(job_id.split("_")[0]) if job_id.split("_")[0].isdigit() else -1
        return next((job for job in self._jobs if job.job_id == raw and not job.is_done), None)

    async def hold(self, job_id: str) -> ActionResult:
        job = self._find(job_id)
        if job is None or not job.is_pending:
            return ActionResult(ok=False, command=f"scontrol hold {job_id}", output="Job is not pending")
        job.held, job.reason = True, "JobHeldUser"
        return ActionResult(ok=True, command=f"scontrol hold {job_id}", output="OK (simulated)")

    async def release(self, job_id: str) -> ActionResult:
        job = self._find(job_id)
        if job is None:
            return ActionResult(
                ok=False, command=f"scontrol release {job_id}", output=f"Invalid job id specified: {job_id}"
            )
        job.held, job.reason = False, "Priority"
        return ActionResult(ok=True, command=f"scontrol release {job_id}", output="OK (simulated)")

    async def cancel(self, job_id: str) -> ActionResult:
        job = self._find(job_id)
        if job is None:
            return ActionResult(ok=False, command=f"scancel {job_id}", output=f"Invalid job id specified: {job_id}")
        now = self._clock()
        for victim in [job, *(child for child in self._jobs if child.array_job_id == job.job_id and not child.is_done)]:
            victim.state, victim.end, victim.array_pending = "CANCELLED", now, []
            self._counters["canceled"] += 1
        return ActionResult(ok=True, command=f"scancel {job_id}", output="OK (simulated)")
