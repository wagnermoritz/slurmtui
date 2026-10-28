"""Settings screen generated from the configuration: general options and per-tab columns/sort."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Collapsible, Input, Select, SelectionList, Static
from textual.widgets.selection_list import Selection

from slurmtui.columns.registry import ColumnDef, resolve_columns
from slurmtui.columns.sort import format_sort, parse_sort
from slurmtui.config.schema import TABLE_TABS, ColumnSpec

if TYPE_CHECKING:
    from slurmtui.app import SlurmTuiApp
    from slurmtui.ui.tabs.base import TableTab


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "dismiss_screen", "Close")]

    def __init__(self, app_ref: SlurmTuiApp) -> None:
        super().__init__()
        self.tui = app_ref

    def compose(self) -> ComposeResult:
        config = self.tui.config
        with Vertical(classes="modal-box"):
            yield Static("Settings  (changes apply immediately and are saved to the state file)", classes="modal-title")
            with VerticalScroll(classes="modal-body"):
                yield Static("General", classes="settings-label")
                with Horizontal(classes="settings-row"):
                    yield Static(" Theme")
                    yield Select(
                        [(name, name) for name in sorted(self.tui.available_themes)],
                        value=self.tui.theme,
                        allow_blank=False,
                        id="set-theme",
                    )
                with Horizontal(classes="settings-row"):
                    yield Static(" Memory unit")
                    yield Select(
                        [("auto", "auto"), ("G", "G"), ("M", "M")],
                        value=config.general.memory_unit,
                        allow_blank=False,
                        id="set-memory-unit",
                    )
                with Horizontal(classes="settings-row"):
                    yield Static(" Duration style")
                    yield Select(
                        [("slurm (D-HH:MM:SS)", "slurm"), ("compact (2d 3h)", "compact")],
                        value=config.general.duration_style,
                        allow_blank=False,
                        id="set-duration-style",
                    )
                yield Checkbox(
                    f"Auto refresh every {config.refresh.active_tab_seconds:g}s (active tab) / "
                    f"{config.refresh.inactive_tabs_seconds:g}s (other tabs)",
                    value=self.tui.auto_refresh_on,
                    id="set-auto-refresh",
                    classes="settings-check",
                )
                for tab_name in TABLE_TABS:
                    tab = self.tui.tabs.get(tab_name)
                    if tab is None or not hasattr(tab, "registry"):
                        continue
                    title = config.table_tab(tab_name).title
                    with Collapsible(title=f"{title} columns and sorting", collapsed=True, id=f"set-{tab_name}"):
                        with Horizontal(classes="settings-row"):
                            yield Static(" Sort by")
                            yield Input(
                                value=format_sort(tab.sort_spec),
                                id=f"sort-{tab_name}",
                                placeholder="e.g. state desc, name",
                            )
                        yield Static("", id=f"sort-status-{tab_name}", classes="modal-hint")
                        with Horizontal(classes="settings-row"):
                            yield Static(" Column order")
                            yield Input(value=", ".join(c.key for c in tab.columns), id=f"order-{tab_name}")
                        yield Static("", id=f"order-status-{tab_name}", classes="modal-hint")
                        visible = {c.key for c in tab.columns}
                        yield SelectionList[str](
                            *[
                                Selection(f"{key:<18} {column.label} — {column.description}", key, key in visible)
                                for key, column in sorted(tab.registry.items())
                            ],
                            id=f"cols-{tab_name}",
                        )
                        yield Button("Reset tab to config", id=f"reset-{tab_name}")
                yield Static("", classes="modal-hint")
                yield Static(self._files_text(), classes="modal-hint")
            with Horizontal(classes="modal-actions"):
                yield Button("Close", id="close")

    def _files_text(self) -> str:
        files = ", ".join(str(path) for path in self.tui.config_files) or "none (packaged defaults)"
        return f"Config files: {files}\nState file: {self.tui.state_path}"

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    # -- general --------------------------------------------------------------

    @on(Select.Changed)
    def _select_changed(self, event: Select.Changed) -> None:
        value = event.value
        if value is Select.BLANK:
            return
        if event.select.id == "set-theme":
            self.tui.set_theme(str(value))
        elif event.select.id == "set-memory-unit":
            self.tui.update_general(memory_unit=str(value))
        elif event.select.id == "set-duration-style":
            self.tui.update_general(duration_style=str(value))

    @on(Checkbox.Changed, "#set-auto-refresh")
    def _auto(self, event: Checkbox.Changed) -> None:
        self.tui.set_auto_refresh(event.value)

    # -- per tab --------------------------------------------------------------

    def _tab(self, widget_id: str, prefix: str) -> tuple[str, TableTab]:
        name = widget_id.removeprefix(prefix)
        return name, self.tui.tabs[name]

    @on(Input.Changed)
    def _input_changed(self, event: Input.Changed) -> None:
        widget_id = event.input.id or ""
        if widget_id.startswith("sort-"):
            name, tab = self._tab(widget_id, "sort-")
            spec, error = parse_sort(event.value, tab.registry)
            status = self.query_one(f"#sort-status-{name}", Static)
            status.update(f"✗ {error}" if error else f"✓ {format_sort(spec) or 'no sorting'}  (Enter applies)")
        elif widget_id.startswith("order-"):
            name, tab = self._tab(widget_id, "order-")
            _, error = self._parse_order(event.value, tab.registry)
            self.query_one(f"#order-status-{name}", Static).update(f"✗ {error}" if error else "✓ (Enter applies)")

    @on(Input.Submitted)
    def _input_submitted(self, event: Input.Submitted) -> None:
        widget_id = event.input.id or ""
        if widget_id.startswith("sort-"):
            name, tab = self._tab(widget_id, "sort-")
            spec, error = parse_sort(event.value, tab.registry)
            if error is None:
                tab.set_sort(spec)
                self.query_one(f"#sort-status-{name}", Static).update(f"✓ {format_sort(spec) or 'no sorting'}")
        elif widget_id.startswith("order-"):
            name, tab = self._tab(widget_id, "order-")
            keys, error = self._parse_order(event.value, tab.registry)
            if error is None and keys:
                self._apply_columns(name, keys)
                selection = self.query_one(f"#cols-{name}", SelectionList)
                with selection.prevent(SelectionList.SelectedChanged):
                    selection.deselect_all()
                    for key in keys:
                        selection.select(key)
                self.query_one(f"#order-status-{name}", Static).update("✓ applied")

    @staticmethod
    def _parse_order(text: str, registry: dict[str, ColumnDef]) -> tuple[list[str], str | None]:
        keys = [part.strip() for part in text.split(",") if part.strip()]
        unknown = [key for key in keys if key not in registry]
        if unknown:
            return [], f"unknown column(s): {', '.join(unknown)}"
        if len(set(keys)) != len(keys):
            return [], "a column is listed twice"
        if not keys:
            return [], "at least one column is needed"
        return keys, None

    @on(SelectionList.SelectedChanged)
    def _selection_changed(self, event: SelectionList.SelectedChanged[str]) -> None:
        widget_id = event.selection_list.id or ""
        if not widget_id.startswith("cols-"):
            return
        name, tab = self._tab(widget_id, "cols-")
        selected = set(event.selection_list.selected)
        current = [c.key for c in tab.columns]
        keys = [key for key in current if key in selected] + [key for key in sorted(selected) if key not in current]
        if not keys:
            return
        self._apply_columns(name, keys)
        self.query_one(f"#order-{name}", Input).value = ", ".join(keys)

    def _apply_columns(self, name: str, keys: list[str]) -> None:
        tab = self.tui.tabs[name]
        existing = {spec.key: spec for spec in self.tui.config.table_tab(name).columns}
        specs = [existing.get(key, ColumnSpec(key=key)) for key in keys]
        self.tui.update_tab_columns(name, specs)
        tab.set_columns(resolve_columns(self.tui.config, name))

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        widget_id = event.button.id or ""
        if widget_id == "close":
            self.dismiss(None)
        elif widget_id.startswith("reset-"):
            name = widget_id.removeprefix("reset-")
            self.tui.reset_tab(name)
            tab = self.tui.tabs[name]
            self.query_one(f"#sort-{name}", Input).value = format_sort(tab.sort_spec)
            self.query_one(f"#order-{name}", Input).value = ", ".join(c.key for c in tab.columns)
            selection = self.query_one(f"#cols-{name}", SelectionList)
            with selection.prevent(SelectionList.SelectedChanged):
                selection.deselect_all()
                for column in tab.columns:
                    selection.select(column.key)
