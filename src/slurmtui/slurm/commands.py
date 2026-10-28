"""Command lines and field lists for every query the CLI backend runs.

Everything is an argv list; nothing is ever passed through a shell.
"""

from __future__ import annotations

from datetime import datetime

# squeue -O fields: (name, width); -O truncates silently, so widths are generous.
SQUEUE_FIELDS: tuple[tuple[str, int], ...] = (
    ("JobArrayID", 40),
    ("JobID", 20),
    ("ArrayJobID", 20),
    ("ArrayTaskID", 40),
    ("Partition", 60),
    ("Name", 200),
    ("UserName", 40),
    ("Account", 60),
    ("QOS", 40),
    ("State", 30),
    ("Reason", 80),
    ("TimeUsed", 20),
    ("TimeLimit", 20),
    ("SubmitTime", 25),
    ("StartTime", 25),
    ("NumNodes", 10),
    ("NumCPUs", 10),
    ("NumTasks", 10),
    ("MinMemory", 20),
    ("tres-alloc", 400),
    ("tres-per-job", 150),
    ("tres-per-node", 150),
    ("tres-per-task", 150),
    ("PriorityLong", 15),
    ("NodeList", 1500),
    ("SchedNodes", 300),
    ("Dependency", 150),
    ("WorkDir", 400),
    ("StdOut", 400),
    ("StdErr", 400),
    ("Command", 400),
)
SQUEUE_FIELD_NAMES = tuple(name for name, _ in SQUEUE_FIELDS)

# Job names, paths and reasons may contain "|", Slurm's default separator, which would shift
# the later columns. sshare has no --delimiter option; account and user names cannot contain "|".
DELIMITER = "\t"
SSHARE_DELIMITER = "|"

SSHARE_FIELDS = (
    "Account",
    "User",
    "RawShares",
    "NormShares",
    "RawUsage",
    "EffectvUsage",
    "FairShare",
    "LevelFS",
)

SACCT_HISTORY_FIELDS = (
    "JobID",
    "JobIDRaw",
    "JobName",
    "Partition",
    "Account",
    "User",
    "State",
    "ExitCode",
    "Elapsed",
    "Timelimit",
    "AllocCPUS",
    "AllocTRES",
    "ReqMem",
    "MaxRSS",
    "TotalCPU",
    "Submit",
    "Start",
    "End",
    "NodeList",
    "StdOut",
    "WorkDir",
)
SACCT_RECENT_FIELDS = ("User", "End")
SACCT_USAGE_FIELDS = ("Account", "Partition", "AllocTRES", "NodeList", "Start", "End")


def _slurm_time(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S")


def nodes() -> list[str]:
    # -d adds GresUsed=, the allocated GPUs when AccountingStorageTRES lacks gres/gpu
    return ["scontrol", "-d", "-o", "show", "node"]


def partitions() -> list[str]:
    return ["scontrol", "-o", "show", "partition"]


def reservations() -> list[str]:
    return ["scontrol", "-o", "show", "reservation"]


def jobs() -> list[str]:
    fmt = ",".join(f"{name}:{width}{DELIMITER}" for name, width in SQUEUE_FIELDS)
    return ["squeue", "-h", "--noconvert", "-O", fmt]


def shares() -> list[str]:
    return ["sshare", "-a", "-P", "-n", "-o", ",".join(SSHARE_FIELDS)]


def scheduler() -> list[str]:
    return ["sdiag"]


def history(user: str, since: datetime) -> list[str]:
    return [
        "sacct",
        "-u",
        user,
        "-S",
        _slurm_time(since),
        "-P",
        "-n",
        "--delimiter=" + DELIMITER,
        "--delimiter=" + DELIMITER,
        "--delimiter=" + DELIMITER,
        "--noconvert",
        "--format=" + ",".join(SACCT_HISTORY_FIELDS),
    ]


def recent_jobs(since: datetime) -> list[str]:
    return [
        "sacct",
        "--allusers",
        "-X",
        "-S",
        _slurm_time(since),
        "-P",
        "-n",
        "--format=" + ",".join(SACCT_RECENT_FIELDS),
    ]


def account_usage(since: datetime) -> list[str]:
    return [
        "sacct",
        "--allusers",
        "-X",
        "-S",
        _slurm_time(since),
        "-P",
        "-n",
        "--noconvert",
        "--format=" + ",".join(SACCT_USAGE_FIELDS),
    ]


def node_detail(name: str) -> list[str]:
    return ["scontrol", "show", "node", name]


def job_detail(job_id: str) -> list[str]:
    return ["scontrol", "show", "job", job_id]


def job_efficiency(job_id: str) -> list[str]:
    return ["seff", job_id]


def hold(job_id: str) -> list[str]:
    return ["scontrol", "hold", job_id]


def release(job_id: str) -> list[str]:
    return ["scontrol", "release", job_id]


def cancel(job_id: str) -> list[str]:
    return ["scancel", job_id]


def version() -> list[str]:
    return ["scontrol", "version"]
