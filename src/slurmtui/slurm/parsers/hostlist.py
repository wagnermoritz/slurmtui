"""Expand and contract Slurm hostlist expressions such as ``htc-cmp[007-009,011],gpu820``."""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable

_BRACKET_RE = re.compile(r"\[([^\]]*)\]")
_TRAILING_NUMBER_RE = re.compile(r"^(.*?)(\d+)$")


def split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside brackets."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _expand_range_spec(spec: str) -> list[str]:
    values: list[str] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            width = len(start) if start.startswith("0") or len(start) == len(end) else 0
            try:
                start_int, end_int = int(start), int(end)
            except ValueError:
                values.append(part)
                continue
            if end_int < start_int:
                start_int, end_int = end_int, start_int
            values.extend(str(number).zfill(width) for number in range(start_int, end_int + 1))
        else:
            values.append(part)
    return values


def expand(text: str | None) -> list[str]:
    """Expand a hostlist expression to individual names, in order, without duplicates."""
    if not text:
        return []
    stripped = text.strip()
    if not stripped or stripped.lower() in {"(null)", "n/a", "none"}:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in split_top_level(stripped):
        literal_parts = _BRACKET_RE.split(item)
        # literal_parts alternates: literal, range spec, literal, range spec, ..., literal
        literals = literal_parts[0::2]
        specs = literal_parts[1::2]
        if not specs:
            candidates = [item]
        else:
            expanded_specs = [_expand_range_spec(spec) for spec in specs]
            candidates = []
            for combination in itertools.product(*expanded_specs):
                pieces = [literals[0]]
                for value, literal in zip(combination, literals[1:]):
                    pieces.append(value)
                    pieces.append(literal)
                candidates.append("".join(pieces))
        for name in candidates:
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def contract(names: Iterable[str], sep: str = ",") -> str:
    """Contract names to Slurm range notation, e.g. ``cmp[001-002,005],login``.

    Names without a trailing number are kept as they are. Zero padding is
    preserved; numbers of different widths form separate ranges.
    """
    groups: dict[tuple[str, int], list[int]] = {}
    plain: list[str] = []
    order: list[tuple[str, int]] = []
    for name in sorted(set(names)):
        match = _TRAILING_NUMBER_RE.match(name)
        if match is None:
            plain.append(name)
            continue
        prefix, digits = match.group(1), match.group(2)
        width = len(digits)
        key = (prefix, width)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(int(digits))

    parts: list[str] = []
    for prefix, width in sorted(order):
        numbers = sorted(set(groups[(prefix, width)]))
        ranges: list[str] = []
        start = prev = numbers[0]
        for number in numbers[1:]:
            if number == prev + 1:
                prev = number
                continue
            ranges.append(_range_text(start, prev, width))
            start = prev = number
        ranges.append(_range_text(start, prev, width))
        if len(ranges) == 1 and "-" not in ranges[0]:
            parts.append(f"{prefix}{ranges[0]}")
        else:
            parts.append(f"{prefix}[{','.join(ranges)}]")
    parts.extend(plain)
    return sep.join(parts)


def _range_text(start: int, end: int, width: int) -> str:
    if start == end:
        return str(start).zfill(width)
    return f"{str(start).zfill(width)}-{str(end).zfill(width)}"
