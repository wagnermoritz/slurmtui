"""Format typed column values as Rich text according to the user's units and styles."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from rich.text import Text

from slurmtui.columns.registry import ColumnDef
from slurmtui.config.schema import Config, style_for_state
from slurmtui.model.states import NodeState
from slurmtui.slurm.parsers import hostlist
from slurmtui.units import format_duration, format_memory, format_memory_pair, format_percent

ELLIPSIS = "…"


class Formatter:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.general = config.general
        self.styles = config.styles

    # -- plain text -----------------------------------------------------------

    def text(self, column: ColumnDef, value: Any) -> str:
        """The plain string for a value (used for filtering and as the cell content)."""
        if value is None:
            return "-"
        kind = column.type
        if kind == "str" or kind == "avail" or kind == "jobid":
            return str(value)
        if kind == "int":
            return str(int(value))
        if kind == "float":
            if value == float("inf"):
                return "inf"
            return f"{float(value):.{column.digits}f}"
        if kind == "bytes":
            return format_memory(int(value), self.general.memory_unit)
        if kind == "duration":
            return format_duration(value, self.general.duration_style)
        if kind == "datetime":
            return value.strftime(self.general.datetime_format) if isinstance(value, datetime) else str(value)
        if kind == "percent":
            return format_percent(value)
        if kind == "fraction":
            used, total = value
            return f"{used}/{total}"
        if kind == "bytes_fraction":
            used, total = value
            return format_memory_pair(used, total, self.general.memory_unit)
        if kind == "nodelist":
            return hostlist.contract(value) if value else "-"
        if kind == "list":
            return ",".join(value) if value else "-"
        if kind == "node_state":
            return value.compact if isinstance(value, NodeState) else str(value)
        if kind == "job_state":
            return str(value)
        return str(value)

    def truncate(self, column: ColumnDef, text: str) -> str:
        if column.max_len is not None and len(text) > column.max_len:
            return text[: max(column.max_len - 1, 1)] + ELLIPSIS
        return text

    # -- styles ---------------------------------------------------------------

    def style(self, column: ColumnDef, value: Any) -> str:
        if value is None:
            return "dim"
        kind = column.type
        if kind == "node_state" and isinstance(value, NodeState):
            style = style_for_state(self.styles.node_state, value.style_key)
            for flag in value.flag_style_keys:
                flag_style = self.styles.node_state_flags.get(flag)
                if flag_style:
                    style = f"{style} {flag_style}".strip()
                    break
            return style
        if kind == "job_state":
            return style_for_state(self.styles.job_state, str(value).upper())
        if kind == "avail":
            return "green" if value == "up" else "red"
        if kind == "percent":
            thresholds = self.styles.efficiency
            if value < thresholds.critical:
                return "red"
            if value < thresholds.warn:
                return "yellow"
            return "green"
        return ""

    def cell(self, column: ColumnDef, value: Any) -> Text:
        text = self.truncate(column, self.text(column, value))
        return Text(text, style=self.style(column, value), justify=column.alignment, no_wrap=True)

    # -- misc -----------------------------------------------------------------

    def memory(self, num_bytes: int | None) -> str:
        return format_memory(num_bytes, self.general.memory_unit)

    def duration(self, value: timedelta | None) -> str:
        return format_duration(value, self.general.duration_style)

    def when(self, value: datetime | None) -> str:
        return value.strftime(self.general.datetime_format) if value else "-"
