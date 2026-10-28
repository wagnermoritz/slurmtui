import os
from pathlib import Path

from slurmtui.cli import main


def test_check_config(capsys, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["check-config"]) == 0
    out = capsys.readouterr().out
    assert "configuration is valid" in out and "[tabs.jobs]" in out


def test_dump_defaults(capsys):
    assert main(["dump-config", "--defaults"]) == 0
    assert "[styles.node_state]" in capsys.readouterr().out


def test_columns(capsys, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert main(["columns", "nodes"]) == 0
    out = capsys.readouterr().out
    assert "gpu_type" in out and "node_state" in out


def test_invalid_config_exit_code(capsys, tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[general]\nmemory_unit = 'XB'\n")
    assert main(["--config", str(bad), "check-config"]) == 2
    assert "general.memory_unit" in capsys.readouterr().err


def test_missing_slurm_message(capsys, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    if os.name != "nt":
        assert main(["--no-state"]) == 2  # fails before the UI starts
        assert "scontrol" in capsys.readouterr().err
