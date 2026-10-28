"""Resolve the output file of a job: sbatch filename patterns (``%j``, ``%A``, ``%a``, ...)."""

from __future__ import annotations

import re
from typing import Any

NO_ARRAY_TASK = "4294967294"
"""What Slurm substitutes for ``%a`` outside job arrays."""

_STDOUT_RE = re.compile(r"(?:^|\s)StdOut=(\S+)", re.MULTILINE)


def expand_output_pattern(path: str, job: Any) -> str:
    """Fill the sbatch ``--output`` patterns in a path squeue or sacct reports as submitted.

    Works for a :class:`~slurmtui.model.records.Job` and a
    :class:`~slurmtui.model.records.JobRecord`; ids, name, user and first node
    come from whichever attributes the record has.
    """
    job_id = str(getattr(job, "job_id", "") or "")
    raw_id = str(getattr(job, "raw_id", "") or job_id.partition("_")[0])
    array_job = getattr(job, "array_job_id", None)
    array_task = getattr(job, "array_task", None)
    if "_" in job_id:
        master, _, index = job_id.partition("_")
        array_job = master if array_job is None else array_job
        array_task = index if array_task is None else array_task
    node_list = getattr(job, "node_list", ()) or ()
    first_node = str(node_list[0]) if node_list else ""
    replacements = (
        ("%%", "\x00"),
        ("%x", str(getattr(job, "name", "") or "")),
        ("%u", str(getattr(job, "user", "") or "")),
        ("%j", raw_id),
        ("%J", raw_id),
        ("%A", str(array_job) if array_job is not None else raw_id),
        ("%a", str(array_task) if array_task is not None else NO_ARRAY_TASK),
        ("%N", first_node),
        ("%n", "0"),
        ("%t", "0"),
    )
    for pattern, value in replacements:
        path = path.replace(pattern, value)
    return path.replace("\x00", "%")


def stdout_from_detail(text: str) -> str | None:
    """The ``StdOut=`` path from ``scontrol show job`` output, which Slurm prints expanded."""
    match = _STDOUT_RE.search(text)
    if match is None:
        return None
    value = match.group(1)
    if not value or "%" in value or value.lower() in {"(null)", "none", "n/a"}:
        return None
    return value
