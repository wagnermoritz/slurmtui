"""Shared objects every tab and screen needs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from slurmtui.columns.format import Formatter
from slurmtui.config.schema import Config
from slurmtui.config.state import State
from slurmtui.data.service import DataService
from slurmtui.model.derive import Deriver
from slurmtui.slurm.backend import SlurmBackend


@dataclass
class TabContext:
    config: Config
    backend: SlurmBackend
    service: DataService
    state: State
    persist: Callable[[], None]
    formatter: Formatter
    deriver: Deriver

    @property
    def whoami(self) -> str:
        return self.backend.whoami()
