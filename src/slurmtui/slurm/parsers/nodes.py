"""Parse ``scontrol -d -o show node`` output."""

from __future__ import annotations

import re

from slurmtui.model.records import Node, NodeReason
from slurmtui.model.states import NodeState
from slurmtui.slurm.parsers.common import (
    gpu_count,
    gpu_gres_type,
    is_null,
    parse_gres,
    parse_kv_line,
    parse_tres,
)
from slurmtui.units import parse_memory, parse_timestamp

_REASON_RE = re.compile(r"^(?P<text>.*?)\s*\[(?P<user>[^@\]]+)@(?P<time>[^\]]+)\]\s*$")


def parse_reason(text: str | None) -> NodeReason | None:
    if is_null(text):
        return None
    assert text is not None
    match = _REASON_RE.match(text)
    if match is None:
        return NodeReason(text=text.strip())
    return NodeReason(
        text=match.group("text").strip(), user=match.group("user"), time=parse_timestamp(match.group("time"))
    )


def _int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _float(value: str | None) -> float | None:
    if value is None or is_null(value):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _csv(value: str | None) -> tuple[str, ...]:
    if is_null(value):
        return ()
    assert value is not None
    return tuple(item.strip() for item in value.split(",") if item.strip())


def node_from_fields(fields: dict[str, str]) -> Node:
    gres_entries = parse_gres(fields.get("Gres"))
    cfg_tres = parse_tres(fields.get("CfgTRES"))
    alloc_tres = parse_tres(fields.get("AllocTRES"))
    gpus_total = cfg_tres.gpu or gpu_count(gres_entries)
    # AllocTRES has GPUs only when AccountingStorageTRES includes gres/gpu;
    # GresUsed (printed with -d) is maintained by slurmctld regardless.
    gpus_alloc = alloc_tres.gpu or gpu_count(parse_gres(fields.get("GresUsed")))
    gres_type = cfg_tres.gpu_type or gpu_gres_type(gres_entries)
    mem_total = parse_memory(fields.get("RealMemory")) or cfg_tres.mem
    mem_alloc = parse_memory(fields.get("AllocMem")) or alloc_tres.mem
    return Node(
        name=fields.get("NodeName", ""),
        state=NodeState.parse(fields.get("State")),
        partitions=_csv(fields.get("Partitions")),
        cpus_total=_int(fields.get("CPUTot")) or cfg_tres.cpu,
        cpus_alloc=_int(fields.get("CPUAlloc")) or alloc_tres.cpu,
        cpu_load=_float(fields.get("CPULoad")),
        mem_total=mem_total,
        mem_alloc=mem_alloc,
        mem_free=parse_memory(fields.get("FreeMem")),
        gpus_total=gpus_total,
        gpus_alloc=gpus_alloc,
        gpu_gres_type=gres_type,
        gpu_gres="" if is_null(fields.get("Gres")) else fields.get("Gres", ""),
        features=_csv(fields.get("ActiveFeatures") or fields.get("AvailableFeatures")),
        arch=None if is_null(fields.get("Arch")) else fields.get("Arch"),
        sockets=_int(fields.get("Sockets"), 1),
        cores_per_socket=_int(fields.get("CoresPerSocket"), 1),
        threads_per_core=_int(fields.get("ThreadsPerCore"), 1),
        reason=parse_reason(fields.get("Reason")),
        cfg_tres=cfg_tres,
        alloc_tres=alloc_tres,
    )


def parse_nodes(text: str) -> list[Node]:
    nodes: list[Node] = []
    for line in text.splitlines():
        if not line.startswith("NodeName="):
            continue
        fields = parse_kv_line(line)
        if fields.get("NodeName"):
            nodes.append(node_from_fields(fields))
    return nodes
