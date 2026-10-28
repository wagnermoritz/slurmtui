"""Shared parsing helpers: delimited rows, ``Key=Value`` lines, TRES and GRES strings."""

from __future__ import annotations

import re
from dataclasses import dataclass

from slurmtui.model.tres import TRES
from slurmtui.slurm.commands import DELIMITER
from slurmtui.units import parse_memory

NULL_VALUES = {"", "(null)", "n/a", "none", "null", "unknown"}

_KEY_RE = re.compile(r"(?:^|\s)([A-Z][\w:/.\-]*)=")


def is_null(value: str | None) -> bool:
    if not value:
        return True
    if value in _NULL_FAST:
        return True
    return value.strip().lower() in NULL_VALUES


_NULL_FAST = frozenset({"(null)", "N/A", "None", "none", "n/a", "Unknown", "(NULL)"})


def parse_kv_line(line: str) -> dict[str, str]:
    """Parse one ``scontrol show ... -o`` line into a dict.

    Values may contain spaces (``Reason=Not responding [root@...]``), so a value
    extends to the next ``<whitespace>Key=``. Keys start with a capital letter,
    which excludes ``key=value`` fragments inside free text (``Reason=GPU xid=79 error``).
    """
    result: dict[str, str] = {}
    matches = list(_KEY_RE.finditer(line))
    for index, match in enumerate(matches):
        key = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        result[key] = line[start:end].strip()
    return result


def parse_kv_blocks(text: str, first_key: str) -> list[dict[str, str]]:
    """Parse multi-line ``scontrol show`` output into one dict per record."""
    records: list[dict[str, str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith(f"{first_key}=") and current:
            records.append(parse_kv_line(" ".join(current)))
            current = []
        if line.strip():
            current.append(line.strip())
    if current:
        records.append(parse_kv_line(" ".join(current)))
    return [record for record in records if first_key in record]


def split_delimited(text: str, delimiter: str = DELIMITER) -> list[list[str]]:
    """Split delimited output into stripped cells; blank lines are dropped."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        rows.append([cell.strip() for cell in line.split(delimiter)])
    return rows


def parse_tres(text: str | None) -> TRES:
    if is_null(text):
        return TRES()
    assert text is not None
    cpu = mem = node = billing = gpu = 0
    gpu_types: dict[str, int] = {}
    other: dict[str, str] = {}
    for item in text.split(","):
        if "=" not in item:
            continue
        key, _, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if key == "cpu":
            cpu = _to_int(value)
        elif key == "mem":
            mem = parse_memory(value) or 0
        elif key == "node":
            node = _to_int(value)
        elif key == "billing":
            billing = _to_int(value)
        elif key == "gres/gpu":
            gpu = _to_int(value)
        elif key.startswith("gres/gpu:"):
            gpu_types[key[len("gres/gpu:") :]] = _to_int(value)
        else:
            other[key] = value
    if not gpu and gpu_types:
        gpu = sum(gpu_types.values())
    return TRES(cpu=cpu, mem=mem, node=node, billing=billing, gpu=gpu, gpu_types=gpu_types, other=other)


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        return 0


@dataclass(frozen=True)
class GresEntry:
    name: str
    type: str | None
    count: int


_PAREN_RE = re.compile(r"\([^)]*\)")


def parse_gres(text: str | None) -> list[GresEntry]:
    """Parse ``gpu:a40:4(S:0-1),gpu:h100-cloud:1`` into entries. ``(null)`` gives []."""
    if is_null(text):
        return []
    assert text is not None
    entries: list[GresEntry] = []
    for item in _PAREN_RE.sub("", text).split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        name = parts[0]
        gres_type: str | None = None
        count = 1
        if len(parts) == 2:
            if parts[1].isdigit():
                count = int(parts[1])
            else:
                gres_type = parts[1]
        elif len(parts) >= 3:
            gres_type = parts[1]
            count = _to_int(parts[2].rstrip("KMG"))
            if parts[2][-1:] in "KMG" and parts[2][:-1].isdigit():
                count = int(parts[2][:-1]) * {"K": 1024, "M": 1024**2, "G": 1024**3}[parts[2][-1]]
        entries.append(GresEntry(name=name, type=gres_type, count=count))
    return entries


def gpu_request(text: str | None) -> int:
    """GPUs in a ``tres-per-*`` request string.

    Accepts the GRES form squeue prints (``gres/gpu:2``, ``gres/gpu:a40:2``,
    ``gres:gpu:2`` on old releases) and the TRES form (``gres/gpu=2``).
    A type without a count (``gres/gpu:a40``) means one.
    """
    if is_null(text):
        return 0
    assert text is not None
    total = 0
    for item in text.split(","):
        item = item.strip()
        if "=" in item:
            key, _, value = item.partition("=")
            if key == "gres/gpu" or key.startswith("gres/gpu:"):
                total += _to_int(value)
            continue
        for prefix in ("gres/", "gres:"):
            if item.startswith(prefix):
                item = item[len(prefix) :]
                break
        parts = item.split(":")
        if parts[0] != "gpu":
            continue
        total += int(parts[-1]) if len(parts) > 1 and parts[-1].isdigit() else 1
    return total


def gpu_count(entries: list[GresEntry]) -> int:
    return sum(entry.count for entry in entries if entry.name == "gpu")


def gpu_gres_type(entries: list[GresEntry]) -> str | None:
    gpus = [entry for entry in entries if entry.name == "gpu" and entry.type]
    if not gpus:
        return None
    return max(gpus, key=lambda entry: entry.count).type


_ARRAY_RANGE_RE = re.compile(r"\[(.*?)\]")


def array_task_count(job_id: str) -> int:
    """Number of tasks represented by a job id like ``123_[1-10,20%4]``; 1 for anything else."""
    match = _ARRAY_RANGE_RE.search(job_id)
    if match is None:
        return 1
    spec = match.group(1).split("%")[0]
    total = 0
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit():
                total += int(end) - int(start) + 1
        elif part.isdigit():
            total += 1
    return max(total, 1)
