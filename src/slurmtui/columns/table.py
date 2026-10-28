"""Build sorted, filtered, formatted rows for a table tab: the glue the UI calls."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from slurmtui.columns.filter import EMPTY_FILTER, Filter
from slurmtui.columns.format import Formatter
from slurmtui.columns.registry import ColumnDef
from slurmtui.columns.sort import SortSpec, sort_rows


@dataclass(frozen=True)
class TableRow:
    key: str
    record: Any
    cells: tuple[Text, ...]


@dataclass(frozen=True)
class TableData:
    columns: list[ColumnDef]
    rows: list[TableRow]
    total: int
    matched: int
    capped: bool
    matched_records: list[Any] = field(default_factory=list)


def build_table(
    records: Sequence[Any],
    visible: list[ColumnDef],
    registry: dict[str, ColumnDef],
    formatter: Formatter,
    sort: SortSpec,
    row_filter: Filter = EMPTY_FILTER,
    key_of: Any = None,
    max_rows: int = 2000,
) -> TableData:
    key_of = key_of or (lambda record: str(id(record)))
    matched: list[Any] = []
    if row_filter.is_empty:
        matched = list(records)
    else:
        for record in records:
            texts = {column.key: formatter.text(column, _get(column, record)) for column in visible}
            row_text = " ".join(texts.values())

            def column_text(key: str, _texts: dict[str, str] = texts, _record: Any = record) -> str | None:
                if key in _texts:
                    return _texts[key]
                column = registry.get(key)
                return formatter.text(column, _get(column, _record)) if column else None

            def raw_value(key: str, _record: Any = record) -> Any:
                column = registry.get(key)
                return _get(column, _record) if column else None

            if row_filter.matches(row_text, column_text, raw_value):
                matched.append(record)
    ordered = sort_rows(matched, sort, registry)
    capped = len(ordered) > max_rows
    rows = [
        TableRow(
            key=key_of(record),
            record=record,
            cells=tuple(formatter.cell(column, _get(column, record)) for column in visible),
        )
        for record in ordered[:max_rows]
    ]
    return TableData(
        columns=visible,
        rows=rows,
        total=len(records),
        matched=len(matched),
        capped=capped,
        matched_records=ordered,
    )


def _get(column: ColumnDef, record: Any) -> Any:
    try:
        return column.getter(record)
    except Exception:
        return None
