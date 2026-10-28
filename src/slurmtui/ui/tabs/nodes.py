"""NODES tab."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from textual.widgets import Input

from slurmtui.columns.table import TableData
from slurmtui.data import aggregate
from slurmtui.data.service import SourceError
from slurmtui.model.records import Node
from slurmtui.slurm.parsers import hostlist
from slurmtui.ui.context import TabContext
from slurmtui.ui.screens.detail import DetailSpec, Section
from slurmtui.ui.tabs.base import TableTab
from slurmtui.ui.tabs.common import jobs_overview


class NodesTab(TableTab):
    TAB = "nodes"
    SOURCES = ("nodes", "partitions", "jobs")

    def __init__(self, ctx: TabContext) -> None:
        super().__init__(ctx)
        self.partitions_text: str = getattr(self.tab_config, "partitions", "")
        self.all_nodes: list[Node] = []

    def extra_inputs(self) -> Iterable[Input]:
        yield Input(
            value=self.partitions_text,
            placeholder="partition(s), comma-separated",
            id="nodes-partitions",
            classes="extra-input",
        )

    def extra_input_submitted(self, input_id: str, value: str) -> None:
        if input_id == "nodes-partitions":
            self.partitions_text = value
            self.ctx.state.tab(self.TAB).partitions = value
            self.ctx.persist()
            self.refresh_data(force=False)

    @property
    def selected_partitions(self) -> list[str]:
        return [part.strip() for part in self.partitions_text.split(",") if part.strip()]

    async def load_records(self, force: bool, include_expensive: bool) -> list[Any]:
        nodes = await self.ctx.service.get("nodes", force=force)
        try:
            jobs = await self.ctx.service.get("jobs", force=force)
        except SourceError:  # reported in the status line
            jobs = []
        self.all_nodes = aggregate.with_job_counts(nodes, jobs)
        selected = self.selected_partitions
        if not selected:
            return list(self.all_nodes)
        wanted = set(selected)
        return [node for node in self.all_nodes if wanted.intersection(node.partitions)]

    def key_of(self, record: Any) -> str:
        return str(record.name)

    def status_text(self, data: TableData) -> str:
        selected = self.selected_partitions
        if not selected:
            return "all partitions"
        shown = {node.name for node in data.matched_records}
        excluded = [node.name for node in self.records if node.name not in shown]
        label = ",".join(selected)
        if excluded:
            return f"other nodes in {label}: {hostlist.contract(excluded, sep=', ')}"
        return f"partition(s) {label}"

    def detail_spec(self, record: Any) -> DetailSpec | None:
        node: Node = record

        async def load() -> list[Section]:
            sections: list[Section] = []
            if node.reason is not None:
                who = f" (set by {node.reason.user}" if node.reason.user else ""
                when = (
                    f", {self.formatter.when(node.reason.time)})" if node.reason.time and who else (")" if who else "")
                )
                sections.append(Section("Reason", f"{node.reason.text}{who}{when}"))
            jobs = await self.ctx.service.get("jobs")
            overview = jobs_overview(
                aggregate.jobs_on_node(jobs, node.name), self.formatter, lambda job: job.user, "User"
            )
            sections.append(Section("Jobs on this node", overview))
            text = await self.ctx.backend.node_detail(node.name)
            sections.append(Section("scontrol show node", text.rstrip()))
            return sections

        title = f"Node {node.name}  [{node.state.compact}]  {node.cpu_type}"
        if node.gpu_type:
            title += f"  {node.gpu_type}"
        actions, on_action = self.show_jobs_action(f"node_list={node.name}", f"jobs on node {node.name}")
        return DetailSpec(title=title, loader=load, actions=actions, on_action=on_action)
