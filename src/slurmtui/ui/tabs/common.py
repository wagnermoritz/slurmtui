"""Rich renderables shared by the detail screens."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from rich import box
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from slurmtui.columns.format import Formatter
from slurmtui.data.aggregate import job_counts
from slurmtui.model.records import Job, ShareEntry
from slurmtui.slurm.parsers import hostlist
from slurmtui.units import parse_window


@dataclass
class _GroupStats:
    running: int = 0
    pending: int = 0
    cpus: int = 0
    gpus: int = 0
    mem: int = 0
    nodes: set[str] = field(default_factory=set)


def jobs_overview(
    jobs: Iterable[Job],
    formatter: Formatter,
    group_by: Callable[[Job], str],
    group_label: str,
) -> RenderableType:
    """Counts and allocated resources of a job list, plus a breakdown per group (user, partition, ...)."""
    jobs = list(jobs)
    if not jobs:
        return Text("none", style="dim")
    running, pending, other = job_counts(jobs)
    summary = Text()
    summary.append(f"running {running}", style="bold")
    summary.append(f"   pending {pending}" + (f"   other {other}" if other else ""))
    total = _GroupStats()
    groups: dict[str, _GroupStats] = {}
    for job in jobs:
        stats = groups.setdefault(group_by(job), _GroupStats())
        if job.is_pending:
            stats.pending += job.task_count
            continue
        if not job.is_running:
            continue
        for target in (stats, total):
            target.running += 1
            target.cpus += job.tres_alloc.cpu
            target.gpus += job.gpus
            target.mem += job.tres_alloc.mem
            target.nodes.update(job.node_list)
    if running:
        summary.append(f"\nallocated   {total.cpus} CPUs   {total.gpus} GPUs   {formatter.memory(total.mem)}")
        summary.append(f"   on {len(total.nodes)} node{'s' if len(total.nodes) != 1 else ''}: ")
        summary.append(hostlist.contract(sorted(total.nodes)), style="dim")
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    table.add_column(group_label)
    for column in ("Running", "Pending", "CPUs", "GPUs", "Memory", "Nodes"):
        table.add_column(column, justify="right")
    for name, stats in sorted(groups.items(), key=lambda item: (-item[1].running, -item[1].pending, item[0])):
        table.add_row(
            name,
            str(stats.running),
            str(stats.pending),
            str(stats.cpus),
            str(stats.gpus),
            formatter.memory(stats.mem),
            str(len(stats.nodes)),
        )
    return Group(summary, table)


def shares_table(entries: Iterable[ShareEntry]) -> Table | Text:
    entries = list(entries)
    if not entries:
        return Text("none", style="dim")
    table = Table(box=box.SIMPLE_HEAD, header_style="bold", pad_edge=False)
    for column in ("Account", "User", "Norm shares", "Raw usage", "Eff. usage", "FairShare", "LevelFS"):
        table.add_column(column, justify="right" if column not in ("Account", "User") else "left")
    for entry in sorted(entries, key=lambda item: (item.account, item.user or "")):
        table.add_row(
            entry.account,
            entry.user or "",
            _num(entry.norm_shares, 6),
            _num(entry.raw_usage, 0),
            _num(entry.effective_usage, 6),
            _num(entry.fairshare, 6),
            _num(entry.level_fs, 3),
        )
    return table


def _num(value: float | None, digits: int) -> str:
    if value is None:
        return "-"
    if value == float("inf"):
        return "inf"
    return f"{value:.{digits}f}"


def resolve_window(text: str, default: str, maximum: str) -> tuple[str, str | None]:
    """Validate a window input. Returns (window to use, note for the status line)."""
    stripped = text.strip()
    if not stripped:
        return default, None
    delta = parse_window(stripped)
    if delta is None:
        return default, f"could not parse window {stripped!r}, using {default}"
    limit = parse_window(maximum)
    if limit is not None and delta > limit:
        return maximum, f"window {stripped} exceeds the maximum {maximum}, using {maximum}"
    return stripped, None
