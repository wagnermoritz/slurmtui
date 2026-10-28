"""USERS tab."""

from __future__ import annotations

from typing import Any

from slurmtui.columns.table import TableData
from slurmtui.data import aggregate
from slurmtui.model.records import UserRow
from slurmtui.ui.screens.detail import DetailSpec, Section
from slurmtui.ui.tabs.base import TableTab
from slurmtui.ui.tabs.common import jobs_overview, shares_table


class UsersTab(TableTab):
    TAB = "users"
    SOURCES = ("jobs", "shares", "recent_jobs")

    async def load_records(self, force: bool, include_expensive: bool) -> list[Any]:
        service = self.ctx.service
        jobs = await service.get("jobs", force=force)
        shares = await service.get("shares", force=force)
        recent = None
        if service.is_enabled("recent_jobs"):
            recent = await service.get("recent_jobs", force=force and include_expensive)
        return aggregate.users(jobs, shares, recent)

    def key_of(self, record: Any) -> str:
        return str(record.user)

    def status_text(self, data: TableData) -> str:
        return f"{data.matched} active users"

    def detail_spec(self, record: Any) -> DetailSpec | None:
        row: UserRow = record

        async def load() -> list[Section]:
            jobs = await self.ctx.service.get("jobs")
            shares = await self.ctx.service.get("shares")
            return [
                Section(
                    "Jobs by partition",
                    jobs_overview(
                        aggregate.jobs_of_user(jobs, row.user), self.formatter, lambda job: job.partition, "Partition"
                    ),
                ),
                Section("Fairshare", shares_table(entry for entry in shares if entry.user == row.user)),
            ]

        actions, on_action = self.show_jobs_action(f"user={row.user}", f"jobs of user {row.user}")
        return DetailSpec(title=f"User {row.user}", loader=load, actions=actions, on_action=on_action)
