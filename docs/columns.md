# Column keys

Use these keys in `tabs.<tab>.columns`, in sort specifications and in filter terms.

## nodes

| Key | Label | Type | Description | Needs |
| --- | --- | --- | --- | --- |
| `avail` | Avail | avail | up when every partition of the node is UP |  |
| `cpu_load` | Load | float | CPU load average |  |
| `cpu_type` | CPU type | str | CPU type from [hardware.cpu_type] |  |
| `cpus` | CPUs | fraction | allocated/total CPUs |  |
| `cpus_alloc` | CPU alloc | int | allocated CPUs |  |
| `cpus_total` | CPU total | int | total CPUs |  |
| `features` | Features | list | active features |  |
| `gpu_gres` | Gres | str | raw Gres string |  |
| `gpu_type` | GPU type | str | GPU type from [hardware.gpu_type] |  |
| `gpus` | GPUs | fraction | allocated/total GPUs |  |
| `gpus_alloc` | GPU alloc | int | allocated GPUs |  |
| `gpus_total` | GPU total | int | total GPUs |  |
| `jobs` | Jobs | int | running jobs on the node |  |
| `max_time` | Max time | duration | largest MaxTime of the node's partitions |  |
| `mem_alloc` | Mem alloc | bytes | allocated memory |  |
| `mem_free` | Mem free | bytes | free memory reported by the node |  |
| `mem_total` | Mem total | bytes | total memory |  |
| `memory` | Memory | bytes_fraction | allocated/total memory |  |
| `name` | Node | str | node name |  |
| `node_group` | Group | str | node group from [[node_groups]] |  |
| `partitions` | Partitions | list | partitions the node belongs to |  |
| `reason` | Reason | str | drain/down reason |  |
| `reason_time` | Reason time | datetime | when |  |
| `reason_user` | Set by | str | who set the reason |  |
| `state` | State | node_state | compact state as sinfo shows it (idle~, mix, drng) |  |
| `state_long` | State | str | full state with flags (IDLE+CLOUD+POWERED_DOWN) |  |

## jobs

| Key | Label | Type | Description | Needs |
| --- | --- | --- | --- | --- |
| `account` | Account | str | account charged |  |
| `array_tasks` | Tasks | int | array tasks represented by the row |  |
| `command` | Command | str | batch script |  |
| `cpus` | CPUs | int | CPUs |  |
| `dependency` | Dependency | str | dependency specification |  |
| `gpus` | GPUs | int | allocated GPUs, requested for pending jobs |  |
| `job_id` | Job ID | jobid | job id, arrays as 123_[1-10] |  |
| `memory` | Memory | bytes | allocated memory, requested for pending jobs |  |
| `name` | Name | str | job name |  |
| `node_group` | Group | str | node group |  |
| `node_list` | Node list | nodelist | allocated nodes |  |
| `nodes` | Nodes | int | number of nodes |  |
| `partition` | Partition | str | partition(s) |  |
| `priority` | Priority | int | scheduling priority |  |
| `qos` | QOS | str | quality of service |  |
| `reason` | Reason | str | pending reason |  |
| `sched_nodes` | Planned | nodelist | nodes planned by the backfill |  |
| `start_time` | Start | datetime | start time (estimated for pending jobs) |  |
| `state` | State | job_state | RUNNING, PENDING, ... |  |
| `stdout` | Stdout | str | stdout file |  |
| `submit_time` | Submitted | datetime | submit time |  |
| `tasks` | NTasks | int | tasks |  |
| `time` | Time | duration | time used |  |
| `time_left` | Left | duration | time left |  |
| `time_limit` | Limit | duration | time limit |  |
| `user` | User | str | owner |  |
| `work_dir` | Work dir | str | working directory |  |

## users

