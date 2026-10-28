"""Parse ``sshare -a -P -n`` output."""

from __future__ import annotations

from slurmtui.model.records import ShareEntry
from slurmtui.slurm.commands import SSHARE_DELIMITER, SSHARE_FIELDS
from slurmtui.slurm.parsers.common import split_delimited


def _float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    if value.lower() in {"inf", "infinity"}:
        return float("inf")
    try:
        return float(value)
    except ValueError:
        return None  # e.g. "parent"


def parse_shares(text: str) -> list[ShareEntry]:
    entries: list[ShareEntry] = []
    for cells in split_delimited(text, SSHARE_DELIMITER):
        if len(cells) < len(SSHARE_FIELDS):
            continue
        account, user, raw_shares, norm_shares, raw_usage, eff_usage, fairshare, level_fs = cells[: len(SSHARE_FIELDS)]
        if not account or (account == "root" and not user):
            continue
        entries.append(
            ShareEntry(
                account=account,
                user=user or None,
                raw_shares=_float(raw_shares),
                norm_shares=_float(norm_shares),
                raw_usage=_float(raw_usage),
                effective_usage=_float(eff_usage),
                fairshare=_float(fairshare),
                level_fs=_float(level_fs),
            )
        )
    return entries
