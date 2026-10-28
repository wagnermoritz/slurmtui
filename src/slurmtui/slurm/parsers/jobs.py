"""Parse ``squeue -O`` output with the field list from :mod:`slurmtui.slurm.commands`."""

from __future__ import annotations

from slurmtui.model.records import Job
from slurmtui.model.tres import TRES
from slurmtui.slurm.commands import DELIMITER, SQUEUE_FIELD_NAMES
from slurmtui.slurm.parsers import hostlist
from slurmtui.slurm.parsers.common import array_task_count, gpu_request, is_null, parse_tres
from slurmtui.units import parse_duration, parse_memory, parse_timestamp


def _int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _opt(value: str | None) -> str | None:
    return None if is_null(value) else value


def _min_memory(text: str | None, cpus: int, nodes: int) -> int | None:
    """MinMemory is per CPU (``c`` suffix) or per node (``n`` or none)."""
    if is_null(text):
        return None
    assert text is not None
    stripped = text.strip()
    per_cpu = stripped.endswith(("c", "C"))
    value = parse_memory(stripped.rstrip("cnCN"))
    if value is None:
        return None
    if per_cpu:
        return value * max(cpus, 1)
    return value * max(nodes, 1)


def _requested_gpus(per_job: str | None, per_node: str | None, per_task: str | None, nodes: int, tasks: int) -> int:
    """GPUs a job asked for.

    ``--gpus`` (per job), else ``--gres``/``--gpus-per-node`` times nodes, else ``--gpus-per-task`` times tasks.
    """
    if gpus := gpu_request(per_job):
        return gpus
    if gpus := gpu_request(per_node):
        return gpus * max(nodes, 1)
    if gpus := gpu_request(per_task):
        return gpus * max(tasks, 1)
    return 0


def job_from_fields(fields: dict[str, str]) -> Job:
    job_id = fields.get("JobArrayID") or fields.get("JobID", "")
    num_nodes = _int(fields.get("NumNodes"))
    cpus = _int(fields.get("NumCPUs"))
    tasks = _int(fields.get("NumTasks"))
    tres_alloc: TRES = parse_tres(fields.get("tres-alloc"))
    array_job = fields.get("ArrayJobID")
    array_task = fields.get("ArrayTaskID")
    return Job(
        job_id=job_id,
        raw_id=_int(fields.get("JobID")),
        array_job_id=None if is_null(array_job) else _int(array_job),
        array_task=None if is_null(array_task) else array_task,
        task_count=array_task_count(job_id),
        partition=fields.get("Partition", ""),
        name=fields.get("Name", ""),
        user=fields.get("UserName", ""),
        account=fields.get("Account", ""),
        qos=fields.get("QOS", ""),
        state=fields.get("State", "").upper(),
        reason="" if is_null(fields.get("Reason")) else fields.get("Reason", ""),
        time_used=parse_duration(fields.get("TimeUsed")),
        time_limit=parse_duration(fields.get("TimeLimit")),
        submit_time=parse_timestamp(fields.get("SubmitTime")),
        start_time=parse_timestamp(fields.get("StartTime")),
        num_nodes=num_nodes,
        cpus=cpus,
        tasks=tasks,
        mem_requested=_min_memory(fields.get("MinMemory"), cpus, num_nodes),
        tres_alloc=tres_alloc,
        gpus_requested=_requested_gpus(
            fields.get("tres-per-job"), fields.get("tres-per-node"), fields.get("tres-per-task"), num_nodes, tasks
        ),
        node_list=tuple(hostlist.expand(fields.get("NodeList"))),
        sched_nodes=tuple(hostlist.expand(fields.get("SchedNodes"))),
        priority=_int(fields.get("PriorityLong")),
        dependency=_opt(fields.get("Dependency")),
        work_dir=fields.get("WorkDir", ""),
        stdout=_opt(fields.get("StdOut")),
        stderr=_opt(fields.get("StdErr")),
        command=_opt(fields.get("Command")),
    )


def parse_jobs(text: str, field_names: tuple[str, ...] = SQUEUE_FIELD_NAMES) -> list[Job]:
    jobs: list[Job] = []
    expected = len(field_names)
    for line in text.splitlines():
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split(DELIMITER)]
        if len(cells) < expected:
            continue
        fields = dict(zip(field_names, cells[:expected]))
        if not fields.get("JobID"):
            continue
        jobs.append(job_from_fields(fields))
    return jobs
