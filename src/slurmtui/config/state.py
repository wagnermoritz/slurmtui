"""UI state the application changes itself, persisted as JSON on top of the configuration.

Keys: theme, auto refresh, the active tab and per tab sort, filter, columns,
partitions and window. "Reset to config" removes a tab's entry.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from slurmtui.config.loader import xdg_state_home
from slurmtui.config.schema import TABLE_TABS, Config

log = logging.getLogger(__name__)

STATE_VERSION = 1
STATE_ENV = "SLURMTUI_STATE"


def default_state_path() -> Path:
    override = os.environ.get(STATE_ENV)
    return Path(override) if override else xdg_state_home() / "slurmtui" / "state.json"


def default_log_path() -> Path:
    return xdg_state_home() / "slurmtui" / "slurmtui.log"


@dataclass
class TabState:
    sort: str | None = None
    filter: str | None = None
    columns: list[dict[str, Any]] | None = None
    partitions: str | None = None
    window: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if value is not None}

    def is_empty(self) -> bool:
        return not self.to_dict()


@dataclass
class State:
    theme: str | None = None
    auto_refresh: bool | None = None
    last_tab: str | None = None
    tabs: dict[str, TabState] = field(default_factory=dict)

    def tab(self, name: str) -> TabState:
        return self.tabs.setdefault(name, TabState())

    def reset_tab(self, name: str) -> None:
        self.tabs.pop(name, None)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"version": STATE_VERSION}
        if self.theme is not None:
            data["theme"] = self.theme
        if self.auto_refresh is not None:
            data["auto_refresh"] = self.auto_refresh
        if self.last_tab is not None:
            data["last_tab"] = self.last_tab
        tabs = {name: tab.to_dict() for name, tab in self.tabs.items() if not tab.is_empty()}
        if tabs:
            data["tabs"] = tabs
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        state = cls(
            theme=data.get("theme"),
            auto_refresh=data.get("auto_refresh"),
            last_tab=data.get("last_tab"),
        )
        for name, tab_data in (data.get("tabs") or {}).items():
            if not isinstance(tab_data, dict):
                continue
            state.tabs[name] = TabState(
                sort=tab_data.get("sort"),
                filter=tab_data.get("filter"),
                columns=tab_data.get("columns"),
                partitions=tab_data.get("partitions"),
                window=tab_data.get("window"),
            )
        return state


def load_state(path: Path | None = None) -> State:
    path = path or default_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return State()
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("ignoring unreadable state file %s: %s", path, exc)
        return State()
    if not isinstance(data, dict):
        return State()
    return State.from_dict(data)


def save_state(state: State, path: Path | None = None) -> None:
    path = path or default_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("could not write state file %s: %s", path, exc)


def apply_state(config: Config, state: State) -> Config:
    """Return a config with the state's overrides applied. Invalid overrides are dropped."""
    updates: dict[str, Any] = {}
    if state.theme:
        updates["general"] = {"theme": state.theme}
    if state.auto_refresh is not None:
        updates["refresh"] = {"auto": state.auto_refresh}
    tab_updates: dict[str, Any] = {}
    for name in TABLE_TABS:
        tab_state = state.tabs.get(name)
        if tab_state is None or tab_state.is_empty():
            continue
        overrides = tab_state.to_dict()
        tab_model = getattr(config.tabs, name)
        allowed = {key: value for key, value in overrides.items() if key in type(tab_model).model_fields}
        if allowed:
            tab_updates[name] = allowed
    if tab_updates:
        updates["tabs"] = tab_updates
    if not updates:
        return config
    raw = config.model_dump()
    merged = _merge(raw, updates)
    try:
        return Config.model_validate(merged)
    except ValidationError as exc:
        log.warning("ignoring invalid state overrides: %s", exc)
        return config


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged
