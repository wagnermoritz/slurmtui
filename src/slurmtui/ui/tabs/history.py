"""HISTORY tab: the user's own jobs from the accounting database."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from textual.widgets import Input

from slurmtui.columns.table import TableData
from slurmtui.data.files import tail_file
from slurmtui.model.output import expand_output_pattern
from slurmtui.model.records import JobRecord
from slurmtui.ui.context import TabContext
from slurmtui.ui.screens.detail import DetailSpec, Section
from slurmtui.ui.tabs.base import TableTab
from slurmtui.ui.tabs.common import resolve_window


class HistoryTab(TableTab):
    TAB = "history"
    SOURCES = ("history",)

    def __init__(self, ctx: TabContext) -> None:
        super().__init__(ctx)
        self.window_text: str = getattr(self.tab_config, "window", "") or ""
        self.window_used = ctx.config.sources.history.default_window

    def extra_inputs(self) -> Iterable[Input]:
        default = self.ctx.config.sources.history.default_window
        yield Input(
            value=self.window_text,
            placeholder=f"look back ({default}), e.g. 12h, 3d, 2w",
            id="history-window",
            classes="extra-input",
        )

    def extra_input_submitted(self, input_id: str, value: str) -> None:
        if input_id == "history-window":
            self.window_text = value
            self.ctx.state.tab(self.TAB).window = value
            self.ctx.persist()
            self.refresh_data(force=False)

    async def load_records(self, force: bool, include_expensive: bool) -> list[Any]:
        cfg = self.ctx.config.sources.history
        window, note = resolve_window(self.window_text, cfg.default_window, cfg.max_window)
        self.window_used = window
        self.note = note
        return list(await self.ctx.service.get("history", window, force=force))

    def primary_params(self) -> tuple[Any, ...]:
        return (self.window_used,)

    def key_of(self, record: Any) -> str:
        return str(record.job_id)

    def status_text(self, data: TableData) -> str:
        return f"{data.matched} jobs of {self.ctx.whoami} in the last {self.window_used}"

    def detail_spec(self, record: Any) -> DetailSpec | None:
        job: JobRecord = record

        async def load() -> list[Section]:
            sections: list[Section] = []
            summary = None
            if self.ctx.config.detail.use_seff:
                summary = await self.ctx.backend.job_efficiency(job.raw_id)
            if summary:
                sections.append(Section("seff", summary))
            else:
                fmt = self.formatter
                lines = [
                    f"State: {job.state} (exit {job.exit_code})",
                    f"Partition: {job.partition}   Account: {job.account}",
                    f"Elapsed: {fmt.duration(job.elapsed)}   Limit: {fmt.duration(job.time_limit)}",
                    f"CPUs: {job.alloc_cpus}   GPUs: {job.gpus}   Nodes: {', '.join(job.node_list) or '-'}",
                    f"Requested memory: {fmt.memory(job.req_mem)}   Max RSS: {fmt.memory(job.max_rss)}",
                    f"Memory efficiency: {fmt.text(self.registry['mem_eff'], job.mem_eff)}"
                    f"   CPU efficiency: {fmt.text(self.registry['cpu_eff'], job.cpu_eff)}",
                    f"Submitted: {fmt.when(job.submit)}   Start: {fmt.when(job.start)}   End: {fmt.when(job.end)}",
                ]
                sections.append(Section("Summary", "\n".join(lines)))
            if job.stdout:
                path = expand_output_pattern(job.stdout, job)
                tail = await asyncio.to_thread(tail_file, path, self.ctx.config.detail)
                sections.append(Section(f"Last {self.ctx.config.detail.stdout_tail_lines} lines of {path}", tail))
            return sections

        return DetailSpec(title=f"Job {job.job_id}  {job.name}  [{job.state}]", loader=load)
