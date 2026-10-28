from __future__ import annotations

import json
import os

import pytest
from textual.widgets import DataTable, Input, Select, SelectionList, TabbedContent

from slurmtui.app import create_app
from slurmtui.columns.sort import cycle_sort
from slurmtui.config.state import State
from slurmtui.ui.screens.detail import DetailScreen
from slurmtui.ui.screens.help import HelpScreen
from slurmtui.ui.screens.settings import SettingsScreen
from slurmtui.ui.screens.sort_dialog import SortDialog


def make_app(demo_config, backend, service, state_path):
    return create_app(demo_config, backend, service, State(), state_path=state_path)


def static_text(widget) -> str:
    content = widget.content
    if hasattr(content, "plain"):
        return content.plain
    if isinstance(content, str):
        return content
    from rich.console import Console

    with open(os.devnull, "w") as sink:
        console = Console(width=200, record=True, file=sink)
        console.print(content)
        return console.export_text()


async def activate(app, pilot, name):
    app.query_one("#tabs", TabbedContent).active = f"pane-{name}"
    await pilot.pause(0.5)
    return app.tabs[name]


@pytest.mark.parametrize("tab", ["nodes", "jobs", "users", "accounts", "history"])
async def test_table_tabs_render(demo_config, backend, service, tmp_state_path, tab):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        widget = await activate(app, pilot, tab)
        table = widget.query_one(DataTable)
        assert table.row_count > 0
        assert len(table.columns) == len(widget.columns)
        assert "rows" in static_text(widget.status_line)


