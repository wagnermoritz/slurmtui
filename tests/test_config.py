import json
from pathlib import Path

import pytest

from slurmtui.columns.registry import validate_config_columns
from slurmtui.config.loader import ConfigError, config_from_dict, load_config, to_toml
from slurmtui.config.schema import Config
from slurmtui.config.state import State, TabState, apply_state, load_state, save_state


def test_defaults_load_and_roundtrip():
    loaded = load_config(use_default_locations=False)
    text = to_toml(loaded.config.model_dump())
    import tomllib

    assert Config.model_validate(tomllib.loads(text)) == loaded.config
    assert loaded.config.tabs.nodes.columns[1].key == "state"


def test_layering(tmp_path: Path):
    site = tmp_path / "site.toml"
    site.write_text('[[node_groups]]\nname = "a"\nnodes = ["a*"]\n\n[tabs.jobs]\ncolumns = ["job_id", "user"]\n')
    user = tmp_path / "user.toml"
    user.write_text('[general]\ntheme = "nord"\n\n[tabs.jobs]\nsort = "user"\n')
    loaded = load_config(site_config=site, user_config=user)
    config = loaded.config
    assert config.group_names == ["a"]
    assert [c.key for c in config.tabs.jobs.columns] == ["job_id", "user"]  # list from site kept
    assert config.tabs.jobs.sort == "user"  # table merged
    assert config.general.theme == "nord"
    assert loaded.source_of(("general", "theme")) == str(user)
    assert loaded.source_of(("tabs", "jobs", "columns")) == str(site)


def test_unknown_key_names_file(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[tabs.jobs]\ncolums = ['x']\n")
    with pytest.raises(ConfigError) as info:
        load_config(user_config=bad)
    assert "tabs.jobs.colums" in str(info.value) and str(bad) in str(info.value)


def test_missing_explicit_file():
    with pytest.raises(ConfigError):
        load_config(user_config=Path("/nonexistent/config.toml"))


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"sources": {"nodes": {"enabled": False}}}, "cannot be disabled"),
        ({"styles": {"job_state": {"RUNNING": "notacolor zz"}}}, "invalid style"),
        ({"node_groups": [{"name": "a"}, {"name": "a"}]}, "unique"),
        ({"hardware": {"gpu_type": {"rules": [{"label": "x"}]}}}, "at least one selector"),
        ({"sources": {"history": {"default_window": "3 months"}}}, "invalid time window"),
        ({"sources": {"history": {"default_window": "100d", "max_window": "90d"}}}, "must not exceed"),
        ({"tabs": {"jobs": {"columns": ["job_id", "job_id"]}}}, "twice"),
        ({"node_groups": [{"name": "a:b"}]}, "must not contain"),
        ({"general": {"max_rows": 0}}, "greater than"),
    ],
)
def test_validation_errors(override, fragment):
    with pytest.raises(ConfigError) as info:
        config_from_dict(override)
    assert fragment in str(info.value)


def test_column_validation():
    config = config_from_dict({"tabs": {"users": {"columns": ["user", "jobs_7d", "bogus"]}}})
    errors = validate_config_columns(config)
    assert any("jobs_7d" in error and "recent_jobs" in error for error in errors)
    assert any("bogus" in error for error in errors)
    ok = config_from_dict(
        {
            "sources": {"account_usage": {"enabled": True}},
            "node_groups": [{"name": "z3"}, {"name": "GCP"}],
            "tabs": {"accounts": {"columns": ["account", "gpu_hours:*"]}},
        }
    )
    assert validate_config_columns(ok) == []


def test_state_roundtrip_and_apply(tmp_path: Path):
    state = State(theme="nord", auto_refresh=True, last_tab="jobs")
    state.tabs["jobs"] = TabState(
        sort="user desc", filter="@me", columns=[{"key": "job_id"}, {"key": "user", "max_len": 5}]
    )
    state.tabs["nodes"] = TabState(partitions="gpu")
    path = tmp_path / "state.json"
    save_state(state, path)
    loaded = load_state(path)
    assert loaded.to_dict() == state.to_dict()
    assert json.loads(path.read_text())["version"] == 1
    config = apply_state(config_from_dict({}), loaded)
    assert config.general.theme == "nord" and config.refresh.auto is True
    assert config.tabs.jobs.sort == "user desc" and config.tabs.jobs.filter == "@me"
    assert [c.key for c in config.tabs.jobs.columns] == ["job_id", "user"]
    assert config.tabs.jobs.columns[1].max_len == 5
    assert config.tabs.nodes.partitions == "gpu"


def test_state_invalid_override_is_dropped():
    state = State()
    state.tabs["jobs"] = TabState(columns=[])
    config = apply_state(config_from_dict({}), state)
    assert len(config.tabs.jobs.columns) > 1


def test_load_state_missing_or_broken(tmp_path: Path):
    assert load_state(tmp_path / "missing.json").to_dict() == {"version": 1}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert load_state(broken).to_dict() == {"version": 1}
