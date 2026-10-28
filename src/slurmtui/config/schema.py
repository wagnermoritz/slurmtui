"""The configuration schema.

Every model forbids unknown keys, so typos are reported with their key path.
The field defaults must agree with ``defaults.toml`` next to this module.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from rich.style import Style, StyleType

from slurmtui.patterns import validate_pattern
from slurmtui.units import parse_window


def _validate_style(value: str) -> str:
    try:
        Style.parse(value)
    except Exception as exc:  # rich raises StyleSyntaxError, a ValueError subclass
        raise ValueError(f"invalid style {value!r}: {exc}") from exc
    return value


def _validate_window(value: str) -> str:
    if parse_window(value) is None:
        raise ValueError(f"invalid time window {value!r}; use e.g. 12h, 3d, 2w")
    return value


Pattern = Annotated[str, AfterValidator(validate_pattern)]
RichStyle = Annotated[str, AfterValidator(_validate_style)]
Window = Annotated[str, AfterValidator(_validate_window)]
KeyBinding = Annotated[list[str], BeforeValidator(lambda v: [v] if isinstance(v, str) else v)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GeneralConfig(StrictModel):
    theme: str = "textual-dark"
    memory_unit: Literal["auto", "G", "M"] = "auto"
    duration_style: Literal["slurm", "compact"] = "slurm"
    datetime_format: str = "%Y-%m-%d %H:%M"
    max_rows: int = Field(default=2000, ge=1)
    log_level: Literal["debug", "info", "warning", "error"] = "warning"


class CommandsConfig(StrictModel):
    timeout_seconds: float = Field(default=60, gt=0)
    path_prefix: str = ""
    env: dict[str, str] = Field(default_factory=dict)


class RefreshConfig(StrictModel):
    auto: bool = False
    active_tab_seconds: float = Field(default=30, ge=5)
    inactive_tabs_seconds: float = Field(default=120, ge=5)
    on_tab_switch: bool = True


class SourceConfig(StrictModel):
    enabled: bool = True
    ttl: float = Field(default=15, ge=0)


class WindowedSourceConfig(SourceConfig):
    default_window: Window = "7d"
    max_window: Window = "90d"

    @model_validator(mode="after")
    def _default_within_max(self) -> WindowedSourceConfig:
        default, maximum = parse_window(self.default_window), parse_window(self.max_window)
        assert default is not None and maximum is not None
        if default > maximum:
            raise ValueError("default_window must not exceed max_window")
        return self


MaxRssUnit = Literal["auto", "B", "K", "M", "G"]


class HistorySourceConfig(WindowedSourceConfig):
    max_rss_unit: MaxRssUnit = "auto"
    """Unit of a MaxRSS value that sacct prints without a suffix.

    ``auto`` follows Slurm: with ``--noconvert`` a bare number is bytes (Slurm stores
    step memory usage in bytes), while older releases always print a ``K`` suffix.
    A suffixed value is always read by its suffix.
    """


class RecentJobsConfig(SourceConfig):
    enabled: bool = False
    ttl: float = Field(default=900, ge=0)
    window: Window = "7d"


class SourcesConfig(StrictModel):
    nodes: SourceConfig = SourceConfig(ttl=15)
    partitions: SourceConfig = SourceConfig(ttl=300)
    jobs: SourceConfig = SourceConfig(ttl=15)
    reservations: SourceConfig = SourceConfig(ttl=120)
    shares: SourceConfig = SourceConfig(ttl=120)
    scheduler: SourceConfig = SourceConfig(ttl=60)
    history: HistorySourceConfig = HistorySourceConfig(ttl=60)
    recent_jobs: RecentJobsConfig = RecentJobsConfig()
    account_usage: WindowedSourceConfig = WindowedSourceConfig(enabled=False, ttl=900, max_window="30d")

    @model_validator(mode="after")
    def _core_sources_enabled(self) -> SourcesConfig:
        for name in ("nodes", "partitions", "jobs", "shares"):
            if not getattr(self, name).enabled:
                raise ValueError(f"source {name!r} cannot be disabled")
        return self


class NodeGroup(StrictModel):
    name: str = Field(min_length=1)
    nodes: list[Pattern] = Field(default_factory=lambda: ["*"])
    partitions: list[Pattern] = Field(default_factory=lambda: ["*"])

    @field_validator("name")
    @classmethod
    def _no_colon(cls, value: str) -> str:
        if ":" in value or "*" in value:
            raise ValueError("group names must not contain ':' or '*'")
        return value


class HardwareRule(StrictModel):
    gres_type: Pattern | None = None
    feature: Pattern | None = None
    features: Pattern | None = None
    node: Pattern | None = None
    partition: Pattern | None = None
    label: str

    @model_validator(mode="after")
    def _has_selector(self) -> HardwareRule:
        if not any((self.gres_type, self.feature, self.features, self.node, self.partition)):
            raise ValueError("a hardware rule needs at least one selector")
        return self


class HardwareTypeConfig(StrictModel):
    rules: list[HardwareRule] = Field(default_factory=list)
    fallback: str = ""


class HardwareConfig(StrictModel):
    gpu_type: HardwareTypeConfig = HardwareTypeConfig(fallback="{gres_type}")
    cpu_type: HardwareTypeConfig = HardwareTypeConfig(fallback="{arch} {cpus}c")


class UsageConfig(StrictModel):
    gpu_hours_when: Literal["gpu_allocated", "partition"] = "gpu_allocated"
    gpu_partitions: list[Pattern] = Field(default_factory=list)
    count_cpu_hours_of_gpu_jobs: bool = False


class UsageBarStyle(StrictModel):
    style: Literal["gradient", "solid"] = "gradient"
    width: int = Field(default=40, ge=5, le=200)
    warn: float = Field(default=0.7, ge=0, le=1)
    critical: float = Field(default=0.9, ge=0, le=1)


class EfficiencyStyle(StrictModel):
    warn: float = Field(default=0.5, ge=0, le=1)
    critical: float = Field(default=0.2, ge=0, le=1)


class StylesConfig(StrictModel):
    node_state: dict[str, RichStyle] = Field(default_factory=dict)
    node_state_flags: dict[str, RichStyle] = Field(default_factory=dict)
    job_state: dict[str, RichStyle] = Field(default_factory=dict)
    usage_bar: UsageBarStyle = UsageBarStyle()
    efficiency: EfficiencyStyle = EfficiencyStyle()

    @field_validator("node_state", "node_state_flags")
    @classmethod
    def _lowercase_keys(cls, value: dict[str, str]) -> dict[str, str]:
        return {key.lower(): style for key, style in value.items()}

    @field_validator("job_state")
    @classmethod
    def _uppercase_keys(cls, value: dict[str, str]) -> dict[str, str]:
        return {key if key == "default" else key.upper(): style for key, style in value.items()}


class DetailConfig(StrictModel):
    stdout_tail_lines: int = Field(default=50, ge=1)
    stdout_tail_max_kb: int = Field(default=256, ge=1)
    stdout_tail_line_len: int = Field(default=400, ge=10)
    use_seff: bool = True


class KeysConfig(StrictModel):
    quit: KeyBinding = ["ctrl+q"]
    help: KeyBinding = ["question_mark"]
    refresh: KeyBinding = ["ctrl+r", "f5"]
    refresh_all: KeyBinding = ["ctrl+shift+r"]
    toggle_auto_refresh: KeyBinding = ["ctrl+t"]
    focus_filter: KeyBinding = ["slash"]
    clear_filter: KeyBinding = ["ctrl+l"]
    next_tab: KeyBinding = ["ctrl+right"]
    prev_tab: KeyBinding = ["ctrl+left"]
    my_jobs: KeyBinding = ["ctrl+n"]
    settings: KeyBinding = ["ctrl+s"]
    close: KeyBinding = ["escape"]
    sort_dialog: KeyBinding = ["ctrl+o"]
    restore_filter: KeyBinding = ["ctrl+z"]


def _column_from_str(value: Any) -> Any:
    return {"key": value} if isinstance(value, str) else value


class ColumnSpec(StrictModel):
    key: str = Field(min_length=1)
    label: str | None = None
    width: int | None = Field(default=None, ge=1)
    max_len: int | None = Field(default=None, ge=1)
    align: Literal["left", "right"] | None = None


ColumnList = Annotated[list[Annotated[ColumnSpec, BeforeValidator(_column_from_str)]], Field(min_length=1)]


class TableTabConfig(StrictModel):
    enabled: bool = True
    title: str
    columns: ColumnList
    sort: str = ""
    filter: str = ""

    @field_validator("columns")
    @classmethod
    def _unique_keys(cls, value: list[ColumnSpec]) -> list[ColumnSpec]:
        seen: set[str] = set()
        for column in value:
            if column.key in seen:
                raise ValueError(f"column {column.key!r} is listed twice")
            seen.add(column.key)
        return value


class NodesTabConfig(TableTabConfig):
    title: str = "NODES"
    partitions: str = ""


class JobsTabConfig(TableTabConfig):
    title: str = "JOBS"


class UsersTabConfig(TableTabConfig):
    title: str = "USERS"


class AccountsTabConfig(TableTabConfig):
    title: str = "ACCOUNTS"


class HistoryTabConfig(TableTabConfig):
    title: str = "HISTORY"
    window: Window | Literal[""] = ""


ClusterPanel = Literal["gpus", "cpus", "memory", "nodes", "jobs", "reservations", "scheduler"]
DEFAULT_PANELS: tuple[ClusterPanel, ...] = ("gpus", "cpus", "memory", "nodes", "jobs", "reservations", "scheduler")


class ClusterTabConfig(StrictModel):
    enabled: bool = True
    title: str = "CLUSTER"
    panels: list[ClusterPanel] = Field(default_factory=lambda: list(DEFAULT_PANELS))
    pending_reasons_shown: int = Field(default=10, ge=1)


class TabsConfig(StrictModel):
    nodes: NodesTabConfig
    jobs: JobsTabConfig
    users: UsersTabConfig
    accounts: AccountsTabConfig
    history: HistoryTabConfig
    cluster: ClusterTabConfig = ClusterTabConfig()


TABLE_TABS: tuple[str, ...] = ("nodes", "jobs", "users", "accounts", "history")
ALL_TABS: tuple[str, ...] = (*TABLE_TABS, "cluster")


class Config(StrictModel):
    general: GeneralConfig = GeneralConfig()
    commands: CommandsConfig = CommandsConfig()
    refresh: RefreshConfig = RefreshConfig()
    sources: SourcesConfig = SourcesConfig()
    node_groups: list[NodeGroup] = Field(default_factory=lambda: [NodeGroup(name="cluster")])
    ungrouped_name: str = "other"
    hardware: HardwareConfig = HardwareConfig()
    usage: UsageConfig = UsageConfig()
    styles: StylesConfig = StylesConfig()
    detail: DetailConfig = DetailConfig()
    keys: KeysConfig = KeysConfig()
    tabs: TabsConfig

    @model_validator(mode="after")
    def _cross_checks(self) -> Config:
        names = [group.name for group in self.node_groups]
        if len(names) != len(set(names)):
            raise ValueError("node group names must be unique")
        if self.ungrouped_name in names:
            raise ValueError(f"ungrouped_name {self.ungrouped_name!r} clashes with a node group")
        if not any(tab_enabled(self, tab) for tab in ALL_TABS):
            raise ValueError("at least one tab must be enabled")
        return self

    @property
    def group_names(self) -> list[str]:
        return [group.name for group in self.node_groups]

    def table_tab(self, name: str) -> TableTabConfig:
        tab = getattr(self.tabs, name)
        if not isinstance(tab, TableTabConfig):
            raise KeyError(name)
        return tab


def tab_enabled(config: Config, name: str) -> bool:
    return bool(getattr(config.tabs, name).enabled)


def style_for_state(styles: dict[str, str], key: str) -> str:
    return styles.get(key, styles.get("default", ""))


def rich_style(text: str) -> StyleType:
    return Style.parse(text) if text else ""
