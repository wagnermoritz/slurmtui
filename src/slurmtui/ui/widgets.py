"""Small shared widgets and renderables."""

from __future__ import annotations

import colorsys
from datetime import datetime

from rich import box
from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Static

from slurmtui.config.schema import UsageBarStyle


class RowTable(DataTable[object]):
    """A row-cursor DataTable where one click selects a row.

    DataTable posts ``RowSelected`` only for a click on the already highlighted
    row; this handler posts it for every other body row. ``DataTable._on_click``
    still runs afterwards and moves the cursor.
    """

    async def _on_click(self, event: events.Click) -> None:
        meta = event.style.meta
        row = meta.get("row", -1)
        if row >= 0 and "column" in meta and self.cursor_type == "row" and row != self.cursor_coordinate.row:
            row_key, _ = self.coordinate_to_cell_key(Coordinate(row, meta["column"]))
            self.post_message(DataTable.RowSelected(self, row, row_key))


class StatusLine(Static):
    """Status text under the filter bar, wrapped when too long; red when it carries an error."""

    def set_status(self, text: str, error: str | None = None, updated: datetime | None = None) -> None:
        parts = [text]
        if updated is not None:
            parts.append(f"updated {updated.strftime('%H:%M:%S')}")
        line = "  │  ".join(part for part in parts if part)
        if error:
            line = f"{line}  │  {error}" if line else error
        self.set_class(bool(error), "error")
        self.update(Text(line))


def usage_bar(label: str, used: int, total: int, label_width: int, style: UsageBarStyle, suffix: str = "") -> Text:
    """A coloured usage bar: label, blocks, used/total."""
    fraction = used / total if total else 0.0
    width = style.width
    filled = round(min(fraction, 1.0) * width)
    text = Text(f"  {label:<{label_width}}  ")
    if style.style == "solid":
        colour = "green" if fraction < style.warn else "yellow" if fraction < style.critical else "red"
        text.append("█" * filled, style=colour)
    else:
        for index in range(filled):
            hue = (1 - index / max(width - 1, 1)) * (120 / 360)
            red, green, blue = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            text.append("█", style=f"#{int(red * 255):02x}{int(green * 255):02x}{int(blue * 255):02x}")
    text.append("░" * (width - filled), style="dim")
    text.append(f"  {suffix or f'{used}/{total}'}")
    if total:
        text.append(f"  ({100 * fraction:.0f}%)", style="dim")
    return text


def section(title: str, content: RenderableType | list[str]) -> Panel:
    if isinstance(content, list):
        content = Text.from_markup("\n".join(content)) if content else Text("  none", style="dim")
    return Panel(
        content,
        title=f"[b]{escape(title)}[/b]",
        title_align="left",
        box=box.ROUNDED,
        border_style="dim",
        padding=(0, 1),
    )


def group(*renderables: RenderableType) -> Group:
    return Group(*renderables)
