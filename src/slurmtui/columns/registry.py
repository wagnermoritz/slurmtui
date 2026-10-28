"""Column definitions per entity and resolution of the configured column lists."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from slurmtui.config.schema import TABLE_TABS, ColumnSpec, Config
from slurmtui.model.records import AccountRow, Job, JobRecord, Node, UserRow

ColumnType = Literal[
    "str",
    "int",
    "float",
    "bytes",
    "duration",
    "datetime",
    "percent",
    "fraction",
    "bytes_fraction",
    "nodelist",
    "list",
    "node_state",
    "job_state",
    "avail",
    "jobid",
]

RIGHT_ALIGNED: frozenset[str] = frozenset(
    {"int", "float", "bytes", "duration", "percent", "fraction", "bytes_fraction", "jobid"}
)


@dataclass(frozen=True)
class ColumnDef:
    key: str
    label: str
    type: ColumnType
    getter: Callable[[Any], Any]
    description: str = ""
    align: Literal["left", "right"] | None = None
    width: int | None = None
    max_len: int | None = None
    digits: int = 2
    requires_source: str | None = None

    @property
    def alignment(self) -> Literal["left", "right"]:
        if self.align is not None:
            return self.align
        return "right" if self.type in RIGHT_ALIGNED else "left"


def _col(
    key: str,
    label: str,
    type_: ColumnType,
    getter: Callable[[Any], Any],
    description: str,
    **kwargs: Any,
) -> ColumnDef:
    return ColumnDef(key=key, label=label, type=type_, getter=getter, description=description, **kwargs)


NODE_COLUMNS: dict[str, ColumnDef] = {
    column.key: column
    for column in (
        _col("name", "Node", "str", lambda n: n.name, "node name"),
        _col("jobs", "Jobs", "int", lambda n: n.jobs_running, "running jobs on the node"),
        _col(
            "state",
            "State",
            "node_state",
            lambda n: n.state,
            "compact state as sinfo shows it (idle~, mix, drng)",
        ),
        _col(
            "state_long",
            "State",
            "str",
            lambda n: n.state.long,
            "full state with flags (IDLE+CLOUD+POWERED_DOWN)",
        ),
        _col("avail", "Avail", "avail", lambda n: n.avail, "up when every partition of the node is UP"),
        _col("partitions", "Partitions", "list", lambda n: n.partitions, "partitions the node belongs to"),
        _col("node_group", "Group", "str", lambda n: n.node_group, "node group from [[node_groups]]"),
        _col("cpus", "CPUs", "fraction", lambda n: (n.cpus_alloc, n.cpus_total), "allocated/total CPUs"),
        _col("cpus_alloc", "CPU alloc", "int", lambda n: n.cpus_alloc, "allocated CPUs"),
        _col("cpus_total", "CPU total", "int", lambda n: n.cpus_total, "total CPUs"),
        _col("cpu_load", "Load", "float", lambda n: n.cpu_load, "CPU load average", digits=1),
        _col("cpu_type", "CPU type", "str", lambda n: n.cpu_type, "CPU type from [hardware.cpu_type]"),
        _col(
            "memory",
            "Memory",
            "bytes_fraction",
            lambda n: (n.mem_alloc, n.mem_total),
            "allocated/total memory",
        ),
        _col("mem_alloc", "Mem alloc", "bytes", lambda n: n.mem_alloc, "allocated memory"),
        _col("mem_total", "Mem total", "bytes", lambda n: n.mem_total, "total memory"),
        _col("mem_free", "Mem free", "bytes", lambda n: n.mem_free, "free memory reported by the node"),
        _col("gpus", "GPUs", "fraction", lambda n: (n.gpus_alloc, n.gpus_total), "allocated/total GPUs"),
        _col("gpus_alloc", "GPU alloc", "int", lambda n: n.gpus_alloc, "allocated GPUs"),
        _col("gpus_total", "GPU total", "int", lambda n: n.gpus_total, "total GPUs"),
        _col("gpu_type", "GPU type", "str", lambda n: n.gpu_type, "GPU type from [hardware.gpu_type]"),
        _col("gpu_gres", "Gres", "str", lambda n: n.gpu_gres, "raw Gres string"),
        _col("features", "Features", "list", lambda n: n.features, "active features"),
        _col(
            "max_time",
            "Max time",
            "duration",
            lambda n: n.max_time,
            "largest MaxTime of the node's partitions",
        ),
        _col("reason", "Reason", "str", lambda n: n.reason.text if n.reason else None, "drain/down reason"),
        _col(
            "reason_user",
            "Set by",
            "str",
            lambda n: n.reason.user if n.reason else None,
            "who set the reason",
        ),
        _col("reason_time", "Reason time", "datetime", lambda n: n.reason.time if n.reason else None, "when"),
    )
}

JOB_COLUMNS: dict[str, ColumnDef] = {
    column.key: column
    for column in (
        _col("job_id", "Job ID", "jobid", lambda j: j.job_id, "job id, arrays as 123_[1-10]"),
        _col("array_tasks", "Tasks", "int", lambda j: j.task_count, "array tasks represented by the row"),
        _col("partition", "Partition", "str", lambda j: j.partition, "partition(s)"),
        _col("name", "Name", "str", lambda j: j.name, "job name", max_len=40),
        _col("user", "User", "str", lambda j: j.user, "owner"),
        _col("account", "Account", "str", lambda j: j.account, "account charged"),
        _col("qos", "QOS", "str", lambda j: j.qos, "quality of service"),
        _col("state", "State", "job_state", lambda j: j.state, "RUNNING, PENDING, ..."),
        _col("reason", "Reason", "str", lambda j: j.reason, "pending reason"),
        _col("time", "Time", "duration", lambda j: j.time_used, "time used"),
        _col("time_limit", "Limit", "duration", lambda j: j.time_limit, "time limit"),
        _col("time_left", "Left", "duration", lambda j: j.time_left, "time left"),
        _col("submit_time", "Submitted", "datetime", lambda j: j.submit_time, "submit time"),
        _col(
            "start_time",
            "Start",
            "datetime",
            lambda j: j.start_time,
            "start time (estimated for pending jobs)",
        ),
        _col("nodes", "Nodes", "int", lambda j: j.num_nodes, "number of nodes"),
        _col("cpus", "CPUs", "int", lambda j: j.cpus, "CPUs"),
        _col("tasks", "NTasks", "int", lambda j: j.tasks, "tasks"),
        _col("gpus", "GPUs", "int", lambda j: j.gpus, "allocated GPUs, requested for pending jobs"),
        _col("memory", "Memory", "bytes", lambda j: j.memory, "allocated memory, requested for pending jobs"),
        _col("priority", "Priority", "int", lambda j: j.priority, "scheduling priority"),
        _col("node_list", "Node list", "nodelist", lambda j: j.node_list, "allocated nodes", max_len=40),
        _col("sched_nodes", "Planned", "nodelist", lambda j: j.sched_nodes, "nodes planned by the backfill"),
        _col("node_group", "Group", "str", lambda j: j.node_group, "node group"),
        _col("dependency", "Dependency", "str", lambda j: j.dependency, "dependency specification"),
        _col("work_dir", "Work dir", "str", lambda j: j.work_dir, "working directory", max_len=60),
        _col("stdout", "Stdout", "str", lambda j: j.stdout, "stdout file", max_len=60),
        _col("command", "Command", "str", lambda j: j.command, "batch script", max_len=60),
    )
}

USER_COLUMNS: dict[str, ColumnDef] = {
    column.key: column
    for column in (
        _col("user", "User", "str", lambda u: u.user, "user name"),
        _col("jobs_running", "Running", "int", lambda u: u.jobs_running, "running jobs"),
        _col("jobs_pending", "Pending", "int", lambda u: u.jobs_pending, "pending jobs (array tasks counted)"),
        _col("jobs_other", "Other", "int", lambda u: u.jobs_other, "jobs in other states"),
        _col("cpus", "CPUs", "int", lambda u: u.cpus, "allocated CPUs"),
        _col("gpus", "GPUs", "int", lambda u: u.gpus, "allocated GPUs"),
        _col("memory", "Memory", "bytes", lambda u: u.memory, "allocated memory"),
        _col("nodes", "Nodes", "nodelist", lambda u: u.nodes, "occupied nodes", max_len=40),
        _col("partitions", "Partitions", "list", lambda u: u.partitions, "partitions with jobs"),
        _col("accounts", "Accounts", "list", lambda u: u.accounts, "accounts with jobs"),
        _col(
            "raw_usage",
            "Raw usage",
            "float",
            lambda u: u.raw_usage,
            "raw usage summed over the user's accounts",
            digits=0,
        ),
        _col(
            "usage",
            "Usage",
            "float",
            lambda u: u.usage,
            "effective usage within the account (largest if the user has several)",
            digits=6,
        ),
        _col("fairshare", "FairShare", "float", lambda u: u.fairshare, "best fairshare factor", digits=6),
        _col(
            "jobs_24h",
            "24h",
            "int",
            lambda u: u.jobs_24h,
            "jobs in the last 24 hours",
            requires_source="recent_jobs",
        ),
        _col(
            "jobs_7d",
            "7d",
            "int",
            lambda u: u.jobs_7d,
            "jobs in the last 7 days",
            requires_source="recent_jobs",
        ),
    )
}

ACCOUNT_COLUMNS: dict[str, ColumnDef] = {
    column.key: column
    for column in (
        _col("account", "Account", "str", lambda a: a.account, "account name"),
        _col("shares", "Shares", "float", lambda a: a.shares, "normalised shares", digits=4),
        _col("raw_usage", "Raw usage", "float", lambda a: a.raw_usage, "raw usage", digits=0),
        _col("usage", "Usage", "float", lambda a: a.usage, "effective usage", digits=6),
        _col("level_fs", "LevelFS", "float", lambda a: a.level_fs, "level fairshare (>1: under-used)", digits=3),
        _col("fairshare", "FairShare", "float", lambda a: a.fairshare, "fairshare factor", digits=6),
        _col("jobs_running", "Running", "int", lambda a: a.jobs_running, "running jobs"),
        _col("jobs_pending", "Pending", "int", lambda a: a.jobs_pending, "pending jobs (array tasks counted)"),
        _col("cpus", "CPUs", "int", lambda a: a.cpus, "allocated CPUs"),
        _col("gpus", "GPUs", "int", lambda a: a.gpus, "allocated GPUs"),
        _col("memory", "Memory", "bytes", lambda a: a.memory, "allocated memory"),
        _col("members", "Members", "int", lambda a: a.members, "users in the account"),
        _col(
            "members_active",
            "Active",
            "fraction",
            lambda a: (a.members_active, a.members),
            "users with a job in the queue / users with an association in the account",
        ),
        _col(
            "oldest_pending",
            "Oldest PD",
            "duration",
            lambda a: a.oldest_pending,
            "age of the oldest pending job",
        ),
    )
}

HISTORY_COLUMNS: dict[str, ColumnDef] = {
    column.key: column
    for column in (
        _col("job_id", "Job ID", "jobid", lambda r: r.job_id, "job id"),
        _col("name", "Name", "str", lambda r: r.name, "job name", max_len=40),
        _col("partition", "Partition", "str", lambda r: r.partition, "partition"),
        _col("account", "Account", "str", lambda r: r.account, "account"),
        _col("state", "State", "job_state", lambda r: r.state, "final state"),
        _col("exit_code", "Exit", "str", lambda r: r.exit_code, "exit code:signal"),
        _col("elapsed", "Elapsed", "duration", lambda r: r.elapsed, "wall time"),
        _col("time_limit", "Limit", "duration", lambda r: r.time_limit, "time limit"),
        _col("cpus", "CPUs", "int", lambda r: r.alloc_cpus, "allocated CPUs"),
        _col("gpus", "GPUs", "int", lambda r: r.gpus, "allocated GPUs"),
        _col("req_mem", "Req mem", "bytes", lambda r: r.req_mem, "requested memory"),
        _col("max_rss", "Max RSS", "bytes", lambda r: r.max_rss, "peak memory over the steps"),
        _col("mem_eff", "Mem eff", "percent", lambda r: r.mem_eff, "max_rss / req_mem"),
        _col("cpu_eff", "CPU eff", "percent", lambda r: r.cpu_eff, "total CPU time / (elapsed x CPUs)"),
        _col("submit", "Submitted", "datetime", lambda r: r.submit, "submit time"),
        _col("start", "Start", "datetime", lambda r: r.start, "start time"),
        _col("end", "End", "datetime", lambda r: r.end, "end time"),
        _col("node_list", "Node list", "nodelist", lambda r: r.node_list, "nodes", max_len=40),
        _col("work_dir", "Work dir", "str", lambda r: r.work_dir, "working directory", max_len=60),
        _col("stdout", "Stdout", "str", lambda r: r.stdout, "stdout file pattern", max_len=60),
    )
}

REGISTRIES: dict[str, dict[str, ColumnDef]] = {
    "nodes": NODE_COLUMNS,
    "jobs": JOB_COLUMNS,
    "users": USER_COLUMNS,
    "accounts": ACCOUNT_COLUMNS,
    "history": HISTORY_COLUMNS,
}

ENTITY_TYPES: dict[str, type] = {
    "nodes": Node,
    "jobs": Job,
    "users": UserRow,
    "accounts": AccountRow,
    "history": JobRecord,
}

USAGE_PREFIXES = ("cpu_hours", "gpu_hours")


def _usage_column(prefix: str, group: str) -> ColumnDef:
    unit = "CPU" if prefix == "cpu_hours" else "GPU"

    def getter(row: Any, _attr: str = prefix, _group: str = group) -> float:
        hours: dict[str, float] = getattr(row, _attr)
        return hours.get(_group, 0.0)

    return ColumnDef(
        key=f"{prefix}:{group}",
        label=f"{group} {unit}h",
        type="float",
        getter=getter,
        description=f"{unit} hours of account jobs in node group {group} within the usage window",
        digits=0,
        requires_source="account_usage",
    )


def registry_for(tab: str, config: Config | None = None) -> dict[str, ColumnDef]:
    """Registered columns of a tab, including the per-group usage columns of ACCOUNTS."""
    base = REGISTRIES[tab]
    if tab != "accounts" or config is None:
        return base
    extended = dict(base)
    for group in [*config.group_names, config.ungrouped_name]:
        for prefix in USAGE_PREFIXES:
            column = _usage_column(prefix, group)
            extended[column.key] = column
    return extended


def _expand_specs(specs: list[ColumnSpec], config: Config) -> list[ColumnSpec]:
    expanded: list[ColumnSpec] = []
    for spec in specs:
        prefix, _, group = spec.key.partition(":")
        if prefix in USAGE_PREFIXES and group == "*":
            expanded.extend(spec.model_copy(update={"key": f"{prefix}:{name}"}) for name in config.group_names)
        else:
            expanded.append(spec)
    return expanded


def resolve_columns(config: Config, tab: str) -> list[ColumnDef]:
    """The configured columns of a tab with overrides applied. Unknown keys raise KeyError."""
    registry = registry_for(tab, config)
    resolved: list[ColumnDef] = []
    for spec in _expand_specs(list(config.table_tab(tab).columns), config):
        column = registry[spec.key]
        updates: dict[str, Any] = {}
        if spec.label is not None:
            updates["label"] = spec.label
        if spec.width is not None:
            updates["width"] = spec.width
        if spec.max_len is not None:
            updates["max_len"] = spec.max_len
        if spec.align is not None:
            updates["align"] = spec.align
        resolved.append(replace(column, **updates) if updates else column)
    return resolved


def validate_config_columns(config: Config) -> list[str]:
    """Human-readable errors for unknown column keys and columns whose source is disabled."""
    errors: list[str] = []
    for tab in TABLE_TABS:
        registry = registry_for(tab, config)
        for spec in _expand_specs(list(config.table_tab(tab).columns), config):
            column = registry.get(spec.key)
            if column is None:
                known = ", ".join(sorted(registry))
                errors.append(f"tabs.{tab}.columns: unknown column {spec.key!r} (known: {known})")
                continue
            if column.requires_source and not getattr(config.sources, column.requires_source).enabled:
                source = column.requires_source
                errors.append(f"tabs.{tab}.columns: column {spec.key!r} needs sources.{source}.enabled = true")
    return errors
