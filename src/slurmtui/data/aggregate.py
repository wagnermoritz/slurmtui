"""Pure aggregations over parsed records: users, accounts and the cluster overview."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from slurmtui.model.derive import Deriver
from slurmtui.model.records import (
    AccountRow,
    GroupOverview,
    Job,
    Node,
    RecentCounts,
    Reservation,
    ShareEntry,
    UsageBarData,
    UsageRecord,
    UserRow,
)


@dataclass
class _LiveStats:
    """Footprint of the current queue, per user or per account."""

    running: int = 0
    pending: int = 0
    other: int = 0
    cpus: int = 0
    gpus: int = 0
    mem: int = 0
    nodes: set[str] = field(default_factory=set)
    partitions: set[str] = field(default_factory=set)
    accounts: set[str] = field(default_factory=set)
    users: set[str] = field(default_factory=set)
    oldest_pending: datetime | None = None

    def add(self, job: Job) -> None:
        self.partitions.update(part.strip() for part in job.partition.split(",") if part.strip())
        self.users.add(job.user)
        if job.account:
            self.accounts.add(job.account)
        if job.is_pending:
            self.pending += job.task_count
            if job.submit_time is not None and (self.oldest_pending is None or job.submit_time < self.oldest_pending):
                self.oldest_pending = job.submit_time
        elif job.is_running:
            self.running += 1
            self.cpus += job.tres_alloc.cpu
            self.gpus += job.gpus
            self.mem += job.tres_alloc.mem
            self.nodes.update(job.node_list)
        else:
            self.other += 1


def users(
    jobs: Iterable[Job],
    shares: Iterable[ShareEntry],
    recent: dict[str, RecentCounts] | None = None,
) -> list[UserRow]:
    per_user: dict[str, _LiveStats] = {}
    for job in jobs:
        per_user.setdefault(job.user, _LiveStats()).add(job)

    # EffectvUsage is normalised within each account, so values of different
    # accounts cannot be added; raw usage can.
    usage: dict[str, float] = {}
    raw_usage: dict[str, float] = defaultdict(float)
    fairshare: dict[str, float] = {}
    for entry in shares:
        if not entry.user:
            continue
        if entry.effective_usage is not None:
            usage[entry.user] = max(usage.get(entry.user, 0.0), entry.effective_usage)
        if entry.raw_usage is not None:
            raw_usage[entry.user] += entry.raw_usage
        if entry.fairshare is not None:
            fairshare[entry.user] = max(fairshare.get(entry.user, 0.0), entry.fairshare)

    rows: list[UserRow] = []
    for user, stats in sorted(per_user.items()):
        counts = recent.get(user) if recent is not None else None
        rows.append(
            UserRow(
                user=user,
                jobs_running=stats.running,
                jobs_pending=stats.pending,
                jobs_other=stats.other,
                cpus=stats.cpus,
                gpus=stats.gpus,
                memory=stats.mem,
                nodes=tuple(sorted(stats.nodes)),
                partitions=tuple(sorted(stats.partitions)),
                accounts=tuple(sorted(stats.accounts)),
                usage=usage.get(user),
                raw_usage=raw_usage.get(user),
                fairshare=fairshare.get(user),
                jobs_24h=None if recent is None else (counts.jobs_24h if counts else 0),
                jobs_7d=None if recent is None else (counts.jobs_7d if counts else 0),
            )
        )
    return rows


def usage_hours(
    records: Iterable[UsageRecord],
    deriver: Deriver,
    window_start: datetime,
    now: datetime | None = None,
) -> dict[str, tuple[dict[str, float], dict[str, float]]]:
    """Per account: ({group: cpu_hours}, {group: gpu_hours}), clipped to the window."""
    now = now or datetime.now()
    count_cpu_for_gpu = deriver.config.usage.count_cpu_hours_of_gpu_jobs
    result: dict[str, tuple[dict[str, float], dict[str, float]]] = {}
    for record in records:
        if record.start is None:
            continue
        end = min(record.end, now) if record.end is not None else now
        hours = (end - max(record.start, window_start)).total_seconds() / 3600
        if hours <= 0:
            continue
        group = deriver.usage_group(record)
        cpu_hours, gpu_hours = result.setdefault(record.account, (defaultdict(float), defaultdict(float)))
        if deriver.is_gpu_job(record.partition, record.tres_alloc.gpu):
            gpu_hours[group] += record.tres_alloc.gpu * hours
            if count_cpu_for_gpu:
                cpu_hours[group] += record.tres_alloc.cpu * hours
        else:
            cpu_hours[group] += record.tres_alloc.cpu * hours
    return result


def accounts(
    shares: Iterable[ShareEntry],
    jobs: Iterable[Job],
    usage: dict[str, tuple[dict[str, float], dict[str, float]]] | None = None,
    now: datetime | None = None,
) -> list[AccountRow]:
    now = now or datetime.now()
    account_entries: dict[str, ShareEntry] = {}
    members: Counter[str] = Counter()
    for entry in shares:
        if entry.user:
            members[entry.account] += 1
        else:
            account_entries[entry.account] = entry

    live: dict[str, _LiveStats] = {}
    for job in jobs:
        live.setdefault(job.account, _LiveStats()).add(job)

    names = sorted(set(account_entries) | set(live))
    rows: list[AccountRow] = []
    for name in names:
        share: ShareEntry | None = account_entries.get(name)
        stats = live.get(name) or _LiveStats()
        hours = usage.get(name) if usage else None
        rows.append(
            AccountRow(
                account=name,
                shares=share.norm_shares if share else None,
                raw_usage=share.raw_usage if share else None,
                usage=share.effective_usage if share else None,
                level_fs=share.level_fs if share else None,
                fairshare=share.fairshare if share else None,
                jobs_running=stats.running,
                jobs_pending=stats.pending,
                cpus=stats.cpus,
                gpus=stats.gpus,
                memory=stats.mem,
                members=members.get(name, 0),
                members_active=len(stats.users),
                oldest_pending=(now - stats.oldest_pending) if stats.oldest_pending else None,
                cpu_hours=dict(hours[0]) if hours else {},
                gpu_hours=dict(hours[1]) if hours else {},
            )
        )
    return rows


def cluster_overview(
    nodes: Sequence[Node],
    jobs: Sequence[Job],
    reservations: Sequence[Reservation],
    group_names: Sequence[str],
    ungrouped_name: str,
) -> dict[str, GroupOverview]:
    """One overview per node group; the ungrouped group is included only when non-empty."""
    by_group: dict[str, list[Node]] = {name: [] for name in group_names}
    for node in nodes:
        by_group.setdefault(node.node_group, []).append(node)
    if ungrouped_name in by_group and not by_group[ungrouped_name]:
        del by_group[ungrouped_name]
    for name in list(by_group):
        if name not in group_names and name != ungrouped_name:
            by_group.setdefault(ungrouped_name, []).extend(by_group.pop(name))

    jobs_by_group: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        jobs_by_group[job.node_group].append(job)

    overviews: dict[str, GroupOverview] = {}
    for name, group_nodes in by_group.items():
        gpu_usage: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        cpu_usage: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        mem_used = mem_total = 0
        states: Counter[str] = Counter()
        node_set: set[str] = set()
        for node in group_nodes:
            node_set.add(node.name)
            states[node.state.compact] += 1
            if node.gpus_total:
                label = node.gpu_type or node.gpu_gres_type or "GPU"
                gpu_usage[label][0] += node.gpus_alloc
                gpu_usage[label][1] += node.gpus_total
            if node.cpus_total:
                cpu_usage[node.cpu_type or "CPU"][0] += node.cpus_alloc
                cpu_usage[node.cpu_type or "CPU"][1] += node.cpus_total
            mem_used += node.mem_alloc
            mem_total += node.mem_total
        group_jobs = jobs_by_group.get(name, [])
        running = sum(1 for job in group_jobs if job.is_running)
        pending = sum(job.task_count for job in group_jobs if job.is_pending)
        reasons: Counter[str] = Counter()
        for job in group_jobs:
            if job.is_pending:
                reasons[job.reason or "-"] += job.task_count
        group_reservations = [res for res in reservations if node_set.intersection(res.nodes)]
        overviews[name] = GroupOverview(
            group=name,
            gpus=[UsageBarData(label, used, total) for label, (used, total) in sorted(gpu_usage.items())],
            cpus=[UsageBarData(label, used, total) for label, (used, total) in sorted(cpu_usage.items())],
            memory=UsageBarData("memory", mem_used, mem_total),
            node_states=dict(states.most_common()),
            node_total=len(group_nodes),
            running=running,
            pending=pending,
            pending_reasons=reasons.most_common(),
            reservations=group_reservations,
        )
    return overviews


def jobs_on_node(jobs: Iterable[Job], node: str) -> list[Job]:
    return [job for job in jobs if node in job.node_list]


def running_jobs_per_node(jobs: Iterable[Job]) -> Counter[str]:
    """Number of running jobs on each node (a multi-node job counts once per node)."""
    counts: Counter[str] = Counter()
    for job in jobs:
        if job.is_running:
            counts.update(job.node_list)
    return counts


def with_job_counts(nodes: Iterable[Node], jobs: Iterable[Job]) -> list[Node]:
    counts = running_jobs_per_node(jobs)
    return [replace(node, jobs_running=counts.get(node.name, 0)) for node in nodes]


def jobs_of_user(jobs: Iterable[Job], user: str) -> list[Job]:
    return [job for job in jobs if job.user == user]


def jobs_of_account(jobs: Iterable[Job], account: str) -> list[Job]:
    return [job for job in jobs if job.account == account]


def job_counts(jobs: Iterable[Job]) -> tuple[int, int, int]:
    """(running, pending tasks, other) over a job list."""
    running = pending = other = 0
    for job in jobs:
        if job.is_running:
            running += 1
        elif job.is_pending:
            pending += job.task_count
        else:
            other += 1
    return running, pending, other


def oldest_pending_age(jobs: Iterable[Job], now: datetime | None = None) -> timedelta | None:
    now = now or datetime.now()
    submits = [job.submit_time for job in jobs if job.is_pending and job.submit_time is not None]
    return (now - min(submits)) if submits else None
