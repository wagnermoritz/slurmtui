"""Parse ``scontrol show partition -o`` output."""

from __future__ import annotations

from slurmtui.model.records import Partition
from slurmtui.slurm.parsers import hostlist
from slurmtui.slurm.parsers.common import parse_kv_line, parse_tres
from slurmtui.units import parse_duration


def _int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def parse_partitions(text: str) -> list[Partition]:
    partitions: list[Partition] = []
    for line in text.splitlines():
        if not line.startswith("PartitionName="):
            continue
        fields = parse_kv_line(line)
        partitions.append(
            Partition(
                name=fields.get("PartitionName", ""),
                state=fields.get("State", "UP").upper(),
                max_time=parse_duration(fields.get("MaxTime")),
                default_time=parse_duration(fields.get("DefaultTime")),
                is_default=fields.get("Default", "NO").upper() == "YES",
                nodes=tuple(hostlist.expand(fields.get("Nodes"))),
                total_cpus=_int(fields.get("TotalCPUs")),
                total_nodes=_int(fields.get("TotalNodes")),
                tres=parse_tres(fields.get("TRES")),
                max_nodes=fields.get("MaxNodes", ""),
            )
        )
    return partitions
