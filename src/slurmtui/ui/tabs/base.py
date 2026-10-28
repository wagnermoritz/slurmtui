"""The generic table tab: filter bar, status line and a DataTable driven by column specs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, ClassVar

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Input

from slurmtui.columns.filter import EMPTY_FILTER, Filter, FilterError, parse_filter
from slurmtui.columns.format import Formatter
from slurmtui.columns.registry import ColumnDef, registry_for, resolve_columns
from slurmtui.columns.sort import SortSpec, cycle_sort, format_sort, parse_sort, sort_marker
from slurmtui.columns.table import TableData, build_table
from slurmtui.data.service import SourceError
from slurmtui.ui.context import TabContext
from slurmtui.ui.screens.detail import Action, ActionOutcome, DetailScreen, DetailSpec
from slurmtui.ui.widgets import RowTable, StatusLine

log = logging.getLogger(__name__)


class TableTab(Vertical):
    """Base class of NODES, JOBS, USERS, ACCOUNTS and HISTORY."""

    TAB: ClassVar[str] = ""
    SOURCES: ClassVar[tuple[str, ...]] = ()
    EMPTY_MESSAGE: ClassVar[str] = "nothing to show"

    def __init__(self, ctx: TabContext) -> None:
        super().__init__(id=f"tab-{self.TAB}")
        self.ctx = ctx
        self.tab_config = ctx.config.table_tab(self.TAB)
        self.registry: dict[str, ColumnDef] = registry_for(self.TAB, ctx.config)
        self.columns: list[ColumnDef] = resolve_columns(ctx.config, self.TAB)
        self.sort_spec, _ = parse_sort(self.tab_config.sort, self.registry)
        self.filter_text = self.tab_config.filter
        self.filter: Filter = EMPTY_FILTER
        self.filter_error: str | None = None
        self._set_filter_text(self.filter_text, persist=False)
        self.records: list[Any] = []
        self.table_data: TableData | None = None
        self.load_error: str | None = None
        self.note: str | None = None
        self._filter_timer: Timer | None = None
        self.loaded_once = False

    # -- composition ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(classes="filter-bar"):
            yield Input(
                value=self.filter_text,
                placeholder="filter: regex, col=value, col~regex, col>value, @me   (? for help)",
                id=f"{self.TAB}-filter",
                classes="filter-input",
            )
            yield from self.extra_inputs()
        yield StatusLine("", id=f"{self.TAB}-status", classes="status-line")
        yield RowTable(id=f"{self.TAB}-table", cursor_type="row", zebra_stripes=True)

    def extra_inputs(self) -> Iterable[Input]:
        return ()

    def on_mount(self) -> None:
        self.refresh_data(force=False)

    def focus_table(self) -> None:
        self.query_one(DataTable).focus()

    @property
    def formatter(self) -> Formatter:
        return self.ctx.formatter

    @property
    def table(self) -> DataTable[Any]:
        return self.query_one(DataTable)

    @property
    def status_line(self) -> StatusLine:
        return self.query_one(StatusLine)

    @property
    def filter_input(self) -> Input:
        return self.query_one(f"#{self.TAB}-filter", Input)

    # -- data -----------------------------------------------------------------

    async def load_records(self, force: bool, include_expensive: bool) -> list[Any]:
        raise NotImplementedError

    def key_of(self, record: Any) -> str:
        raise NotImplementedError

    def status_text(self, data: TableData) -> str:
        return ""

    def detail_spec(self, record: Any) -> DetailSpec | None:
        return None

    @work(exclusive=True, group="refresh")
    async def refresh_data(self, force: bool = True, include_expensive: bool = True) -> None:
        self.load_error = None
        try:
            self.records = await self.load_records(force, include_expensive)
        except SourceError as exc:
            self.load_error = str(exc)
        except Exception as exc:  # shown in the status line
            log.exception("loading %s failed", self.TAB)
            self.load_error = f"{type(exc).__name__}: {exc}"
        self.loaded_once = True
        await self.render_rows()

    def primary_params(self) -> tuple[Any, ...]:
        """Cache-key parameters of the first source (e.g. the window of the history source)."""
        return ()

    def is_stale(self) -> bool:
        service = self.ctx.service
        if not self.SOURCES:
            return False
        first, *rest = self.SOURCES
        if service.is_enabled(first) and not service.is_fresh(first, *self.primary_params()):
            return True
        return any(not service.is_fresh(name) for name in rest if service.is_enabled(name))

    async def render_rows(self) -> None:
        data = await asyncio.to_thread(
            build_table,
            self.records,
            self.columns,
            self.registry,
            self.formatter,
            self.sort_spec,
            self.filter,
            self.key_of,
            self.ctx.config.general.max_rows,
        )
        self.table_data = data
        self._fill_table(data)
        self.update_status()

    def _cursor_key(self) -> str | None:
        table = self.table
        if table.row_count == 0:
            return None
        try:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return None

    def _fill_table(self, data: TableData) -> None:
        table = self.table
        previous = self._cursor_key()
        table.clear(columns=True)
        widths = _column_widths(data)
        for index, column in enumerate(data.columns):
            marker = sort_marker(self.sort_spec, column.key)
            label = Text(
                f"{column.label} {marker}".rstrip(),
                justify="right" if column.alignment == "right" else "left",
            )
            # Explicit widths: with auto widths the DataTable measures cells on idle and keeps
            # earlier cell renders, so rows painted first stay narrow until a re-render.
            width = column.width if column.width is not None else max(widths[index], label.cell_len)
            table.add_column(label, key=column.key, width=width)
        for row in data.rows:
            table.add_row(*row.cells, key=row.key)
        if previous is not None and previous in table.rows:
            table.move_cursor(row=table.get_row_index(previous), animate=False)

    def update_status(self) -> None:
        data = self.table_data
        parts: list[str] = []
        if data is not None:
            parts.append(self.status_text(data))
            shown = f"{data.matched} of {data.total}" if data.matched != data.total else str(data.total)
            if data.capped:
                shown += f", showing first {len(data.rows)}"
            parts.append(f"{shown} rows")
        if self.note:
            parts.append(self.note)
        errors = [self.load_error] if self.load_error else []
        if self.filter_error:
            errors.append(f"filter: {self.filter_error}")
        for name in self.SOURCES:
            status = self.ctx.service.status(name) if name in self.ctx.service.names else None
            if status and status.last_error and status.last_error not in errors:
                errors.append(
                    f"{name}: {status.last_error} (showing stale data)" if status.updated_at else status.last_error
                )
        updated = None
        if self.SOURCES and self.SOURCES[0] in self.ctx.service.names:
            updated = self.ctx.service.status(self.SOURCES[0], *self.primary_params()).updated_at
        self.status_line.set_status("  │  ".join(part for part in parts if part), "; ".join(errors) or None, updated)

    # -- sorting --------------------------------------------------------------

    def set_sort(self, spec: SortSpec) -> None:
        self.sort_spec = spec
        self.ctx.state.tab(self.TAB).sort = format_sort(spec)
        self.ctx.persist()
        self.call_later(self.render_rows)

    @on(DataTable.HeaderSelected)
    def _header_selected(self, event: DataTable.HeaderSelected) -> None:
        key = event.column_key.value
        if key:
            self.set_sort(cycle_sort(self.sort_spec, key))

    # -- filtering ------------------------------------------------------------

    def _set_filter_text(self, text: str, persist: bool = True) -> bool:
        try:
            self.filter = parse_filter(text, self.registry, self.ctx.whoami)
            self.filter_error = None
        except FilterError as exc:
            self.filter_error = str(exc)
            return False
        self.filter_text = text
        if persist:
            self.ctx.state.tab(self.TAB).filter = text
            self.ctx.persist()
        return True

    def set_filter_text(self, text: str, update_input: bool = True) -> None:
        if update_input:
            self.filter_input.value = text
        if self._set_filter_text(text):
            self.call_later(self.render_rows)
        else:
            self.update_status()

    @on(Input.Changed)
    def _input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f"{self.TAB}-filter":
            return
        if self._filter_timer is not None:
            self._filter_timer.stop()
        value = event.value
        self._filter_timer = self.set_timer(0.3, lambda: self.set_filter_text(value, update_input=False))

    @on(Input.Submitted)
    def _input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == f"{self.TAB}-filter":
            if self._filter_timer is not None:
                self._filter_timer.stop()
            self.set_filter_text(event.value, update_input=False)
            self.table.focus()
        else:
            self.extra_input_submitted(event.input.id or "", event.value)
            self.table.focus()

    def extra_input_submitted(self, input_id: str, value: str) -> None:
        return None

    def focus_filter(self) -> None:
        self.filter_input.focus()

    def clear_filter(self) -> None:
        self.set_filter_text("")

    # -- columns --------------------------------------------------------------

    def set_columns(self, columns: list[ColumnDef]) -> None:
        self.columns = columns
        self.call_later(self.render_rows)

    # -- details --------------------------------------------------------------

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        if self.table_data is None or event.row_key.value is None:
            return
        record = next((row.record for row in self.table_data.rows if row.key == event.row_key.value), None)
        if record is None:
            return
        spec = self.detail_spec(record)
        if spec is not None:
            self.app.push_screen(DetailScreen(spec))

    def show_jobs_action(
        self, filter_text: str, origin: str
    ) -> tuple[list[Action], Callable[[str], Awaitable[ActionOutcome]]]:
        """A detail button that closes the detail and opens the JOBS tab with ``filter_text``."""

        async def on_action(action_id: str) -> ActionOutcome:
            show_jobs = getattr(self.app, "show_jobs", None)
            if show_jobs is None:
                return ActionOutcome(message="JOBS tab not available", ok=False, reload=False)
            show_jobs(filter_text, origin)
            return ActionOutcome(message="", reload=False, close=True)

        return [Action("show-jobs", "Show in JOBS")], on_action

    def open_selected(self) -> None:
        key = self._cursor_key()
        if key is None or self.table_data is None:
            return
        record = next((row.record for row in self.table_data.rows if row.key == key), None)
        if record is not None and (spec := self.detail_spec(record)) is not None:
            self.app.push_screen(DetailScreen(spec))


def _column_widths(data: TableData) -> list[int]:
    """Widest cell per column, in terminal cells."""
    widths = [0] * len(data.columns)
    for row in data.rows:
        for index, cell in enumerate(row.cells):
            length = cell.cell_len
            if length > widths[index]:
                widths[index] = length
    return widths