| Key | Label | Type | Description | Needs |
| --- | --- | --- | --- | --- |
| `accounts` | Accounts | list | accounts with jobs |  |
| `cpus` | CPUs | int | allocated CPUs |  |
| `fairshare` | FairShare | float | best fairshare factor |  |
| `gpus` | GPUs | int | allocated GPUs |  |
| `jobs_24h` | 24h | int | jobs in the last 24 hours | `sources.recent_jobs` |
| `jobs_7d` | 7d | int | jobs in the last 7 days | `sources.recent_jobs` |
| `jobs_other` | Other | int | jobs in other states |  |
| `jobs_pending` | Pending | int | pending jobs (array tasks counted) |  |
| `jobs_running` | Running | int | running jobs |  |
| `memory` | Memory | bytes | allocated memory |  |
| `nodes` | Nodes | nodelist | occupied nodes |  |
| `partitions` | Partitions | list | partitions with jobs |  |
| `raw_usage` | Raw usage | float | raw usage summed over the user's accounts |  |
| `usage` | Usage | float | effective usage within the account (largest if the user has several) |  |
| `user` | User | str | user name |  |

## accounts

| Key | Label | Type | Description | Needs |
| --- | --- | --- | --- | --- |
| `account` | Account | str | account name |  |
| `cpus` | CPUs | int | allocated CPUs |  |
| `fairshare` | FairShare | float | fairshare factor |  |
| `gpus` | GPUs | int | allocated GPUs |  |
| `jobs_pending` | Pending | int | pending jobs (array tasks counted) |  |
| `jobs_running` | Running | int | running jobs |  |
| `level_fs` | LevelFS | float | level fairshare (>1: under-used) |  |
| `members` | Members | int | users in the account |  |
| `members_active` | Active | fraction | users with a job in the queue / users with an association in the account |  |
| `memory` | Memory | bytes | allocated memory |  |
| `oldest_pending` | Oldest PD | duration | age of the oldest pending job |  |
| `raw_usage` | Raw usage | float | raw usage |  |
| `shares` | Shares | float | normalised shares |  |
| `usage` | Usage | float | effective usage |  |

Per node group usage columns are added dynamically: `cpu_hours:<group>` and `gpu_hours:<group>`,
or `cpu_hours:*` / `gpu_hours:*` for every configured group. They need `sources.account_usage`.

## history

| Key | Label | Type | Description | Needs |
| --- | --- | --- | --- | --- |
| `account` | Account | str | account |  |
| `cpu_eff` | CPU eff | percent | total CPU time / (elapsed x CPUs) |  |
| `cpus` | CPUs | int | allocated CPUs |  |
| `elapsed` | Elapsed | duration | wall time |  |
| `end` | End | datetime | end time |  |
| `exit_code` | Exit | str | exit code:signal |  |
| `gpus` | GPUs | int | allocated GPUs |  |
| `job_id` | Job ID | jobid | job id |  |
| `max_rss` | Max RSS | bytes | peak memory over the steps |  |
| `mem_eff` | Mem eff | percent | max_rss / req_mem |  |
| `name` | Name | str | job name |  |
| `node_list` | Node list | nodelist | nodes |  |
| `partition` | Partition | str | partition |  |
| `req_mem` | Req mem | bytes | requested memory |  |
| `start` | Start | datetime | start time |  |
| `state` | State | job_state | final state |  |
| `stdout` | Stdout | str | stdout file pattern |  |
| `submit` | Submitted | datetime | submit time |  |
| `time_limit` | Limit | duration | time limit |  |
| `work_dir` | Work dir | str | working directory |  |

## Column types

| Type | Formatting | Sorting | Comparison operands in filters |
| --- | --- | --- | --- |
| str, list, nodelist | text; node lists are contracted (`cmp[001-003]`) | case-insensitive | — |
| int, float | number; `digits` per column | numeric | number |
| bytes, bytes_fraction | `[general].memory_unit` | numeric | memory size, bare numbers are GB (`64G`, `512M`) |
| duration | `[general].duration_style` | seconds; UNLIMITED last | `1-00:00:00`, `2h`, `30` (minutes) |
| datetime | `[general].datetime_format` | chronological | ISO timestamp or an age like `2h` (= 2 hours ago) |
| percent | `12.3%`, coloured by `[styles].efficiency` | numeric | `50%` or `0.5` |
| fraction | `used/total` | by used, then total | number (compared with used) |
| node_state | compact sinfo form (`idle~`), coloured by `[styles].node_state` | text | — |
| job_state | `RUNNING`, coloured by `[styles].job_state` | text | — |
| jobid | as is | numeric by every number in the id | number |
