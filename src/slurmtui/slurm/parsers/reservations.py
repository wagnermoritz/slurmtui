"""Parse ``scontrol show reservation -o`` output."""

from __future__ import annotations

from slurmtui.model.records import Reservation
from slurmtui.slurm.parsers import hostlist
from slurmtui.slurm.parsers.common import is_null, parse_kv_line
from slurmtui.units import parse_timestamp


def _csv(value: str | None) -> tuple[str, ...]:
    if is_null(value):
        return ()
    assert value is not None
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_reservations(text: str) -> list[Reservation]:
    reservations: list[Reservation] = []
    for line in text.splitlines():
        if not line.startswith("ReservationName="):
            continue
        fields = parse_kv_line(line)
        node_spec = "" if is_null(fields.get("Nodes")) else fields.get("Nodes", "")
        reservations.append(
            Reservation(
                name=fields.get("ReservationName", ""),
                state=fields.get("State", "").upper(),
                start=parse_timestamp(fields.get("StartTime")),
                end=parse_timestamp(fields.get("EndTime")),
                nodes=tuple(hostlist.expand(node_spec)),
                node_spec=node_spec,
                users=_csv(fields.get("Users")),
                accounts=_csv(fields.get("Accounts")),
                flags=_csv(fields.get("Flags")),
            )
        )
    return reservations
