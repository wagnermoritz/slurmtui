"""CLUSTER tab: one overview per node group."""

from __future__ import annotations

import logging

from rich import box
from rich.console import Group, RenderableType
from rich.markup import escape
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static, TabbedContent, TabPane

from slurmtui.config.schema import style_for_state
from slurmtui.data import aggregate
from slurmtui.data.service import SourceError
from slurmtui.model.records import GroupOverview, SchedulerStats
from slurmtui.model.states import NodeState
from slurmtui.ui.context import TabContext
from slurmtui.ui.widgets import StatusLine, section, usage_bar

log = logging.getLogger(__name__)


class ClusterTab(Vertical):
    TAB = "cluster"
    SOURCES = ("nodes", "jobs", "reservations", "scheduler")

    def __init__(self, ctx: TabContext) -> None:
        super().__init__(id="tab-cluster")
        self.ctx = ctx
        self.cfg = ctx.config.tabs.cluster
        self.loaded_once = False

    def compose(self) -> ComposeResult:
        yield StatusLine("", id="cluster-status", classes="status-line")
        with TabbedContent(id="cluster-groups"):
            for name in self.ctx.config.group_names:
                with TabPane(name, id=f"group-{_safe(name)}"):
                    yield VerticalScroll(
                        Static(Text("Loading…", style="dim"), id=f"group-{_safe(name)}-text"),
                        classes="cluster-scroll",
                    )

    def on_mount(self) -> None:
        self.refresh_data(force=False)

    def is_stale(self) -> bool:
        return any(not self.ctx.service.is_fresh(name) for name in self.SOURCES if self.ctx.service.is_enabled(name))

    def focus_filter(self) -> None:
        return None

    def clear_filter(self) -> None:
        return None

    @work(exclusive=True, group="refresh")
    async def refresh_data(self, force: bool = True, include_expensive: bool = True) -> None:
        service = self.ctx.service
        errors: list[str] = []
        try:
            nodes = await service.get("nodes", force=force)
            jobs = await service.get("jobs", force=force)
        except SourceError as exc:
            self.query_one(StatusLine).set_status("", str(exc))
            return
        reservations = []
        if service.is_enabled("reservations"):
            try:
                reservations = await service.get("reservations", force=force)
            except SourceError as exc:
                errors.append(f"reservations: {exc}")
        stats: SchedulerStats | None = None
        if service.is_enabled("scheduler"):
            try:
                stats = await service.get("scheduler", force=force)
            except SourceError as exc:
                errors.append(f"scheduler: {exc}")
        overviews = aggregate.cluster_overview(
            nodes, jobs, reservations, self.ctx.config.group_names, self.ctx.config.ungrouped_name
        )
        tabs = self.query_one("#cluster-groups", TabbedContent)
        for name, overview in overviews.items():
            pane_id = f"group-{_safe(name)}"
            if not tabs.query(f"#{pane_id}"):
                await tabs.add_pane(
                    TabPane(
                        name,
                        VerticalScroll(Static(id=f"{pane_id}-text"), classes="cluster-scroll"),
                        id=pane_id,
                    )
                )
            self.query_one(f"#{pane_id}-text", Static).update(self.render_group(overview, stats))
        self.loaded_once = True
        updated = service.status("nodes").updated_at
        total = sum(view.node_total for view in overviews.values())
        running = sum(view.running for view in overviews.values())
        pending = sum(view.pending for view in overviews.values())
        self.query_one(StatusLine).set_status(
            f"{total} nodes  │  running {running}  pending {pending}", "; ".join(errors) or None, updated
        )

    # -- rendering ------------------------------------------------------------

    def render_group(self, view: GroupOverview, stats: SchedulerStats | None) -> RenderableType:
        fmt = self.ctx.formatter
        style = self.ctx.config.styles
        panels: list[RenderableType] = []
        label_width = max((len(bar.label) for bar in [*view.gpus, *view.cpus]), default=6)
        for panel in self.cfg.panels:
            if panel == "gpus":
                bars = [usage_bar(b.label, b.used, b.total, label_width, style.usage_bar) for b in view.gpus]
                panels.append(section("GPUs", Group(*bars) if bars else Text("  none", style="dim")))
            elif panel == "cpus":
                bars = [usage_bar(b.label, b.used, b.total, label_width, style.usage_bar) for b in view.cpus]
                panels.append(section("CPUs", Group(*bars) if bars else Text("  none", style="dim")))
            elif panel == "memory":
                mem = view.memory
                bar = usage_bar(
                    "memory",
                    mem.used,
                    mem.total,
                    label_width,
                    style.usage_bar,
                    suffix=f"{fmt.memory(mem.used)}/{fmt.memory(mem.total)}",
                )
                panels.append(section("Memory", bar))
            elif panel == "nodes":
                lines = Text()
                for state_text, count in view.node_states.items():
                    state = NodeState.parse(state_text)
                    state_style = style_for_state(style.node_state, state.style_key)
                    for flag in state.flag_style_keys:
                        if flag in style.node_state_flags:
                            state_style = f"{state_style} {style.node_state_flags[flag]}".strip()
                            break
                    lines.append("  ")
                    lines.append(f"{state_text:<12}", style=state_style)
                    lines.append(f" {count}\n")
                lines.rstrip()
                panels.append(section(f"Nodes ({view.node_total} total)", lines or Text("  none", style="dim")))
            elif panel == "jobs":
                text = Text("  ")
                text.append("running", style="green")
                text.append(f" {view.running}   ")
                text.append("pending", style="yellow")
                text.append(f" {view.pending}\n")
                if view.pending_reasons:
                    text.append("  pending by reason:\n", style="dim")
                    top = view.pending_reasons[: self.cfg.pending_reasons_shown]
                    width = max(len(reason) for reason, _ in top)
                    for reason, count in top:
                        text.append(f"    {reason:<{width}} {count}\n")
                text.rstrip()
                panels.append(section("Jobs", text))
            elif panel == "reservations":
                panels.append(section("Reservations", self._reservations(view)))
            elif panel == "scheduler":
                panels.append(section("Scheduler (whole cluster)", self._scheduler(stats)))
        return Group(*panels)

    def _reservations(self, view: GroupOverview) -> RenderableType:
        if not view.reservations:
            return Text("  none", style="dim")
        table = Table(box=box.SIMPLE_HEAD, header_style="bold", expand=True, pad_edge=False)
        for column in ("Name", "State", "Start", "End", "Users / accounts"):
            table.add_column(column, no_wrap=True)
        table.add_column("Nodes", overflow="fold", ratio=1)
        fmt = self.ctx.formatter
        for res in sorted(view.reservations, key=lambda item: (not item.is_active, item.start or 0)):
            who = ",".join(res.users) or ",".join(res.accounts) or "-"
            table.add_row(
                escape(res.name),
                Text(res.state, style="green" if res.is_active else "yellow"),
                fmt.when(res.start),
                fmt.when(res.end),
                who,
                Text(res.node_spec, overflow="fold"),
            )
        return table

    def _scheduler(self, stats: SchedulerStats | None) -> RenderableType:
        if stats is None:
            return Text("  not available", style="dim")

        def ms(value: int | None) -> str:
            return f"{value / 1000:.1f} ms" if value is not None else "-"

        def num(value: int | None) -> str:
            return str(value) if value is not None else "-"

        lines = [
            f"  queue length {num(stats.queue_length)}   mean cycle {ms(stats.mean_cycle_us)}   "
            f"last cycle {ms(stats.last_cycle_us)}   max cycle {ms(stats.max_cycle_us)}",
            f"  backfilled since start {num(stats.backfill_total_jobs)}   last backfill cycle "
            f"{num(stats.backfill_last_cycle_jobs)} jobs in {ms(stats.backfill_last_cycle_us)}   "
            f"mean backfill cycle {ms(stats.backfill_mean_cycle_us)}",
            f"  jobs since {self.ctx.formatter.when(stats.data_since)}: submitted {num(stats.jobs_submitted)}   "
            f"started {num(stats.jobs_started)}   completed {num(stats.jobs_completed)}   "
            f"canceled {num(stats.jobs_canceled)}   failed {num(stats.jobs_failed)}",
        ]
        return Text("\n".join(lines))

    @on(TabbedContent.TabActivated)
    def _subtab(self, event: TabbedContent.TabActivated) -> None:
        event.stop()


def _safe(name: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