async def test_cluster_tab_renders_groups(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        widget = await activate(app, pilot, "cluster")
        groups = widget.query_one("#cluster-groups", TabbedContent)
        assert {pane.id for pane in groups.query("TabPane")} == {"group-z3", "group-GCP"}
        text = static_text(widget.query_one("#group-z3-text"))
        assert "A40 48GB" in text or "GPUs" in text


async def test_single_click_opens_detail(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        jobs = await activate(app, pilot, "jobs")
        table = jobs.query_one(DataTable)
        await pilot.click("#jobs-table", offset=(10, 4))  # border + header, then body row 2
        await pilot.pause(0.5)
        assert table.cursor_coordinate.row == 2
        assert isinstance(app.screen, DetailScreen)
        await app.pop_screen()
        await pilot.pause(0.3)
        assert not isinstance(app.screen, DetailScreen)
        await pilot.click("#jobs-table", offset=(10, 1))  # header: sorts, no detail
        await pilot.pause(0.5)
        assert not isinstance(app.screen, DetailScreen)


async def test_filter_sort_and_detail(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        jobs = await activate(app, pilot, "jobs")
        total = jobs.query_one(DataTable).row_count
        jobs.set_filter_text("state=running gpus>0")
        await pilot.pause(0.6)
        filtered = jobs.query_one(DataTable).row_count
        assert 0 < filtered < total
        assert all(row.record.state == "RUNNING" and row.record.gpus > 0 for row in jobs.table_data.rows)
        jobs.set_filter_text("nope=1")
        await pilot.pause(0.3)
        assert jobs.filter_error and jobs.query_one(DataTable).row_count == filtered  # previous filter kept
        jobs.set_filter_text("")
        await pilot.pause(0.6)
        jobs.set_sort(cycle_sort([], "priority"))
        await pilot.pause(0.5)
        priorities = [row.record.priority for row in jobs.table_data.rows]
        assert priorities == sorted(priorities)
        jobs.set_sort(cycle_sort(jobs.sort_spec, "priority"))
        await pilot.pause(0.5)
        priorities = [row.record.priority for row in jobs.table_data.rows]
        assert priorities == sorted(priorities, reverse=True)
        jobs.query_one(DataTable).focus()
        await pilot.press("enter")
        await pilot.pause(0.8)
        assert isinstance(app.screen, DetailScreen)
        texts = [static_text(w) for w in app.screen.query_one("#detail-body").query("Static")]
        assert any("JobId=" in text for text in texts)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, DetailScreen)


async def test_actions_only_for_own_jobs(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        jobs = await activate(app, pilot, "jobs")
        jobs.set_filter_text("@me state=pending")
        await pilot.pause(0.6)
        table = jobs.query_one(DataTable)
        table.focus()
        await pilot.press("enter")
        await pilot.pause(0.8)
        labels = {str(button.label) for button in app.screen.query("Button")}
        assert {"Hold", "Release", "Cancel job", "Close"} <= labels
        hold = next(button for button in app.screen.query("Button") if str(button.label) == "Hold")
        await pilot.click(hold)
        await pilot.pause(0.8)
        assert "OK" in static_text(app.screen.query_one("#detail-message"))
        await pilot.press("escape")
        await pilot.pause(0.3)
        jobs.set_filter_text("user!=demo")
        await pilot.pause(0.6)
        table.focus()
        await pilot.press("enter")
        await pilot.pause(0.8)
        labels = {str(button.label) for button in app.screen.query("Button")}
        assert labels == {"Close"}
        await pilot.press("escape")


async def test_nodes_partition_input_lists_other_nodes(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        nodes = await activate(app, pilot, "nodes")
        nodes.extra_input_submitted("nodes-partitions", "gpu")
        await pilot.pause(0.8)
        assert all("gpu" in row.record.partitions for row in nodes.table_data.rows)
        nodes.set_filter_text("state=drng,drain,down")
        await pilot.pause(0.6)
        status = static_text(nodes.status_line)
        assert "other nodes in gpu" in status and "htc-gpu[" in status


async def test_status_line_wraps(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(60, 40)) as pilot:
        nodes = await activate(app, pilot, "nodes")
        nodes.extra_input_submitted("nodes-partitions", "gpu")
        await pilot.pause(0.8)
        nodes.set_filter_text("state=drng,drain,down")
        await pilot.pause(0.6)
        status = nodes.status_line
        assert len(static_text(status)) > status.size.width
        assert status.size.height >= 2
        table_top = nodes.query_one(DataTable).region.y
        assert table_top >= status.region.y + status.size.height


async def test_detail_show_in_jobs_and_restore(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        jobs = await activate(app, pilot, "jobs")
        jobs.set_filter_text("state=pending")
        await pilot.pause(0.6)
        nodes = await activate(app, pilot, "nodes")
        nodes.set_filter_text("state=mix,alloc")
        await pilot.pause(0.6)
        nodes.query_one(DataTable).focus()
        await pilot.press("enter")
        await pilot.pause(0.8)
        assert isinstance(app.screen, DetailScreen)
        node = app.screen.spec.title.split()[1]
        texts = [static_text(w) for w in app.screen.query_one("#detail-body").query("Static")]
        assert any("running" in text and "User" in text for text in texts)
        button = next(button for button in app.screen.query("Button") if str(button.label) == "Show in JOBS")
        await pilot.click(button)
        await pilot.pause(1.0)
        assert not isinstance(app.screen, DetailScreen)
        assert app.active_tab_name == "jobs"
        assert jobs.filter_text == f"node_list={node}"
        assert jobs.table_data.rows and all(node in row.record.node_list for row in jobs.table_data.rows)
        assert f"jobs on node {node}" in static_text(jobs.status_line)
        await pilot.press("ctrl+z")
        await pilot.pause(0.6)
        assert jobs.filter_text == "state=pending"
        assert jobs.filter_input.value == "state=pending"
        assert "jobs on node" not in static_text(jobs.status_line)
        users = await activate(app, pilot, "users")
        users.query_one(DataTable).focus()
        await pilot.press("enter")
        await pilot.pause(0.8)
        user = app.screen.spec.title.split()[1]
        button = next(button for button in app.screen.query("Button") if str(button.label) == "Show in JOBS")
        await pilot.click(button)
        await pilot.pause(1.0)
        assert jobs.filter_text == f"user={user}"
        await pilot.press("escape")  # escape on the JOBS table restores the filter too
        await pilot.pause(0.6)
        assert jobs.filter_text == "state=pending"


async def test_dialogs_and_state_persistence(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        jobs = await activate(app, pilot, "jobs")
        await pilot.press("ctrl+o")
        await pilot.pause(0.3)
        assert isinstance(app.screen, SortDialog)
        app.screen.query_one(Input).value = "user, time desc"
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert jobs.sort_spec == [("user", "asc"), ("time", "desc")]
        await pilot.press("question_mark")
        await pilot.pause(0.4)
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        await pilot.press("ctrl+s")
        await pilot.pause(0.8)
        assert isinstance(app.screen, SettingsScreen)
        app.screen.query_one("#set-memory-unit", Select).value = "M"
        await pilot.pause(0.5)
        assert app.config.general.memory_unit == "M"
        app.screen.query_one("#cols-jobs", SelectionList).deselect("priority")
        await pilot.pause(0.5)
        assert "priority" not in [column.key for column in jobs.columns]
        await pilot.press("escape")
        await pilot.pause(1.5)
        saved = json.loads(tmp_state_path.read_text())
        assert saved["tabs"]["jobs"]["sort"] == "user, time desc"
        assert "priority" not in [column["key"] for column in saved["tabs"]["jobs"]["columns"]]


async def test_my_jobs_toggle_and_tab_cycling(demo_config, backend, service, tmp_state_path):
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await activate(app, pilot, "nodes")
        await pilot.press("ctrl+n")
        await pilot.pause(0.6)
        assert app.active_tab_name == "jobs"
        assert app.tabs["jobs"].filter_text.split() == ["@me"]
        await pilot.press("ctrl+right")
        await pilot.pause(0.3)
        assert app.active_tab_name == "users"
        await pilot.press("ctrl+left")
        await pilot.pause(0.3)
        assert app.active_tab_name == "jobs"


async def test_table_columns_have_explicit_widths(demo_config, backend, service, tmp_state_path):
    """Auto widths left rows painted before the idle measurement narrower than the rest."""
    app = make_app(demo_config, backend, service, tmp_state_path)
    async with app.run_test(size=(140, 40)) as pilot:
        widget = await activate(app, pilot, "nodes")
        table = widget.query_one(DataTable)
        assert table.row_count > 0
        for column in table.columns.values():
            assert not column.auto_width
            assert column.width >= column.label.cell_len
        name_column = table.columns[next(iter(table.columns))]
        longest = max(len(row.record.name) for row in widget.table_data.rows)
        assert name_column.width >= longest
