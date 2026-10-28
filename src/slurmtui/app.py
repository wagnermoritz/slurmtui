"""The Textual application: tab shell, key bindings, refresh timers and state persistence."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widgets import Footer, Input, Static, TabbedContent, TabPane

from slurmtui import __version__
from slurmtui.columns.format import Formatter
from slurmtui.columns.registry import resolve_columns
from slurmtui.config.schema import ALL_TABS, ColumnSpec, Config, KeysConfig, TableTabConfig, tab_enabled
from slurmtui.config.state import State, save_state
from slurmtui.data.service import DataService
from slurmtui.model.derive import Deriver
from slurmtui.slurm.backend import SlurmBackend
from slurmtui.ui.context import TabContext
from slurmtui.ui.screens.help import HelpScreen
from slurmtui.ui.screens.settings import SettingsScreen
from slurmtui.ui.screens.sort_dialog import SortDialog
from slurmtui.ui.tabs.accounts import AccountsTab
from slurmtui.ui.tabs.base import TableTab
from slurmtui.ui.tabs.cluster import ClusterTab
from slurmtui.ui.tabs.history import HistoryTab
from slurmtui.ui.tabs.jobs import JobsTab
from slurmtui.ui.tabs.nodes import NodesTab
from slurmtui.ui.tabs.users import UsersTab

log = logging.getLogger(__name__)

TAB_CLASSES: dict[str, type[Any]] = {
    "nodes": NodesTab,
    "jobs": JobsTab,
    "users": UsersTab,
    "accounts": AccountsTab,
    "history": HistoryTab,
    "cluster": ClusterTab,
}

ACTIONS: list[tuple[str, str, str, bool]] = [
    # (keys field, action, description, show in footer)
    ("quit", "quit", "Quit", True),
    ("help", "help", "Help", True),
    ("refresh", "refresh", "Refresh", True),
    ("refresh_all", "refresh_all", "Refresh all", False),
    ("toggle_auto_refresh", "toggle_auto_refresh", "Auto refresh", True),
    ("focus_filter", "focus_filter", "Filter", True),
    ("clear_filter", "clear_filter", "Clear filter", False),
    ("next_tab", "next_tab", "Next tab", False),
    ("prev_tab", "prev_tab", "Prev tab", False),
    ("my_jobs", "my_jobs", "My jobs", True),
    ("settings", "settings", "Settings", True),
    ("sort_dialog", "sort_dialog", "Sort", True),
    ("close", "close", "Close", False),
    ("restore_filter", "restore_filter", "Previous filter", False),
]


def make_bindings(keys: KeysConfig) -> list[Binding]:
    bindings: list[Binding] = []
    for field, action, description, show in ACTIONS:
        for index, key in enumerate(getattr(keys, field)):
            bindings.append(Binding(key, action, description, show=show and index == 0, priority=action in {"quit"}))
    return bindings


class SlurmTuiApp(App[None]):
    CSS_PATH = Path(__file__).parent / "ui" / "styles.tcss"
    TITLE = "slurmtui"
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        config: Config,
        backend: SlurmBackend,
        service: DataService,
        state: State,
        *,
        state_path: Path | None = None,
        config_files: Sequence[Path] = (),
        initial_tab: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.backend = backend
        self.service = service
        self.state = state
        self.state_path = state_path
        self.config_files = list(config_files)
        self.initial_tab = initial_tab
        self.auto_refresh_on = config.refresh.auto
        self.formatter = Formatter(config)
        self.ctx = TabContext(
            config=config,
            backend=backend,
            service=service,
            state=state,
            persist=self.schedule_state_save,
            formatter=self.formatter,
            deriver=Deriver(config),
        )
        self.tabs: dict[str, Any] = {}
        self._save_timer: Timer | None = None
        self.version_text = ""

    # -- composition ----------------------------------------------------------

    @property
    def enabled_tabs(self) -> list[str]:
        return [name for name in ALL_TABS if tab_enabled(self.config, name)]

    def compose(self) -> ComposeResult:
        with TabbedContent(id="tabs"):
            for name in self.enabled_tabs:
                widget = TAB_CLASSES[name](self.ctx)
                self.tabs[name] = widget
                with TabPane(getattr(self.config.tabs, name).title, id=f"pane-{name}"):
                    yield widget
        with Horizontal(id="footer-bar"):
            yield Footer()
            yield Static("", id="footer-right")

    async def on_mount(self) -> None:
        self.set_theme(self.config.general.theme, persist=False)
        wanted = self.initial_tab or self.state.last_tab
        if wanted in self.tabs:
            self.query_one("#tabs", TabbedContent).active = f"pane-{wanted}"
        self.call_after_refresh(self._focus_active_table)
        self.set_interval(self.config.refresh.active_tab_seconds, self._tick_active)
        self.set_interval(self.config.refresh.inactive_tabs_seconds, self._tick_inactive)
        self.set_interval(5, self._update_footer)
        self._update_footer()
        try:
            self.version_text = await self.backend.version()
        except Exception:
            self.version_text = ""

    # -- helpers --------------------------------------------------------------

    @property
    def active_tab_name(self) -> str | None:
        active = self.query_one("#tabs", TabbedContent).active
        return active.removeprefix("pane-") if active else None

    @property
    def active_tab(self) -> Any | None:
        name = self.active_tab_name
        return self.tabs.get(name) if name else None

    def set_theme(self, name: str, persist: bool = True) -> None:
        if name not in self.available_themes:
            log.warning("unknown theme %r, falling back to textual-dark", name)
            name = "textual-dark"
        self.theme = name
        if persist:
            self.state.theme = name
            self.schedule_state_save()

    def set_auto_refresh(self, enabled: bool) -> None:
        self.auto_refresh_on = enabled
        self.state.auto_refresh = enabled
        self.schedule_state_save()
        self._update_footer()

    def update_general(self, **changes: Any) -> None:
        """Apply a change to [general] at runtime (memory unit, duration style)."""
        general = self.config.general.model_copy(update=changes)
        self.config = self.config.model_copy(update={"general": general})
        self.formatter = Formatter(self.config)
        self.ctx.config = self.config
        self.ctx.formatter = self.formatter
        for tab in self.tabs.values():
            if isinstance(tab, TableTab):
                tab.call_later(tab.render_rows)
            else:
                tab.refresh_data(force=False)

    def update_tab_columns(self, name: str, specs: list[ColumnSpec]) -> None:
        tab_config: TableTabConfig = self.config.table_tab(name)
        new_tab = tab_config.model_copy(update={"columns": specs})
        tabs = self.config.tabs.model_copy(update={name: new_tab})
        self.config = self.config.model_copy(update={"tabs": tabs})
        self.ctx.config = self.config
        self.state.tab(name).columns = [spec.model_dump(exclude_none=True) for spec in specs]
        self.schedule_state_save()

    def reset_tab(self, name: str) -> None:
        """Drop the state overrides of a tab and go back to the configured defaults."""
        from slurmtui.config.state import State as _State  # local import keeps module load light
        from slurmtui.config.state import apply_state

        self.state.reset_tab(name)
        base = apply_state(self.base_config, _State(tabs={}))
        tab_config = base.table_tab(name)
        tabs = self.config.tabs.model_copy(update={name: tab_config})
        self.config = self.config.model_copy(update={"tabs": tabs})
        self.ctx.config = self.config
        tab = self.tabs[name]
        from slurmtui.columns.sort import parse_sort

        tab.sort_spec, _ = parse_sort(tab_config.sort, tab.registry)
        tab.set_filter_text(tab_config.filter)
        tab.set_columns(resolve_columns(self.config, name))
        self.schedule_state_save()

    @property
    def base_config(self) -> Config:
        return getattr(self, "_base_config", self.config)

    @base_config.setter
    def base_config(self, value: Config) -> None:
        self._base_config = value

    def schedule_state_save(self) -> None:
        if self._save_timer is not None:
            self._save_timer.stop()
        self._save_timer = self.set_timer(1.0, self._save_state_now)

    def _save_state_now(self) -> None:
        if self.state_path is not None:
            save_state(self.state, self.state_path)

    def _update_footer(self) -> None:
        tab = self.active_tab
        age = ""
        sources: tuple[str, ...] = getattr(tab, "SOURCES", ()) if tab is not None else ()
        if sources:
            name = sources[0]
            if name in self.service.names:
                status = self.service.status(name)
                if status.age is not None:
                    age = f"  data {int(status.age)}s old"
                if status.in_flight:
                    age += "  refreshing…"
        self.query_one("#footer-right", Static).update(f"auto refresh {'ON' if self.auto_refresh_on else 'OFF'}{age}")

    def _focus_active_table(self) -> None:
        tab = self.active_tab
        if isinstance(tab, TableTab):
            tab.focus_table()

    # -- timers ---------------------------------------------------------------

    def _tick_active(self) -> None:
        if self.auto_refresh_on and (tab := self.active_tab) is not None:
            tab.refresh_data(force=True, include_expensive=False)

    def _tick_inactive(self) -> None:
        if not self.auto_refresh_on:
            return
        active = self.active_tab_name
        for name, tab in self.tabs.items():
            if name != active:
                tab.refresh_data(force=True, include_expensive=False)

    @on(TabbedContent.TabActivated, "#tabs")
    def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
        name = event.pane.id.removeprefix("pane-") if event.pane.id else None
        if name is None or name not in self.tabs:
            return
        self.state.last_tab = name
        self.schedule_state_save()
        tab = self.tabs[name]
        if self.config.refresh.on_tab_switch and tab.loaded_once and tab.is_stale():
            tab.refresh_data(force=False)
        self._update_footer()
        self.call_after_refresh(self._focus_active_table)

    # -- actions --------------------------------------------------------------

    def action_refresh(self) -> None:
        if (tab := self.active_tab) is not None:
            tab.refresh_data(force=True)

    def action_refresh_all(self) -> None:
        for tab in self.tabs.values():
            tab.refresh_data(force=True, include_expensive=False)

    def action_toggle_auto_refresh(self) -> None:
        self.set_auto_refresh(not self.auto_refresh_on)
        self.notify(f"Auto refresh {'on' if self.auto_refresh_on else 'off'}", timeout=2)

    def action_focus_filter(self) -> None:
        if (tab := self.active_tab) is not None:
            tab.focus_filter()

    def action_clear_filter(self) -> None:
        if (tab := self.active_tab) is not None:
            tab.clear_filter()

    def _switch_tab(self, offset: int) -> None:
        names = self.enabled_tabs
        current = self.active_tab_name
        if current not in names:
            return
        target = names[(names.index(current) + offset) % len(names)]
        self.query_one("#tabs", TabbedContent).active = f"pane-{target}"

    def action_next_tab(self) -> None:
        self._switch_tab(1)

    def action_prev_tab(self) -> None:
        self._switch_tab(-1)

    def action_my_jobs(self) -> None:
        jobs = self.tabs.get("jobs")
        if isinstance(jobs, JobsTab):
            if self.active_tab_name != "jobs":
                self.query_one("#tabs", TabbedContent).active = "pane-jobs"
            jobs.toggle_my_jobs()

    def show_jobs(self, filter_text: str, origin: str) -> None:
        """Switch to the JOBS tab with ``filter_text``; the current filter can be restored."""
        jobs = self.tabs.get("jobs")
        if not isinstance(jobs, JobsTab):
            self.notify("The JOBS tab is disabled", severity="warning", timeout=3)
            return
        if self.active_tab_name != "jobs":
            self.query_one("#tabs", TabbedContent).active = "pane-jobs"
        jobs.push_filter(filter_text, origin)

    def action_restore_filter(self) -> None:
        jobs = self.active_tab
        if isinstance(jobs, JobsTab) and not jobs.restore_filter():
            self.notify("No previous filter", timeout=2)

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen(self))

    def action_help(self) -> None:
        tab = self.active_tab
        columns = getattr(tab, "registry", {}) if tab is not None else {}
        title = getattr(self.config.tabs, self.active_tab_name).title if self.active_tab_name else ""
        self.push_screen(HelpScreen(self.config.keys, title, columns, self.version_text or __version__))

    def action_sort_dialog(self) -> None:
        tab = self.active_tab
        if not isinstance(tab, TableTab):
            return

        def apply(spec: Any) -> None:
            if spec is not None:
                tab.set_sort(spec)

        self.push_screen(SortDialog(tab.sort_spec, tab.registry), callback=apply)

    def action_close(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()
            return
        focused = self.focused
        tab = self.active_tab
        if isinstance(focused, Input) and isinstance(tab, TableTab):
            tab.table.focus()
        elif isinstance(tab, JobsTab):
            tab.restore_filter()


def create_app(
    config: Config,
    backend: SlurmBackend,
    service: DataService,
    state: State,
    *,
    base_config: Config | None = None,
    state_path: Path | None = None,
    config_files: Sequence[Path] = (),
    initial_tab: str | None = None,
) -> SlurmTuiApp:
    """Build an app class whose BINDINGS come from the configuration."""
    cls: type[SlurmTuiApp] = type("SlurmTuiApp", (SlurmTuiApp,), {"BINDINGS": make_bindings(config.keys)})
    app = cls(
        config,
        backend,
        service,
        state,
        state_path=state_path,
        config_files=config_files,
        initial_tab=initial_tab,
    )
    app.base_config = base_config or config
    return app
