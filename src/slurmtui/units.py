"""Parsing and formatting of memory sizes, durations, timestamps and lookback windows.

Pure functions shared by the parsers, the configuration and the column formatters.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal

MemoryUnit = Literal["auto", "G", "M", "T"]
DurationStyle = Literal["slurm", "compact"]

UNLIMITED = timedelta.max
"""Sentinel for Slurm's UNLIMITED durations; sorts after every real duration."""

_UNIT_EXPONENTS = {"B": 0, "K": 10, "M": 20, "G": 30, "T": 40, "P": 50}
_MEMORY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMGTP]?)(?:B|iB|b|n|c)?\s*$", re.IGNORECASE)
_MISSING = {"", "0", "n/a", "none", "null", "(null)", "unknown", "-"}


def parse_memory(text: str | None, default_unit: str = "M") -> int | None:
    """Parse a Slurm memory string to bytes; None for missing or unparseable values.

    Bare numbers are in ``default_unit`` (Slurm's default is megabytes).
    The per-node/per-CPU suffixes ``n``/``c`` are dropped.
    """
    if text is None:
        return None
    stripped = text.strip()
    if stripped.lower() in _MISSING:
        return 0 if stripped == "0" else None
    match = _MEMORY_RE.match(stripped)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or default_unit).upper()
    return int(number * 2 ** _UNIT_EXPONENTS[unit])


def format_memory(num_bytes: int | None, unit: MemoryUnit = "auto") -> str:
    """Format bytes as e.g. ``512G``, ``1.5T`` or ``3000M``."""
    if num_bytes is None:
        return "-"
    if unit == "T":  # only used internally by format_memory_pair
        return f"{_trim(num_bytes / 2**40)}T"
    if unit == "M":
        return f"{_trim(num_bytes / 2**20)}M"
    if unit == "G":
        return f"{_trim(num_bytes / 2**30)}G"
    if num_bytes >= 2**40:
        return f"{_trim(num_bytes / 2**40)}T"
    if num_bytes >= 2**30:
        return f"{_trim(num_bytes / 2**30)}G"
    return f"{_trim(num_bytes / 2**20)}M"


def format_memory_pair(used: int | None, total: int | None, unit: MemoryUnit = "auto") -> str:
    """``used/total`` with both numbers in the unit chosen for the total."""
    if unit == "auto" and total:
        unit = "T" if total >= 2**40 else "G" if total >= 2**30 else "M"
    return f"{format_memory(used, unit)}/{format_memory(total, unit)}"


def _trim(value: float) -> str:
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


_DURATION_RE = re.compile(r"^\s*(?:(?P<days>\d+)-)?(?:(?P<h>\d{1,3}):)?(?P<m>\d{1,2}):(?P<s>\d{1,2}(?:\.\d+)?)\s*$")
_DAYS_HOURS_RE = re.compile(r"^\s*(?P<days>\d+)-(?P<h>\d{1,2})\s*$")
_MINUTES_RE = re.compile(r"^\s*(?P<m>\d+)\s*$")


def parse_duration(text: str | None) -> timedelta | None:
    """Parse Slurm durations: ``D-HH:MM:SS``, ``HH:MM:SS``, ``MM:SS``, ``D-HH``, bare minutes.

    ``UNLIMITED`` becomes the UNLIMITED sentinel; ``N/A``, ``INVALID``, ``Unknown``
    and empty strings become None. Fractional seconds (sacct TotalCPU) are kept.
    """
    if text is None:
        return None
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in {"unlimited", "infinite"}:
        return UNLIMITED
    if lowered in {"", "n/a", "invalid", "unknown", "none", "not_set", "-"}:
        return None
    match = _DURATION_RE.match(stripped)
    if match:
        days = int(match.group("days") or 0)
        hours = int(match.group("h") or 0)
        minutes = int(match.group("m"))
        seconds = float(match.group("s"))
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    match = _DAYS_HOURS_RE.match(stripped)
    if match:
        return timedelta(days=int(match.group("days")), hours=int(match.group("h")))
    match = _MINUTES_RE.match(stripped)
    if match:
        return timedelta(minutes=int(match.group("m")))
    return None


def format_duration(value: timedelta | None, style: DurationStyle = "slurm") -> str:
    """Format a duration as ``D-HH:MM:SS`` (slurm) or ``2d 3h`` (compact)."""
    if value is None:
        return "-"
    if value == UNLIMITED:
        return "unlimited"
    total = int(value.total_seconds())
    if total < 0:
        total = 0
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    if style == "compact":
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m {seconds:02d}s"
    if days:
        return f"{days}-{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


_TIMESTAMP_FORMATS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def parse_timestamp(text: str | None) -> datetime | None:
    """Parse Slurm's ISO timestamps; ``Unknown``, ``None``, ``N/A`` and empty give None."""
    if text is None:
        return None
    stripped = text.strip()
    if not stripped or stripped.lower() in {"unknown", "none", "n/a", "(null)", "-"}:
        return None
    try:
        return datetime.fromisoformat(stripped)
    except ValueError:
        pass
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            continue
    return None


_WINDOW_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(hours?|days?|weeks?|h|d|w)?\s*$", re.IGNORECASE)


def parse_window(text: str | None) -> timedelta | None:
    """Parse a lookback window like ``12h``, ``3d``, ``2w``, ``2 days`` or a plain number of days."""
    if text is None:
        return None
    match = _WINDOW_RE.match(text)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "d")[0].lower()
    if unit == "h":
        return timedelta(hours=number)
    if unit == "w":
        return timedelta(weeks=number)
    return timedelta(days=number)


def format_window(value: timedelta) -> str:
    hours = value.total_seconds() / 3600
    if hours % (24 * 7) == 0:
        return f"{int(hours // (24 * 7))}w"
    if hours % 24 == 0:
        return f"{int(hours // 24)}d"
    return f"{_trim(hours)}h"


def format_percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{100 * value:.{digits}f}%"
