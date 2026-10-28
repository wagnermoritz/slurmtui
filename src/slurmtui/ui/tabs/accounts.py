"""ACCOUNTS tab."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from textual.widgets import Input

from slurmtui.columns.table import TableData
from slurmtui.data import aggregate
from slurmtui.model.records import AccountRow
from slurmtui.ui.context import TabContext
from slurmtui.ui.screens.detail import DetailSpec, Section
from slurmtui.ui.tabs.base import TableTab
from slurmtui.ui.tabs.common import jobs_overview, resolve_window, shares_table
from slurmtui.units import parse_window


class AccountsTab(TableTab):
    TAB = "accounts"
    SOURCES = ("shares", "jobs", "account_usage")

    def __init__(self, ctx: TabContext) -> None:
        super().__init__(ctx)
        self.usage_enabled = ctx.service.is_enabled("account_usage")
        self.window_text = ctx.state.tab(self.TAB).window or ""

    def extra_inputs(self) -> Iterable[Input]:
        if self.usage_enabled:
            default = self.ctx.config.sources.account_usage.default_window
            yield Input(
                value=self.window_text,
                placeholder=f"usage window ({default}), e.g. 12h, 3d, 2w",
                id="accounts-window",
                classes="extra-input",
            )

    def extra_input_submitted(self, input_id: str, value: str) -> None:
        if input_id == "accounts-window":
            self.window_text = value
            self.ctx.state.tab(self.TAB).window = value
            self.ctx.persist()
            self.refresh_data(force=False)

    async def load_records(self, force: bool, include_expensive: bool) -> list[Any]:
        service = self.ctx.service
        shares = await service.get("shares", force=force)
        jobs = await service.get("jobs", force=force)
        usage = None
        self.note = None
        if self.usage_enabled:
            cfg = self.ctx.config.sources.account_usage
            window, note = resolve_window(self.window_text, cfg.default_window, cfg.max_window)
            self.note = note
            records = await service.get("account_usage", window, force=force and include_expensive)
            delta = parse_window(window)
            assert delta is not None
            usage = aggregate.usage_hours(records, self.ctx.deriver, datetime.now() - delta)
            self.note = f"usage window {window}" + (f"  ({note})" if note else "")
        return aggregate.accounts(shares, jobs, usage)

    def key_of(self, record: Any) -> str:
        return str(record.account)

    def status_text(self, data: TableData) -> str:
        return f"{data.matched} accounts"

    def detail_spec(self, record: Any) -> DetailSpec | None:
        row: AccountRow = record

        async def load() -> list[Section]:
            shares = await self.ctx.service.get("shares")
            jobs = await self.ctx.service.get("jobs")
            return [
                Section(
                    "Jobs by user",
                    jobs_overview(
                        aggregate.jobs_of_account(jobs, row.account), self.formatter, lambda job: job.user, "User"
                    ),
                ),
                Section(
                    "Fairshare by user",
                    shares_table(entry for entry in shares if entry.account == row.account),
                ),
            ]

        actions, on_action = self.show_jobs_action(f"account={row.account}", f"jobs of account {row.account}")
        return DetailSpec(title=f"Account {row.account}", loader=load, actions=actions, on_action=on_action)
