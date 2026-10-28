"""Multi-column sort specifications: ``state desc, name``."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Literal

from slurmtui.columns.registry import ColumnDef
from slurmtui.model.states import NodeState

Direction = Literal["asc", "desc"]
SortSpec = list[tuple[str, Direction]]

_DIRECTIONS: dict[str, Direction] = {
    "asc": "asc",
    "ascending": "asc",
    "a": "asc",
    "up": "asc",
    "desc": "desc",
    "descending": "desc",
    "d": "desc",
    "down": "desc",
}


def parse_sort(text: str, valid_keys: Iterable[str]) -> tuple[SortSpec, str | None]:
    """Parse a sort string. Returns (spec, error); the spec is empty when there is an error."""
    lookup = {key.lower(): key for key in valid_keys}
    spec: SortSpec = []
    seen: set[str] = set()
    for entry in (part.strip() for part in text.split(",")):
        if not entry:
            continue
        tokens = entry.split()
        direction: Direction = "asc"
        if len(tokens) > 1 and tokens[-1].lower() in _DIRECTIONS:
            direction = _DIRECTIONS[tokens[-1].lower()]
            tokens = tokens[:-1]
        key = lookup.get(" ".join(tokens).lower())
        if key is None:
            return [], f"unknown column '{' '.join(tokens)}'"
        if key in seen:
            return [], f"column '{key}' appears twice"
        seen.add(key)
        spec.append((key, direction))
    return spec, None


def format_sort(spec: SortSpec) -> str:
    return ", ".join(f"{key} {direction}" if direction == "desc" else key for key, direction in spec)


def cycle_sort(spec: SortSpec, key: str) -> SortSpec:
    """Header click behaviour: new column -> primary asc; asc -> desc; desc -> removed."""
    current = dict(spec)
    if key not in current:
        return [(key, "asc"), *spec]
    if current[key] == "asc":
        return [(k, "desc" if k == key else d) for k, d in spec]
    return [(k, d) for k, d in spec if k != key]


def sort_marker(spec: SortSpec, key: str) -> str:
    for index, (spec_key, direction) in enumerate(spec):
        if spec_key == key:
            arrow = "↑" if direction == "asc" else "↓"
            return f"{arrow}{index}" if len(spec) > 1 else arrow
    return ""


def _jobid_key(value: str) -> tuple[int, ...]:
    numbers: list[int] = []
    current = ""
    for char in value:
        if char.isdigit():
            current += char
        elif current:
            numbers.append(int(current))
            current = ""
    if current:
        numbers.append(int(current))
    return tuple(numbers) or (0,)


def sort_key_for(column: ColumnDef) -> Callable[[Any], Any]:
    kind = column.type
    if kind in {"str", "avail", "list"}:
        return lambda v: (",".join(v) if isinstance(v, tuple | list) else str(v)).lower()
    if kind == "nodelist":
        return lambda v: (len(v), tuple(v))
    if kind == "node_state":
        return lambda v: v.compact if isinstance(v, NodeState) else str(v)
    if kind == "job_state":
        return lambda v: str(v)
    if kind == "jobid":
        return _jobid_key
    if kind in {"fraction", "bytes_fraction"}:
        return lambda v: (v[0], v[1])
    return lambda v: v


def sort_rows(rows: Sequence[Any], spec: SortSpec, columns: dict[str, ColumnDef]) -> list[Any]:
    """Stable multi-key sort on raw values; None sorts last in both directions."""
    ordered = list(rows)
    for key, direction in reversed(spec):
        column = columns.get(key)
        if column is None:
            continue
        getter = column.getter
        key_fn = sort_key_for(column)
        reverse = direction == "desc"
        none_rank = 0 if reverse else 1

        def row_key(
            row: Any,
            _getter: Callable[[Any], Any] = getter,
            _key_fn: Callable[[Any], Any] = key_fn,
            _none_rank: int = none_rank,
        ) -> Any:
            try:
                value = _getter(row)
            except Exception:
                value = None
            if value is None:
                return (_none_rank, 0)
            try:
                return (1 - _none_rank, _key_fn(value))
            except Exception:
                return (_none_rank, 0)

        ordered.sort(key=row_key, reverse=reverse)
    return ordered
