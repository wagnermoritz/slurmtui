"""JOBS tab."""

from __future__ import annotations

import asyncio
from typing import Any

from slurmtui.columns.table import TableData
from slurmtui.data import aggregate
from slurmtui.data.files import tail_file
from slurmtui.model.output import expand_output_pattern, stdout_from_detail
from slurmtui.model.records import Job
from slurmtui.ui.context import TabContext
from slurmtui.ui.screens.detail import Action, ActionOutcome, DetailSpec, Section
from slurmtui.ui.tabs.base import TableTab


class JobsTab(TableTab):
    TAB = "jobs"
    SOURCES = ("jobs",)

    def __init__(self, ctx: TabContext) -> None:
        super().__init__(ctx)
        # filters replaced by a detail's "Show in JOBS": (previous filter text, what is shown now)
        self.filter_stack: list[tuple[str, str]] = []

    async def load_records(self, force: bool, include_expensive: bool) -> list[Any]:
        return list(await self.ctx.service.get("jobs", force=force))

    def key_of(self, record: Any) -> str:
        return str(record.job_id)

    def status_text(self, data: TableData) -> str:
        running, pending, other = aggregate.job_counts(data.matched_records)
        text = f"running {running}  pending {pending}" + (f"  other {other}" if other else "")
        if "@me" in self.filter_text.split():
            text += "  (your jobs)"
        if self.filter_stack:
            keys = self.ctx.config.keys.restore_filter
            hint = f"  ({keys[0]} restores the previous filter)" if keys else ""
            text += f"  │  {self.filter_stack[-1][1]}{hint}"
        return text

    def push_filter(self, text: str, origin: str) -> None:
        """Replace the filter, remembering the current one so it can be restored."""
        self.filter_stack.append((self.filter_text, origin))
        self.set_filter_text(text)

    def restore_filter(self) -> bool:
        if not self.filter_stack:
            return False
        previous, _ = self.filter_stack.pop()
        self.set_filter_text(previous)
        return True

    def toggle_my_jobs(self) -> None:
        terms = self.filter_text.split()
        if "@me" in terms:
            terms = [term for term in terms if term != "@me"]
        else:
            terms = ["@me", *terms]
        self.set_filter_text(" ".join(terms))

    def detail_spec(self, record: Any) -> DetailSpec | None:
        job: Job = record
        mine = job.user == self.ctx.whoami

        async def load() -> list[Section]:
            text = await self.ctx.backend.job_detail(job.command_id)
            sections = [Section("scontrol show job", text.rstrip())]
            if job.stdout and job.is_running:
                # scontrol prints the path with %j/%A/%a expanded; squeue reports it as submitted
                path = stdout_from_detail(text) or expand_output_pattern(job.stdout, job)
                tail = await asyncio.to_thread(tail_file, path, self.ctx.config.detail)
                sections.append(Section(f"Last {self.ctx.config.detail.stdout_tail_lines} lines of {path}", tail))
            return sections

        async def on_action(action_id: str) -> ActionOutcome:
            backend = self.ctx.backend
            result = await {"hold": backend.hold, "release": backend.release, "cancel": backend.cancel}[action_id](
                job.command_id
            )
            self.ctx.service.invalidate("jobs")
            self.refresh_data(force=True)
            return ActionOutcome(message=f"{result.command}: {result.output}", ok=result.ok, reload=True)

        actions = []
        if mine:
            actions = [
                Action("hold", "Hold"),
                Action("release", "Release"),
                Action("cancel", "Cancel job", confirm=f"Cancel job {job.job_id} ({job.name})?", variant="error"),
            ]
        return DetailSpec(
            title=f"Job {job.job_id}  {job.name}  [{job.state}]  {job.user}@{job.partition}",
            loader=load,
            actions=actions,
            on_action=on_action if mine else None,
        )
