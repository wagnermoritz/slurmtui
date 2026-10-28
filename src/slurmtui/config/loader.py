"""Layered configuration loading.

defaults.toml  <-  site config  <-  user config  <-  extra files from the command line

Tables are merged recursively, lists are replaced. Each leaf remembers the
file that set it, so validation errors can name the right file.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from slurmtui.config.schema import Config

SITE_CONFIG_ENV = "SLURMTUI_SITE_CONFIG"
SITE_CONFIG_DEFAULT = Path("/etc/slurmtui/config.toml")
USER_CONFIG_ENV = "SLURMTUI_CONFIG"

Provenance = dict[tuple[str, ...], str]


class ConfigError(Exception):
    """A configuration file could not be read or does not validate."""


@dataclass
class LoadedConfig:
    config: Config
    files: list[Path] = field(default_factory=list)
    provenance: Provenance = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def source_of(self, path: tuple[str, ...]) -> str:
        return source_of(self.provenance, path)


def source_of(provenance: Provenance, path: tuple[str, ...]) -> str:
    """Name of the file that set a key path, falling back to its closest parent."""
    for length in range(len(path), 0, -1):
        if path[:length] in provenance:
            return provenance[path[:length]]
    return "defaults"


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")


def default_user_config_path() -> Path:
    override = os.environ.get(USER_CONFIG_ENV)
    return Path(override) if override else xdg_config_home() / "slurmtui" / "config.toml"


def default_site_config_path() -> Path | None:
    override = os.environ.get(SITE_CONFIG_ENV)
    if override:
        return Path(override)
    return SITE_CONFIG_DEFAULT if SITE_CONFIG_DEFAULT.exists() else None


def defaults_dict() -> dict[str, Any]:
    text = resources.files("slurmtui.config").joinpath("defaults.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: file not found") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: {exc.strerror}") from exc


def deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
    provenance: Provenance,
    origin: str,
    path: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Merge override into a copy of base. Tables merge, everything else replaces."""
    merged = dict(base)
    for key, value in override.items():
        key_path = (*path, key)
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value, provenance, origin, key_path)
        else:
            merged[key] = value
            provenance[key_path] = origin
            _record_children(value, provenance, origin, key_path)
    return merged


def _record_children(value: Any, provenance: Provenance, origin: str, path: tuple[str, ...]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            provenance[(*path, key)] = origin
            _record_children(child, provenance, origin, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            provenance[(*path, str(index))] = origin
            _record_children(child, provenance, origin, (*path, str(index)))


def format_validation_error(error: ValidationError, provenance: Provenance | None = None) -> str:
    lines = []
    for item in error.errors():
        loc = tuple(str(part) for part in item["loc"])
        where = f" (set in {source_of(provenance, loc)})" if provenance is not None else ""
        dotted = ".".join(loc) or "<root>"
        message = item["msg"]
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        lines.append(f"  {dotted}: {message}{where}")
    return "\n".join(lines)


def validate_raw(raw: dict[str, Any], provenance: Provenance, files: Sequence[Path]) -> LoadedConfig:
    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError("invalid configuration:\n" + format_validation_error(exc, provenance)) from exc
    return LoadedConfig(config=config, files=list(files), provenance=provenance, raw=raw)


def load_config(
    *,
    site_config: Path | None = None,
    user_config: Path | None = None,
    extra_files: Iterable[Path] = (),
    use_default_locations: bool = True,
) -> LoadedConfig:
    """Load and validate the layered configuration.

    ``site_config``/``user_config`` override the default locations; a missing
    default location is skipped silently, an explicitly given file must exist.
    """
    raw = defaults_dict()
    provenance: Provenance = {}
    files: list[Path] = []

    layers: list[tuple[Path, bool]] = []
    if site_config is not None:
        layers.append((site_config, True))
    elif use_default_locations and (default_site := default_site_config_path()) is not None:
        layers.append((default_site, SITE_CONFIG_ENV in os.environ))
    if user_config is not None:
        layers.append((user_config, True))
    elif use_default_locations:
        layers.append((default_user_config_path(), USER_CONFIG_ENV in os.environ))
    layers.extend((Path(extra), True) for extra in extra_files)

    for path, required in layers:
        if not path.exists():
            if required:
                raise ConfigError(f"{path}: file not found")
            continue
        raw = deep_merge(raw, read_toml(path), provenance, str(path))
        files.append(path)
    return validate_raw(raw, provenance, files)


def config_from_dict(raw_override: dict[str, Any]) -> Config:
    """Defaults merged with a dict; handy for tests and programmatic use."""
    provenance: Provenance = {}
    raw = deep_merge(defaults_dict(), raw_override, provenance, "<dict>")
    return validate_raw(raw, provenance, []).config


def to_toml(data: dict[str, Any]) -> str:
    """Serialise a plain dict (as produced by model_dump) to TOML text.

    Covers what the config schema needs: nested tables, arrays of tables for
    lists of dicts, inline tables inside arrays.
    """
    out: list[str] = []
    _write_table(_drop_none(data), (), out)
    return "\n".join(out).strip() + "\n"


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value if v is not None]
    return value


def _write_table(table: dict[str, Any], path: tuple[str, ...], out: list[str]) -> None:
    scalars = {k: v for k, v in table.items() if not isinstance(v, dict) and not _is_table_array(v)}
    subtables = {k: v for k, v in table.items() if isinstance(v, dict)}
    table_arrays = {k: v for k, v in table.items() if _is_table_array(v)}
    if path and (scalars or (not subtables and not table_arrays)):
        out.append(f"\n[{'.'.join(path)}]")
    for key, value in scalars.items():
        out.append(f"{_toml_key(key)} = {_toml_value(value)}")
    for key, value in table_arrays.items():
        for item in value:
            out.append(f"\n[[{'.'.join((*path, key))}]]")
            for sub_key, sub_value in item.items():
                out.append(f"{_toml_key(sub_key)} = {_toml_value(sub_value)}")
    for key, value in subtables.items():
        _write_table(value, (*path, key), out)


def _is_table_array(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)


def _toml_key(key: str) -> str:
    return key if key.replace("_", "").replace("-", "").isalnum() else _toml_value(key)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"cannot serialise {type(value).__name__} to TOML")
