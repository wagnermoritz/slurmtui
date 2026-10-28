# Configuration reference

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
| `gres_type` | the GPU GRES type name, e.g. `a100-80g-gcp` | `{gres_type}`, `{gres_type.N}` |
| `feature` | each feature token in turn, first hit wins | `{feature}` or `{feature.0}` whole token, `{feature.N}` regex group N |
| `features` | the comma-joined feature string | `{features.N}` |
| `node` | the node name | `{node}`, `{node.N}` |
| `partition` | any partition of the node | `{partition.N}` |

Templates may also use `{arch}`, `{cpus}`, `{sockets}`, `{cores}` and `{threads}`. The GPU label is
`None` for nodes without GPUs; the CPU fallback `{arch} {cpus}c` is never empty.

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
with overrides: `{ key = "name", label = "Node", width = 20, max_len = 15, align = "right" }`. Column keys
are listed in [columns.md](columns.md) and by `slurmtui columns`. NODES has `partitions` (the initial
partition selection), HISTORY has `window`, CLUSTER has `panels` and `pending_reasons_shown`.

## Keys

`[keys]` binds every action to one key or a list of keys using Textual key names
(`ctrl+r`, `f5`, `question_mark`, `slash`, ...).

## Packaged defaults

```toml
ungrouped_name = "other"

[[node_groups]]
name = "cluster"
nodes = ["*"]
partitions = ["*"]

[general]
theme = "textual-dark"
memory_unit = "auto"
duration_style = "slurm"
datetime_format = "%Y-%m-%d %H:%M"
max_rows = 2000
log_level = "warning"

[commands]
timeout_seconds = 60
path_prefix = ""

[commands.env]

[refresh]
auto = false
active_tab_seconds = 30
inactive_tabs_seconds = 120
on_tab_switch = true

[sources.nodes]
ttl = 15

[sources.partitions]
ttl = 300

[sources.jobs]
ttl = 15

[sources.reservations]
ttl = 120

[sources.shares]
ttl = 120

[sources.scheduler]
ttl = 60

[sources.history]
ttl = 60
default_window = "7d"
max_window = "90d"
max_rss_unit = "auto"

[sources.recent_jobs]
enabled = false
ttl = 900
window = "7d"

[sources.account_usage]
enabled = false
ttl = 900
default_window = "7d"
max_window = "30d"

[hardware.gpu_type]
rules = []
fallback = "{gres_type}"

[hardware.cpu_type]
rules = []
fallback = "{arch} {cpus}c"

[usage]
gpu_hours_when = "gpu_allocated"
gpu_partitions = []
count_cpu_hours_of_gpu_jobs = false

[styles.usage_bar]
style = "gradient"
width = 40
warn = 0.7
critical = 0.9

[styles.efficiency]
warn = 0.5
critical = 0.2

[styles.node_state]
idle = "green"
mixed = "yellow"
allocated = "yellow"
completing = "yellow"
planned = "yellow"
reserved = "yellow"
down = "red"
drained = "red"
draining = "red"
fail = "red"
failing = "red"
maint = "red"
unknown = "red"
error = "red"
future = "dim"
default = ""

[styles.node_state_flags]
powered_down = "dim"
powering_up = "italic"
powering_down = "dim"
not_responding = "red"
maintenance = "red"
reboot_requested = "yellow"
reboot_issued = "yellow"

[styles.job_state]
RUNNING = "green"
PENDING = "yellow"
COMPLETING = "yellow"
CONFIGURING = "yellow"
SUSPENDED = "yellow"
REQUEUED = "yellow"
COMPLETED = "green"
FAILED = "red"
CANCELLED = "red"
TIMEOUT = "red"
OUT_OF_MEMORY = "red"
NODE_FAIL = "red"
PREEMPTED = "red"
BOOT_FAIL = "red"
DEADLINE = "red"
default = ""

[detail]
stdout_tail_lines = 50
stdout_tail_max_kb = 256
stdout_tail_line_len = 400
use_seff = true

[keys]
quit = "ctrl+q"
help = "question_mark"
refresh = ["ctrl+r", "f5"]
refresh_all = "ctrl+shift+r"
toggle_auto_refresh = "ctrl+t"
focus_filter = "slash"
clear_filter = "ctrl+l"
next_tab = "ctrl+right"
prev_tab = "ctrl+left"
my_jobs = "ctrl+n"
settings = "ctrl+s"
close = "escape"
sort_dialog = "ctrl+o"
restore_filter = "ctrl+z"

[tabs.nodes]
enabled = true
title = "NODES"
columns = ["name", "state", "avail", "partitions", "jobs", "cpus", "cpu_type", "memory", "gpus", "gpu_type", "max_time"]
sort = "name"
filter = ""
partitions = ""

[tabs.jobs]
enabled = true
title = "JOBS"
columns = ["job_id", "partition", "name", "user", "state", "time", "time_limit", "cpus", "gpus", "memory", "priority", "nodes", "node_list"]
sort = "state, priority desc"
filter = ""

[tabs.users]
enabled = true
title = "USERS"
columns = ["user", "jobs_running", "jobs_pending", "cpus", "gpus", "memory", "usage", "fairshare", "nodes", "partitions"]
sort = "jobs_running desc"
filter = ""

[tabs.accounts]
enabled = true
title = "ACCOUNTS"
columns = ["account", "shares", "usage", "level_fs", "jobs_running", "jobs_pending", "cpus", "gpus", "memory", "members_active", "oldest_pending"]
sort = "usage desc"
filter = ""

[tabs.history]
enabled = true
title = "HISTORY"
columns = ["job_id", "name", "partition", "state", "exit_code", "elapsed", "cpus", "req_mem", "max_rss", "mem_eff", "cpu_eff", "end"]
sort = "end desc"
filter = ""
window = ""

[tabs.cluster]
enabled = true
title = "CLUSTER"
panels = ["gpus", "cpus", "memory", "nodes", "jobs", "reservations", "scheduler"]
pending_reasons_shown = 10
```
