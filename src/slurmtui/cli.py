"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from slurmtui import __version__
from slurmtui.columns.registry import registry_for, validate_config_columns
from slurmtui.config.loader import ConfigError, LoadedConfig, defaults_dict, load_config, to_toml
from slurmtui.config.schema import ALL_TABS, TABLE_TABS
from slurmtui.config.state import apply_state, default_log_path, default_state_path, load_state
from slurmtui.slurm.backend import SlurmBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slurmtui", description="A terminal UI for monitoring Slurm clusters.")
    parser.add_argument("--version", action="version", version=f"slurmtui {__version__}")
    parser.add_argument("--site-config", type=Path, metavar="PATH", help="site configuration file")
    parser.add_argument(
        "--config",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="additional configuration file (may be repeated; later files win)",
    )
    parser.add_argument("--no-user-config", action="store_true", help="ignore the user configuration file")
    parser.add_argument("--tab", choices=ALL_TABS, help="tab to show first")
    parser.add_argument("--theme", help="Textual theme name")
    parser.add_argument("--demo", action="store_true", help="run on a small simulated cluster (no Slurm needed)")
    parser.add_argument("--state-file", type=Path, metavar="PATH", help="state file (default: XDG state dir)")
    parser.add_argument("--no-state", action="store_true", help="do not read or write the state file")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"])
    parser.add_argument("--log-file", type=Path, metavar="PATH")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check-config", help="validate the configuration and print the effective result")
    dump = sub.add_parser("dump-config", help="print the effective configuration as TOML")
    dump.add_argument("--defaults", action="store_true", help="print the packaged defaults instead")
    columns = sub.add_parser("columns", help="list the column keys of a tab")
    columns.add_argument("tab", nargs="?", choices=TABLE_TABS)
    return parser


def _load(args: argparse.Namespace) -> LoadedConfig:
    site_config = args.site_config
    use_default_locations = not args.no_user_config
    if getattr(args, "demo", False):
        # own site file, no installed configuration: the demo looks the same everywhere
        from slurmtui.slurm.simulated_backend import demo_config_path

        site_config = site_config or demo_config_path()
        use_default_locations = False
    loaded = load_config(
        site_config=site_config,
        user_config=None,
        extra_files=args.config,
        use_default_locations=use_default_locations,
    )
    errors = validate_config_columns(loaded.config)
    if errors:
        raise ConfigError("invalid configuration:\n  " + "\n  ".join(errors))
    return loaded


def _setup_logging(level: str, path: Path | None) -> None:
    path = path or default_log_path()
    handlers: list[logging.Handler] = []
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
    )


def _make_backend(args: argparse.Namespace, loaded: LoadedConfig) -> SlurmBackend:
    from slurmtui.slurm.cli_backend import CliBackend

    if args.demo:
        from slurmtui.slurm.simulated_backend import SimulatedBackend

        return SimulatedBackend()
    prefix = loaded.config.commands.path_prefix
    binary = os.path.join(prefix, "scontrol") if prefix else "scontrol"
    if shutil.which(binary) is None:
        raise ConfigError(
            f"{binary}: command not found. Run slurmtui on a node with the Slurm client tools, set "
            "[commands].path_prefix in the configuration, or try `slurmtui --demo`."
        )
    return CliBackend(loaded.config.commands, max_rss_unit=loaded.config.sources.history.max_rss_unit)


def cmd_check_config(args: argparse.Namespace) -> int:
    loaded = _load(args)
    print("configuration files:")
    for path in loaded.files or []:
        print(f"  {path}")
    if not loaded.files:
        print("  (none, packaged defaults only)")
    print("\nconfiguration is valid. effective configuration:\n")
    print(to_toml(loaded.config.model_dump()))
    return 0


def cmd_dump_config(args: argparse.Namespace) -> int:
    if args.defaults:
        print(to_toml(defaults_dict()))
        return 0
    loaded = _load(args)
    print(to_toml(loaded.config.model_dump()))
    return 0


def cmd_columns(args: argparse.Namespace) -> int:
    loaded = _load(args)
    for tab in [args.tab] if args.tab else TABLE_TABS:
        registry = registry_for(tab, loaded.config)
        configured = [spec.key for spec in loaded.config.table_tab(tab).columns]
        print(f"{tab}  (configured: {', '.join(configured)})")
        width = max(len(key) for key in registry)
        for key, column in sorted(registry.items()):
            needs = f"  [needs sources.{column.requires_source}]" if column.requires_source else ""
            print(f"  {key:<{width}}  {column.type:<15} {column.label:<12} {column.description}{needs}")
        print()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from slurmtui.app import create_app
    from slurmtui.data.sources import build_service

    loaded = _load(args)
    config = loaded.config
    _setup_logging(args.log_level or config.general.log_level, args.log_file)
    backend = _make_backend(args, loaded)
    state_path = None if args.no_state else (args.state_file or default_state_path())
    if args.demo and state_path is not None and args.state_file is None:
        state_path = state_path.with_name("demo-" + state_path.name)  # keep demo settings apart from real ones
    state = load_state(state_path) if state_path else load_state(Path(os.devnull))
    effective = apply_state(config, state)
    if args.theme:
        effective = effective.model_copy(update={"general": effective.general.model_copy(update={"theme": args.theme})})
    service = build_service(effective, backend)
    app = create_app(
        effective,
        backend,
        service,
        state,
        base_config=config,
        state_path=state_path,
        config_files=loaded.files,
        initial_tab=args.tab,
    )
    app.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        None: cmd_run,
        "check-config": cmd_check_config,
        "dump-config": cmd_dump_config,
        "columns": cmd_columns,
    }
    try:
        return handlers[args.command](args)
    except ConfigError as exc:
        print(f"slurmtui: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
