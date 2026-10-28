"""Parse ``sacct -P -n`` output for the history, recent-job and usage queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from slurmtui.model.records import JobRecord, RecentCounts, UsageRecord
from slurmtui.slurm.commands import SACCT_HISTORY_FIELDS, SACCT_RECENT_FIELDS, SACCT_USAGE_FIELDS
from slurmtui.slurm.parsers import hostlist
from slurmtui.slurm.parsers.common import is_null, parse_tres, split_delimited
from slurmtui.units import parse_duration, parse_memory, parse_timestamp


def _int(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        return 0


def _req_mem(text: str, cpus: int, nodes: int) -> int | None:
    """ReqMem is total memory in recent Slurm; older versions suffix ``c``/``n``."""
    if is_null(text):
        return None
    stripped = text.strip()
    suffix = stripped[-1:]
    value = parse_memory(stripped.rstrip("cnCN"))
    if value is None:
        return None
    if suffix in "cC":
        return value * max(cpus, 1)
    if suffix in "nN":
        return value * max(nodes, 1)
    return value


def _clean_state(state: str) -> str:
    return state.split()[0].upper() if state.strip() else ""


def parse_history(text: str, max_rss_unit: str = "auto") -> list[JobRecord]:
    """One record per job; MaxRSS is the maximum over the job's steps.

    ``max_rss_unit`` applies to a MaxRSS printed without suffix; ``auto`` means bytes,
    which is what ``sacct --noconvert`` prints. Suffixed values (``83548K`` from older
    releases) keep their unit.
    """
    bare_unit = "B" if max_rss_unit == "auto" else max_rss_unit
    jobs: dict[str, JobRecord] = {}
    order: list[str] = []
    max_rss: dict[str, int] = {}
    for cells in split_delimited(text):
        if len(cells) < len(SACCT_HISTORY_FIELDS):
            continue
        fields = dict(zip(SACCT_HISTORY_FIELDS, cells))
        job_id = fields["JobID"]
        parent = job_id.split(".")[0]
        rss = parse_memory(fields["MaxRSS"], default_unit=bare_unit)
        if rss:
            max_rss[parent] = max(max_rss.get(parent, 0), rss)
        if "." in job_id:
            continue
        tres = parse_tres(fields["AllocTRES"])
        cpus = _int(fields["AllocCPUS"]) or tres.cpu
        node_list = tuple(hostlist.expand(fields["NodeList"])) if fields["NodeList"] != "None assigned" else ()
        nodes = tres.node or len(node_list)
        jobs[parent] = JobRecord(
            job_id=job_id,
            raw_id=fields["JobIDRaw"],
            name=fields["JobName"],
            partition=fields["Partition"],
            account=fields["Account"],
            user=fields["User"],
            state=_clean_state(fields["State"]),
            exit_code=fields["ExitCode"],
            elapsed=parse_duration(fields["Elapsed"]),
            time_limit=parse_duration(fields["Timelimit"]),
            alloc_cpus=cpus,
            tres_alloc=tres,
            req_mem=_req_mem(fields["ReqMem"], cpus, nodes),
            max_rss=None,
            total_cpu=parse_duration(fields["TotalCPU"]),
            submit=parse_timestamp(fields["Submit"]),
            start=parse_timestamp(fields["Start"]),
            end=parse_timestamp(fields["End"]),
            node_list=node_list,
            stdout=None if is_null(fields["StdOut"]) else fields["StdOut"],
            work_dir=None if is_null(fields["WorkDir"]) else fields["WorkDir"],
        )
        order.append(parent)
    from dataclasses import replace

    return [replace(jobs[key], max_rss=max_rss.get(key)) for key in order]


def parse_recent_counts(text: str, now: datetime | None = None) -> dict[str, RecentCounts]:
    now = now or datetime.now()
    cutoff = now - timedelta(hours=24)
    counts: dict[str, list[int]] = {}
    for cells in split_delimited(text):
        if len(cells) < len(SACCT_RECENT_FIELDS):
            continue
        user, end = cells[0], cells[1]
        if not user:
            continue
        entry = counts.setdefault(user, [0, 0])
        entry[1] += 1
        end_time = parse_timestamp(end)
        if end_time is None or end_time >= cutoff:
            entry[0] += 1
    return {user: RecentCounts(jobs_24h=values[0], jobs_7d=values[1]) for user, values in counts.items()}


def parse_usage(text: str) -> list[UsageRecord]:
    records: list[UsageRecord] = []
    for cells in split_delimited(text):
        if len(cells) < len(SACCT_USAGE_FIELDS):
            continue
        account, partition, tres, node_list, start, end = cells[: len(SACCT_USAGE_FIELDS)]
        if not account:
            continue
        records.append(
            UsageRecord(
                account=account,
                partition=partition,
                tres_alloc=parse_tres(tres),
                node_list=tuple(hostlist.expand(node_list)) if node_list != "None assigned" else (),
                start=parse_timestamp(start),
                end=parse_timestamp(end),
            )
        )
    return records
