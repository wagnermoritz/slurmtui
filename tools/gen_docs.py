#!/usr/bin/env python3
"""Generate docs/columns.md and docs/configuration.md from the registries and the schema."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slurmtui.columns.registry import REGISTRIES
from slurmtui.config.loader import defaults_dict, to_toml

ROOT = Path(__file__).resolve().parents[1]


def columns_md() -> str:
    lines = [
        "# Column keys",
        "",
        "Use these keys in `tabs.<tab>.columns`, in sort specifications and in filter terms.",
        "",
    ]
    for tab, registry in REGISTRIES.items():
        lines += [f"## {tab}", "", "| Key | Label | Type | Description | Needs |", "| --- | --- | --- | --- | --- |"]
        for key, column in sorted(registry.items()):
            needs = f"`sources.{column.requires_source}`" if column.requires_source else ""
            lines.append(f"| `{key}` | {column.label} | {column.type} | {column.description} | {needs} |")
        if tab == "accounts":
            lines += [
                "",
                "Per node group usage columns are added dynamically: `cpu_hours:<group>` and `gpu_hours:<group>`,",
                "or `cpu_hours:*` / `gpu_hours:*` for every configured group. They need `sources.account_usage`.",
            ]
        lines.append("")
    lines += [
        "## Column types",
        "",
        "| Type | Formatting | Sorting | Comparison operands in filters |",
        "| --- | --- | --- | --- |",
        "| str, list, nodelist | text; node lists are contracted (`cmp[001-003]`) | case-insensitive | — |",
        "| int, float | number; `digits` per column | numeric | number |",
        "| bytes, bytes_fraction | `[general].memory_unit` | numeric | memory size, bare numbers are GB (`64G`, `512M`) |",
        "| duration | `[general].duration_style` | seconds; UNLIMITED last | `1-00:00:00`, `2h`, `30` (minutes) |",
        "| datetime | `[general].datetime_format` | chronological | ISO timestamp or an age like `2h` (= 2 hours ago) |",
        "| percent | `12.3%`, coloured by `[styles].efficiency` | numeric | `50%` or `0.5` |",
        "| fraction | `used/total` | by used, then total | number (compared with used) |",
        "| node_state | compact sinfo form (`idle~`), coloured by `[styles].node_state` | text | — |",
        "| job_state | `RUNNING`, coloured by `[styles].job_state` | text | — |",
        "| jobid | as is | numeric by every number in the id | number |",
        "",
    ]
    return "\n".join(lines)


def configuration_md() -> str:
    defaults = to_toml(defaults_dict())
    return f"""# Configuration reference

slurmtui reads TOML configuration in layers; later layers override earlier ones.
Tables merge key by key, lists replace the whole list.

| Layer | Location | Written by |
| --- | --- | --- |
| packaged defaults | inside the package (`slurmtui dump-config --defaults`) | the project |
| site config | `$SLURMTUI_SITE_CONFIG`, else `/etc/slurmtui/config.toml` | cluster admins |
| user config | `$SLURMTUI_CONFIG`, else `$XDG_CONFIG_HOME/slurmtui/config.toml` (`~/.config/slurmtui/config.toml`) | users |
| command line | `--site-config PATH`, `--config PATH` (repeatable), `--theme`, `--tab` | users |
| state file | `$SLURMTUI_STATE`, else `$XDG_STATE_HOME/slurmtui/state.json` | the app (sort, filter, columns, theme, last tab) |

Unknown keys, wrong types and inconsistent values are rejected; the message names the key path and the
file that set it. `slurmtui check-config` prints the loaded files and the effective configuration.

## Patterns

Wherever a value is a *pattern*, it is a shell glob (full match, case-sensitive) unless it starts with
`re:`, in which case the rest is a Python regular expression that is searched in the value.
Lists of patterns match when any entry matches.

## Node groups

```toml
[[node_groups]]
name = "z3"                  # shown as a CLUSTER subtab and usable as cpu_hours:z3 / gpu_hours:z3
nodes = ["htc-*"]            # patterns on the node name; the first matching group wins
partitions = ["re:^(?!gcp)"] # patterns on the partition, used for jobs that have no nodes yet
```

A running job belongs to the group of its first allocated node, a pending job to the first group whose
`partitions` match. Nodes matching no group land in the group named by `ungrouped_name` (default `other`),
which only appears when it is non-empty. Without any `[[node_groups]]` there is one group called `cluster`.

## Hardware labels

`[hardware.gpu_type]` and `[hardware.cpu_type]` each have an ordered list of `rules` and a `fallback`
template. The first rule whose selectors all match wins. Selectors:

| Selector | Matched against | Placeholders |
| --- | --- | --- |
| `gres_type` | the GPU GRES type name, e.g. `a100-80g-gcp` | `{{gres_type}}`, `{{gres_type.N}}` |
| `feature` | each feature token in turn, first hit wins | `{{feature}}` or `{{feature.0}}` whole token, `{{feature.N}}` regex group N |
| `features` | the comma-joined feature string | `{{features.N}}` |
| `node` | the node name | `{{node}}`, `{{node.N}}` |
| `partition` | any partition of the node | `{{partition.N}}` |

Templates may also use `{{arch}}`, `{{cpus}}`, `{{sockets}}`, `{{cores}}` and `{{threads}}`. The GPU label is
`None` for nodes without GPUs; the CPU fallback `{{arch}} {{cpus}}c` is never empty.

## Sources

Every data source has a `ttl` in seconds. Within the TTL all tabs share one fetch; a tab refresh
(`ctrl+r`) forces a new one. `nodes`, `partitions`, `jobs` and `shares` cannot be disabled.

`recent_jobs` (24h/7d job counts per user) and `account_usage` (CPU/GPU hours per account and node
group) run cluster-wide `sacct` sweeps that load slurmdbd. They are **off by default**, have long TTLs,
are never fetched by timers or "refresh all" unless stale, and refuse windows beyond `max_window`.
Columns that need them are rejected by `check-config` while they are disabled.

`history.max_rss_unit` is the unit of a MaxRSS value that `sacct --noconvert` prints without a suffix.
Slurm stores step memory usage in bytes, so the default `auto` reads a bare number as bytes; older
releases print kilobytes with a `K` suffix, which is honoured regardless of this setting. Set `K`
(or `M`, `G`) only if your sacct prints bare numbers in another unit.

## Usage classification

`[usage].gpu_hours_when = "gpu_allocated"` counts a job's hours as GPU hours when it allocated any
`gres/gpu`, otherwise as CPU hours. `"partition"` classifies by `gpu_partitions` patterns instead.
`count_cpu_hours_of_gpu_jobs` additionally books the CPUs of GPU jobs as CPU hours.

## Styles

`[styles.node_state]` maps the long state names (`idle`, `mixed`, `allocated`, `drained`, `draining`,
`down`, ...) to Rich styles, `[styles.node_state_flags]` adds a style for flags such as `powered_down`
or `not_responding`, and `[styles.job_state]` maps job states. `default` applies to anything unlisted.
`[styles.usage_bar]` sets the CLUSTER bars (`gradient` or `solid`, width, thresholds) and
`[styles.efficiency]` the thresholds that colour the HISTORY efficiency columns.

## Tabs

Each table tab has `enabled`, `title`, `columns`, `sort` and `filter`. A column entry is a key or a table
with overrides: `{{ key = "name", label = "Node", width = 20, max_len = 15, align = "right" }}`. Column keys
are listed in [columns.md](columns.md) and by `slurmtui columns`. NODES has `partitions` (the initial
partition selection), HISTORY has `window`, CLUSTER has `panels` and `pending_reasons_shown`.

## Keys

`[keys]` binds every action to one key or a list of keys using Textual key names
(`ctrl+r`, `f5`, `question_mark`, `slash`, ...).

## Packaged defaults

```toml
{defaults}```
"""


if __name__ == "__main__":
    (ROOT / "docs" / "columns.md").write_text(columns_md())
    (ROOT / "docs" / "configuration.md").write_text(configuration_md())
    # the package ships a copy of the demo site file, so `--demo` works after `pip install`
    (ROOT / "src" / "slurmtui" / "demo" / "site-config.toml").write_text(
        (ROOT / "examples" / "demo" / "site-config.toml").read_text()
    )
    print("wrote docs/columns.md, docs/configuration.md and src/slurmtui/demo/site-config.toml")
