#!/usr/bin/env python3
"""Generate tests/fixtures/hybrid-cloud: command outputs of a hybrid on-premise/cloud cluster.

Deterministic (fixed seed). Node classes, node names and partitions follow a
real cluster; user, account and job names are invented.

    python tools/make_test_fixtures.py
"""

from __future__ import annotations

import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slurmtui.slurm.commands import DELIMITER, SACCT_HISTORY_FIELDS, SQUEUE_FIELDS
from slurmtui.slurm.parsers import hostlist

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "hybrid-cloud"
rng = random.Random(20261019)
NOW = datetime(2026, 10, 19, 14, 30, 0)
WHOAMI = "demo"


def ts(when: datetime | None) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S") if when else "Unknown"


def dur(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{days}-{hours:02d}:{minutes:02d}:{seconds:02d}" if days else f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# --- node classes -----------------------------------------------------------
# (prefix, first, count, partitions, gres, features, cpus, mem_mb, sockets, cores, threads)
NODE_CLASSES = [
    ("htc-cmp", 101, 46, ["small", "big"], None, "Intel,Xeon,Gold6338,Infiniband", 128, 1024000, 2, 32, 2),
    ("htc-cmp", 200, 32, ["small", "big"], None, "Intel,Xeon,Gold6342,Infiniband", 64, 120000, 2, 16, 2),
    ("htc-cmp", 300, 14, ["small", "big", "high-mem"], None, "AMD,EPYC9475F,Infiniband", 192, 1547708, 2, 48, 2),
    ("htc-cmp", 501, 7, ["small", "big"], None, "AMD,EPYC7542,Infiniband", 128, 1031500, 2, 32, 2),
    ("htc-cmp", 1, 4, ["small", "high-mem"], None, "Intel,Xeon,Gold6246,Infiniband", 96, 1031400, 2, 24, 2),
    ("htc-cmp", 520, 20, ["small", "big"], None, "Intel,Xeon,virtual", 8, 64310, 1, 4, 2),
    (
        "htc-gpu",
        12,
        21,
        ["small", "gpu"],
        "gpu:a40:4(S:0-1)",
        "Intel,Xeon,Gold6338,A40,A40-48GB,GPU-48GB,Infiniband",
        128,
        512000,
        2,
        32,
        2,
    ),
    (
        "htc-gpu",
        100,
        6,
        ["small", "gpu"],
        "gpu:h200:4(S:0-1)",
        "AMD,EPYC9335,H200,H200-141GB,GPU-141GB,Infiniband",
        128,
        2321874,
        2,
        32,
        2,
    ),
    (
        "htc-gpu",
        110,
        5,
        ["small", "gpu"],
        "gpu:h200:4(S:0-1)",
        "AMD,EPYC9555,H200,H200-141GB,GPU-141GB,Infiniband",
        256,
        1547685,
        2,
        64,
        2,
    ),
    (
        "htc-gpu",
        1,
        4,
        ["small", "gpu"],
        "gpu:a100:4(S:0)",
        "AMD,EPYC7502P,A100,A100-40GB,GPU-40GB",
        32,
        515500,
        1,
        32,
        1,
    ),
    (
        "htc-gpu",
        33,
        4,
        ["small", "gpu"],
        "gpu:a100:4(S:0-1)",
        "AMD,EPYC7513,A100,A100-80GB,GPU-80GB,Infiniband",
        128,
        1547700,
        2,
        32,
        2,
    ),
    ("cmp", 820, 40, ["gcp1-cmp"], None, "AMD,EPYC9B45,c4d-highcpu-64", 64, 120000, 1, 32, 2),
    (
        "gpu",
        840,
        20,
        ["gcp1-gpu", "gcp1-gpu-l4"],
        "gpu:l4-gcp:8(S:0-1)",
        "Intel,Xeon,Platinum8273CL,L4,L4-24GB,GPU-24GB,g2-standard-96",
        96,
        384000,
        2,
        24,
        2,
    ),
    (
        "gpu",
        800,
        18,
        ["gcp1-gpu", "gcp1-gpu-h100"],
        "gpu:h100-gcp:8(S:0-1)",
        "Intel,Xeon,Platinum8481C,H100,H100-80GB,GPU-80GB,a3-highgpu-8g",
        208,
        1872000,
        2,
        52,
        2,
    ),
    (
        "gpu",
        818,
        6,
        ["gcp1-gpu", "gcp1-gpu-h100"],
        "gpu:h100-gcp:1",
        "Intel,Xeon,Platinum8481C,H100,H100-80GB,GPU-80GB,a3-highgpu-1g",
        26,
        234000,
        1,
        13,
        2,
    ),
    (
        "gpu",
        920,
        10,
        ["gcp1-gpu", "gcp1-gpu-a100"],
        "gpu:a100-gcp:8(S:0-1)",
        "Intel,Xeon,Platinum8273CL,A100,A100-40GB,GPU-40GB,a2-highgpu-8g",
        96,
        680000,
        2,
        24,
        2,
    ),
    (
        "gpu",
        930,
        10,
        ["gcp1-gpu", "gcp1-gpu-a100"],
        "gpu:a100-gcp:4",
        "Intel,Xeon,Platinum8273CL,A100,A100-40GB,GPU-40GB,a2-highgpu-4g",
        48,
        340000,
        1,
        24,
        2,
    ),
    (
        "gpu",
        940,
        20,
        ["gcp1-gpu", "gcp1-gpu-a100-80g"],
        "gpu:a100-80g-gcp:8(S:0-1)",
        "Intel,Xeon,Platinum8273CL,A100,A100-80GB,GPU-80GB,a2-ultragpu-8g",
        96,
        1360000,
        2,
        24,
        2,
    ),
    (
        "gpu",
        860,
        4,
        ["gcp1-gpu", "gcp1-gpu-h200"],
        "gpu:h200-gcp:8(S:0-1)",
        "Intel,Xeon,Platinum8581C,H200,H200-141GB,GPU-141GB,a3-ultragpu-8g",
        224,
        2952000,
        2,
        56,
        2,
    ),
    (
        "gpu",
        880,
        2,
        ["gcp1-gpu", "gcp1-gpu-b200"],
        "gpu:b200-gcp:8(S:0-1)",
        "Intel,Xeon,Platinum8581C,B200,B200-180GB,GPU-180GB,a4-highgpu-8g",
        224,
        3968000,
        2,
        56,
        2,
    ),
    (
        "gpu",
        870,
        4,
        ["gcp1-gpu", "gcp1-gpu-rtx-pro-6000"],
        "gpu:rtx-pro-6000-gcp:8(S:0-1)",
        "AMD,EPYC9B45,RTX-PRO-6000,RTX-PRO-6000-96GB,GPU-96GB,g4-standard-384",
        384,
        1440000,
        2,
        96,
        2,
    ),
    (
        "gpu",
        900,
        2,
        ["gcp1-gpu-a100-npr"],
        "gpu:a100-gcp-npr:1",
        "Intel,Xeon,Platinum8273CL,A100,A100-40GB,GPU-40GB,a2-highgpu-1g",
        12,
        85000,
        1,
        6,
        2,
    ),
    (
        "gpu",
        912,
        2,
        ["gcp1-gpu-a100-80g-npr"],
        "gpu:a100-80g-gcp-npr:1",
        "Intel,Xeon,Platinum8273CL,A100,A100-80GB,GPU-80GB,a2-ultragpu-1g",
        12,
        170000,
        1,
        6,
        2,
    ),
]

PARTITION_MAXTIME = {
    "small": "2-02:00:00",
    "big": "30-00:00:00",
    "high-mem": "2-02:00:00",
    "gpu": "30-00:00:00",
    "gcp1-cmp": "2-02:00:00",
    "gcp1-gpu": "2-02:00:00",
    "gcp1-gpu-l4": "2-02:00:00",
    "gcp1-gpu-a100": "2-02:00:00",
    "gcp1-gpu-a100-npr": "7-00:00:00",
    "gcp1-gpu-a100-80g": "2-02:00:00",
    "gcp1-gpu-a100-80g-npr": "7-00:00:00",
    "gcp1-gpu-h100": "2-02:00:00",
    "gcp1-gpu-h200": "2-02:00:00",
    "gcp1-gpu-b200": "2-02:00:00",
    "gcp1-gpu-rtx-pro-6000": "2-02:00:00",
}

ACCOUNTS = [
    "mllab",
    "optim",
    "energy",
    "numerics",
    "vision-lab",
    "bioinf",
    "climate",
    "robotics",
    "nlp",
    "physics",
    "quantum",
    "teaching",
]
FIRST = [
    "anna",
    "ben",
    "chen",
    "dora",
    "emil",
    "fatima",
    "greg",
    "hana",
    "igor",
    "jana",
    "kemal",
    "lena",
    "marc",
    "nina",
    "omar",
    "pia",
    "quinn",
    "rosa",
    "sven",
    "tara",
    "uwe",
    "vera",
    "wim",
    "xenia",
    "yusuf",
    "zoe",
    "aiden",
    "bela",
    "carl",
    "dani",
    "elif",
    "finn",
    "gala",
    "hugo",
    "ines",
    "jon",
    "kai",
    "lia",
    "mila",
    "noah",
]
USERS = [f"{name}{rng.randint(1, 99):02d}" for name in FIRST] + [WHOAMI]
USER_ACCOUNT = {user: rng.choice(ACCOUNTS) for user in USERS}
USER_ACCOUNT[WHOAMI] = "mllab"
EXTRA_ACCOUNT = {user: rng.choice(ACCOUNTS) for user in rng.sample(USERS, 8)}
JOB_NAMES = [
    "train",
    "eval",
    "preprocess",
    "sweep",
    "finetune",
    "simulate",
    "render",
    "align",
    "bench",
    "analysis",
    "jupyter",
    "optimize",
    "sample",
    "ablation",
    "tokenize",
    "fold",
    "dock",
    "mesh",
    "solve",
    "postproc",
]
REASONS = [
    "Priority",
    "Resources",
    "Dependency",
    "QOSMaxJobsPerUserLimit",
    "ReqNodeNotAvail, Reserved for maintenance",
    "AssocGrpCpuLimit",
    "BeginTime",
    "DependencyNeverSatisfied",
    "JobHeldUser",
    "Nodes required for job are DOWN, DRAINED or reserved for jobs in higher priority partitions",
]


class NodeInfo:
    def __init__(self, name, partitions, gres, features, cpus, mem_mb, sockets, cores, threads, cloud):
        self.name = name
        self.partitions = partitions
        self.gres = gres
        self.features = features
        self.cpus = cpus
        self.mem_mb = mem_mb
        self.sockets, self.cores, self.threads = sockets, cores, threads
        self.cloud = cloud
        self.gpu_type = gres.split(":")[1] if gres else None
        self.gpus = int(gres.split(":")[2].split("(")[0]) if gres else 0
        self.alloc_cpus = 0
        self.alloc_mem = 0
        self.alloc_gpus = 0
        self.state = None
        self.reason = None
        self.flags = []


nodes: list[NodeInfo] = []
for prefix, first, count, parts, gres, features, cpus, mem, sockets, cores, threads in NODE_CLASSES:
    for i in range(count):
        number = first + i
        name = f"{prefix}{number:03d}"
        nodes.append(
            NodeInfo(
                name, parts, gres, features, cpus, mem, sockets, cores, threads, cloud=not prefix.startswith("htc-")
            )
        )
by_name = {node.name: node for node in nodes}

# pick which cloud nodes are powered up
for node in nodes:
    if node.cloud:
        node.powered = rng.random() < 0.28
    else:
        node.powered = True

# drained / down nodes
drained = rng.sample([n for n in nodes if not n.cloud], 5)
for node in drained[:3]:
    node.flags.append("DRAIN")
    node.reason = rng.choice(["GPU failure, waiting for vendor", "Memory errors", "Kernel update pending"])
for node in drained[3:]:
    node.state = "DOWN"
    node.reason = "Not responding"
cloud_down = rng.choice([n for n in nodes if n.cloud and not n.powered])
cloud_down.state = "DOWN"
cloud_down.reason = "Node unexpectedly rebooted"
powering = rng.choice([n for n in nodes if n.cloud and not n.powered and n.state is None])
powering.powering_up = True

# --- jobs -------------------------------------------------------------------
part_nodes: dict[str, list[NodeInfo]] = defaultdict(list)
for node in nodes:
    for part in node.partitions:
        part_nodes[part].append(node)

jobs = []
job_id = 4093000


def alloc_node(partition, want_cpus, want_gpus, want_mem_mb):
    candidates = [
        n
        for n in part_nodes[partition]
        if n.powered
        and n.state != "DOWN"
        and "DRAIN" not in n.flags
        and n.cpus - n.alloc_cpus >= want_cpus
        and n.gpus - n.alloc_gpus >= want_gpus
        and n.mem_mb - n.alloc_mem >= want_mem_mb
    ]
    if not candidates:
        return None
    node = rng.choice(candidates)
    node.alloc_cpus += want_cpus
    node.alloc_gpus += want_gpus
    node.alloc_mem += want_mem_mb
    return node


def tres(cpus, mem_mb, nodes_count, gpus, gpu_type):
    parts = [f"cpu={cpus}", f"mem={mem_mb}M", f"node={nodes_count}", f"billing={cpus}"]
    if gpus:
        parts.append(f"gres/gpu={gpus}")
        parts.append(f"gres/gpu:{gpu_type}={gpus}")
    return ",".join(parts)


gpu_partitions = [p for p in PARTITION_MAXTIME if "gpu" in p]
cpu_partitions = ["small", "big", "high-mem", "gcp1-cmp"]
weights = {
    "small": 30,
    "big": 15,
    "high-mem": 3,
    "gpu": 25,
    "gcp1-cmp": 6,
    "gcp1-gpu": 10,
    "gcp1-gpu-h100": 5,
    "gcp1-gpu-l4": 4,
    "gcp1-gpu-a100": 3,
    "gcp1-gpu-a100-80g": 3,
    "gcp1-gpu-h200": 1,
    "gcp1-gpu-b200": 1,
    "gcp1-gpu-rtx-pro-6000": 1,
    "gcp1-gpu-a100-npr": 1,
    "gcp1-gpu-a100-80g-npr": 1,
}
partition_choices = list(weights)
partition_weights = list(weights.values())

for _ in range(420):
    job_id += rng.randint(1, 3)
    user = rng.choice(USERS) if rng.random() > 0.08 else WHOAMI
    account = USER_ACCOUNT[user]
    partition = rng.choices(partition_choices, partition_weights)[0]
    is_gpu = "gpu" in partition
    gpus = rng.choice([1, 1, 2, 4, 8]) if is_gpu else 0
    cpus = rng.choice([2, 4, 8, 16, 32]) if not is_gpu else gpus * rng.choice([4, 8, 10])
    mem_mb = cpus * rng.choice([2000, 3000, 4000, 8000])
    time_limit = timedelta(hours=rng.choice([1, 2, 4, 8, 12, 24, 48, 50, 120]))
    name = rng.choice(JOB_NAMES) + rng.choice(["", "", f"_{rng.randint(1, 40)}", "-v2", "-large"])
    submit = NOW - timedelta(hours=rng.uniform(0.1, 72))
    node = alloc_node(partition, cpus, gpus, mem_mb)
    workdir = f"/scratch/{user}/{name.split('_')[0]}"
    array = rng.random() < 0.12
    state, reason, run_time, start, node_list, tres_alloc = (
        "PENDING",
        rng.choice(REASONS),
        timedelta(0),
        None,
        "",
        "N/A",
    )
    task_spec = None
    if node is not None and rng.random() < 0.8:
        state = "RUNNING" if rng.random() > 0.03 else rng.choice(["COMPLETING", "CONFIGURING"])
        max_run = min(time_limit, NOW - submit)
        run_time = timedelta(seconds=rng.uniform(60, max(61, max_run.total_seconds())))
        start = NOW - run_time
        reason = "None"
        node_list = node.name
        tres_alloc = tres(cpus, mem_mb, 1, gpus, node.gpu_type)
        if array:
            task_spec = str(rng.randint(1, 40))
    elif node is not None:
        # release the allocation: job stays pending
        node.alloc_cpus -= cpus
        node.alloc_gpus -= gpus
        node.alloc_mem -= mem_mb
        if array:
            lo = rng.randint(1, 5)
            task_spec = f"[{lo}-{lo + rng.randint(5, 60)}{rng.choice(['', '', '%4'])}]"
    elif array:
        lo = rng.randint(1, 5)
        task_spec = f"[{lo}-{lo + rng.randint(5, 60)}]"
    array_id = f"{job_id}_{task_spec}" if task_spec else str(job_id)
    tres_per_node = f"gres/gpu:{gpus}" if gpus else "N/A"
    tres_per_task = "N/A"
    if gpus and state == "PENDING" and job_id % 7 == 0:
        tres_per_node, tres_per_task = "N/A", f"gres/gpu:{gpus}"
    dependency = f"afterok:{job_id - rng.randint(1, 50)}" if reason == "Dependency" else "(null)"
    row = {
        "JobArrayID": array_id,
        "JobID": str(job_id),
        "ArrayJobID": str(job_id) if task_spec else "N/A",
        "ArrayTaskID": task_spec if task_spec else "N/A",
        "Partition": partition,
        "Name": name,
        "UserName": user,
        "Account": account,
        "QOS": "normal",
        "State": state,
        "Reason": reason,
        "TimeUsed": dur(run_time) if state != "PENDING" else "0:00",
        "TimeLimit": dur(time_limit),
        "SubmitTime": ts(submit),
        "StartTime": ts(start) if start else "N/A",
        "NumNodes": "1",
        "NumCPUs": str(cpus),
        "NumTasks": "1",
        "MinMemory": f"{mem_mb // cpus}M" if rng.random() < 0.5 else f"{mem_mb}M",
        "tres-alloc": tres_alloc,
        "tres-per-job": "N/A",
        "tres-per-node": tres_per_node,
        "tres-per-task": tres_per_task,
        "PriorityLong": str(rng.randint(10000, 60000)),
        "NodeList": node_list,
        "SchedNodes": "(null)",
        "Dependency": dependency,
        "WorkDir": workdir,
        "StdOut": f"{workdir}/slurm-{job_id}.out",
        "StdErr": f"{workdir}/slurm-{job_id}.out",
        "Command": f"{workdir}/run.sh",
    }
    jobs.append(row)

# two multi-node jobs on big
for _ in range(2):
    job_id += 1
    user = rng.choice(USERS)
    picked = [n for n in part_nodes["big"] if n.powered and n.state != "DOWN" and n.alloc_cpus == 0][:3]
    if len(picked) < 2:
        break
    for n in picked:
        n.alloc_cpus = n.cpus
        n.alloc_mem = n.mem_mb // 2
    cpus = sum(n.cpus for n in picked)
    mem = sum(n.mem_mb // 2 for n in picked)
    run = timedelta(hours=rng.uniform(1, 30))
    jobs.append(
        {
            **jobs[-1],
            "JobArrayID": str(job_id),
            "JobID": str(job_id),
            "ArrayJobID": "N/A",
            "ArrayTaskID": "N/A",
            "Partition": "big",
            "Name": "mpi_solver",
            "UserName": user,
            "Account": USER_ACCOUNT[user],
            "State": "RUNNING",
            "Reason": "None",
            "TimeUsed": dur(run),
            "TimeLimit": "2-00:00:00",
            "SubmitTime": ts(NOW - run - timedelta(hours=2)),
            "StartTime": ts(NOW - run),
            "NumNodes": str(len(picked)),
            "NumCPUs": str(cpus),
            "NumTasks": str(cpus),
            "MinMemory": f"{mem // len(picked)}M",
            "tres-alloc": tres(cpus, mem, len(picked), 0, None),
            "tres-per-node": "N/A",
            "tres-per-task": "N/A",
            "NodeList": hostlist.contract([n.name for n in picked]),
            "Dependency": "(null)",
            "WorkDir": f"/scratch/{user}/mpi",
            "StdOut": f"/scratch/{user}/mpi/slurm-{job_id}.out",
            "StdErr": f"/scratch/{user}/mpi/slurm-{job_id}.out",
            "Command": f"/scratch/{user}/mpi/run.sh",
            "PriorityLong": "25000",
        }
    )

# node states from allocations
for node in nodes:
    if node.state == "DOWN":
        pass
    elif node.alloc_cpus >= node.cpus:
        node.state = "ALLOCATED"
    elif node.alloc_cpus > 0:
        node.state = "MIXED"
    else:
        node.state = "IDLE"
    if node.cloud:
        node.flags.append("CLOUD")
        if not node.powered:
            node.flags.append("POWERED_DOWN")
    if getattr(node, "powering_up", False):
        node.flags.remove("POWERED_DOWN")
        node.flags.append("POWERING_UP")
planned = rng.sample([n for n in nodes if n.state == "MIXED" and not n.cloud], 3)
for node in planned:
    node.flags.append("PLANNED")

# --- write nodes.txt --------------------------------------------------------
node_lines = []
for node in nodes:
    state = "+".join([node.state, *node.flags])
    cfg = f"cpu={node.cpus},mem={node.mem_mb}M,billing={node.cpus}"
    if node.gpus:
        cfg += f",gres/gpu={node.gpus},gres/gpu:{node.gpu_type}={node.gpus}"
    alloc = ""
    if node.alloc_cpus:
        alloc = f"cpu={node.alloc_cpus},mem={node.alloc_mem}M"
        if node.alloc_gpus:
            alloc += f",gres/gpu={node.alloc_gpus},gres/gpu:{node.gpu_type}={node.alloc_gpus}"
    reason = f" Reason={node.reason} [root@{ts(NOW - timedelta(hours=rng.randint(2, 90)))}]" if node.reason else ""
    if node.gpus:
        idx = "N/A" if not node.alloc_gpus else ("0" if node.alloc_gpus == 1 else f"0-{node.alloc_gpus - 1}")
        gres_used = f"gpu:{node.gpu_type}:{node.alloc_gpus}(IDX:{idx})"
    else:
        gres_used = ""
    load = f"{node.alloc_cpus * rng.uniform(0.6, 1.1):.2f}" if node.powered else "0.00"
    free_mem = node.mem_mb - node.alloc_mem - rng.randint(1000, 8000) if node.powered else node.mem_mb - 73
    boot = ts(NOW - timedelta(days=rng.randint(1, 40)))
    node_lines.append(
        f"NodeName={node.name} Arch=x86_64 CoresPerSocket={node.cores} CPUAlloc={node.alloc_cpus} CPUEfctv={node.cpus} "
        f"CPUTot={node.cpus} CPULoad={load} AvailableFeatures={node.features} ActiveFeatures={node.features} "
        f"Gres={node.gres or '(null)'} GresDrain=N/A GresUsed={gres_used} NodeAddr={node.name} NodeHostName={node.name} Version=24.11.7 "
        f"OS=Linux 6.12.111+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.111-1 (2026-09-28) RealMemory={node.mem_mb} "
        f"AllocMem={node.alloc_mem} FreeMem={max(free_mem, 0)} Sockets={node.sockets} Boards=1 State={state} "
        f"ThreadsPerCore={node.threads} TmpDisk=0 Weight=1 Owner=N/A MCS_label=N/A Partitions={','.join(node.partitions)} "
        f"BootTime={boot} SlurmdStartTime={boot} LastBusyTime={ts(NOW - timedelta(minutes=rng.randint(1, 600)))} "
        f"ResumeAfterTime=None CfgTRES={cfg} AllocTRES={alloc} CurrentWatts=0 AveWatts=0{reason}"
    )
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "nodes.txt").write_text("\n".join(node_lines) + "\n")

# --- partitions.txt ---------------------------------------------------------
partition_lines = []
for part, max_time in PARTITION_MAXTIME.items():
    members = part_nodes[part]
    total_cpus = sum(n.cpus for n in members)
    total_mem = sum(n.mem_mb for n in members)
    gpu_tres = ""
    gpus_by_type = defaultdict(int)
    for n in members:
        if n.gpus:
            gpus_by_type[n.gpu_type] += n.gpus
    if gpus_by_type:
        gpu_tres = f",gres/gpu={sum(gpus_by_type.values())}," + ",".join(
            f"gres/gpu:{t}={c}" for t, c in sorted(gpus_by_type.items())
        )
    default = "YES" if part == "small" else "NO"
    partition_lines.append(
        f"PartitionName={part} AllowGroups=ALL AllowAccounts=ALL AllowQos=ALL AllocNodes=ALL Default={default} QoS=N/A "
        f"DefaultTime=01:00:00 DisableRootJobs=NO ExclusiveUser=NO ExclusiveTopo=NO GraceTime=0 Hidden=NO "
        f"MaxNodes={'UNLIMITED' if part in ('big', 'gpu') else 1} MaxTime={max_time} MinNodes=0 LLN=NO MaxCPUsPerNode=UNLIMITED "
        f"MaxCPUsPerSocket=UNLIMITED Nodes={hostlist.contract([n.name for n in members])} PriorityJobFactor=10 PriorityTier=10 "
        f"RootOnly=NO ReqResv=NO OverSubscribe=NO OverTimeLimit=NONE PreemptMode=OFF State=UP TotalCPUs={total_cpus} "
        f"TotalNodes={len(members)} SelectTypeParameters=NONE JobDefaults=(null) DefMemPerNode=UNLIMITED "
        f"MaxMemPerCPU=9223372036854775807 TRES=cpu={total_cpus},mem={total_mem}M,node={len(members)},billing={total_cpus}{gpu_tres} "
        f"ResumeTimeout=GLOBAL SuspendTimeout=GLOBAL SuspendTime=GLOBAL PowerDownOnIdle=NO"
    )
(OUT / "partitions.txt").write_text("\n".join(partition_lines) + "\n")

# --- jobs.txt ---------------------------------------------------------------
job_lines = ["".join(f"{row[name]}{DELIMITER}" for name, _ in SQUEUE_FIELDS) for row in jobs]
(OUT / "jobs.txt").write_text("\n".join(job_lines) + "\n")

# --- reservations.txt -------------------------------------------------------
maint_nodes = [n.name for n in part_nodes["high-mem"]][:6]
gpu_res_nodes = [n.name for n in part_nodes["gpu"]][:4]
reservations = [
    f"ReservationName=maint_2026_10 StartTime={ts(NOW - timedelta(hours=3))} EndTime={ts(NOW + timedelta(hours=21))} Duration=1-00:00:00 "
    f"Nodes={hostlist.contract(maint_nodes)} NodeCnt={len(maint_nodes)} CoreCnt=576 Features=(null) PartitionName=(null) Flags=MAINT,SPEC_NODES "
    f"TRES=cpu=1152 Users=(null) Groups=(null) Accounts=root Licenses=(null) State=ACTIVE BurstBuffer=(null) MaxStartDelay=(null)",
    f"ReservationName=course_dl StartTime={ts(NOW + timedelta(days=2))} EndTime={ts(NOW + timedelta(days=2, hours=6))} Duration=06:00:00 "
    f"Nodes={hostlist.contract(gpu_res_nodes)} NodeCnt={len(gpu_res_nodes)} CoreCnt=256 Features=(null) PartitionName=gpu Flags=SPEC_NODES "
    f"TRES=cpu=512,gres/gpu=16 Users=anna07,ben12 Groups=(null) Accounts=(null) Licenses=(null) State=INACTIVE BurstBuffer=(null) MaxStartDelay=(null)",
]
(OUT / "reservations.txt").write_text("\n".join(reservations) + "\n")

# --- shares.txt -------------------------------------------------------------
share_lines = ["root|||1.000000|987654321|1.000000|||"]
members = defaultdict(list)
for user, account in USER_ACCOUNT.items():
    members[account].append(user)
for user, account in EXTRA_ACCOUNT.items():
    if user not in members[account]:
        members[account].append(user)
total_raw = 0
account_raw = {}
for account in ACCOUNTS:
    account_raw[account] = rng.randint(100000, 90000000)
    total_raw += account_raw[account]
for account in ACCOUNTS:
    eff = account_raw[account] / total_raw
    norm = 1 / len(ACCOUNTS)
    level_fs = norm / eff if eff else float("inf")
    share_lines.append(f"{account}||1|{norm:.6f}|{account_raw[account]}|{eff:.6f}||{level_fs:.6f}")
    users_in = members[account]
    for user in users_in:
        raw = rng.randint(0, account_raw[account] // max(len(users_in), 1))
        user_eff = raw / total_raw
        fs = max(0.0, min(1.0, 1 - user_eff * rng.uniform(5, 40)))
        share_lines.append(f"{account}|{user}|1|{norm / len(users_in):.6f}|{raw}|{user_eff:.6f}|{fs:.6f}|")
(OUT / "shares.txt").write_text("\n".join(share_lines) + "\n")

# --- scheduler.txt ----------------------------------------------------------
running_jobs = sum(1 for r in jobs if r["State"] == "RUNNING")
pending_jobs = sum(1 for r in jobs if r["State"] == "PENDING")
(OUT / "scheduler.txt").write_text(f"""*******************************************************
sdiag output at {NOW.strftime("%a %b %d %H:%M:%S %Y")} (1792420200)
Data since      {(NOW - timedelta(days=3)).strftime("%a %b %d %H:%M:%S %Y")} (1792161000)
*******************************************************
Server thread count:  3
RPC queue enabled:    0
Agent queue size:     0
Agent count:          0
Agent thread count:   0
DBD Agent queue size: 0

Jobs submitted: 18342
Jobs started:   17911
Jobs completed: 17654
Jobs canceled:  412
Jobs failed:    0
Jobs pending:   {pending_jobs}
Jobs running:   {running_jobs}

Job states ts:  {NOW.strftime("%a %b %d %H:%M:%S %Y")} (1792420190)

Main schedule statistics (microseconds):
\tLast cycle:   41235
\tMax cycle:    1287654
\tTotal cycles: 182334
\tMean cycle:   53112
\tMean depth cycle:  89
\tCycles per minute: 42
\tLast queue length: {pending_jobs}

Main scheduler exit:
\tEnd of job queue:  14012
\tHit default_queue_depth: 0
\tHit sched_max_job_start: 0
\tBlocked on licenses: 0
\tHit max_rpc_cnt: 0
\tTimeout (max_sched_time): 0

Backfilling stats
\tTotal backfilled jobs (since last slurm start): 9123
\tTotal backfilled jobs (since last stats cycle start): 371
\tTotal backfilled heterogeneous job components: 0
\tTotal cycles: 4321
\tLast cycle when: {NOW.strftime("%a %b %d %H:%M:%S %Y")} (1792420100)
\tLast cycle: 2213456
\tMax cycle:  8123456
\tMean cycle: 1456789
\tLast depth cycle: 613
\tLast depth cycle (try sched): 142
\tDepth Mean: 598
\tDepth Mean (try depth): 131
\tLast queue length: {pending_jobs}
\tQueue length mean: 540
\tLast table size: 118
\tMean table size: 102

Latency for 1000 calls to gettimeofday(): 23 microseconds

Remote Procedure Call statistics by message type
\tREQUEST_PARTITION_INFO                  ( 2009) count:122338 ave_time:120    total_time:14680560
\tREQUEST_JOB_INFO_SINGLE                 ( 2021) count:98765  ave_time:1850   total_time:182715250
\tREQUEST_NODE_INFO                       ( 2007) count:65432  ave_time:2100   total_time:137407200
""")

# --- history.txt (sacct of the demo user) -----------------------------------
history_lines = []
hid = 4080000
states = ["COMPLETED"] * 10 + ["FAILED", "TIMEOUT", "CANCELLED by 3375", "OUT_OF_MEMORY", "NODE_FAIL", "RUNNING"]
for _ in range(45):
    hid += rng.randint(1, 20)
    state = rng.choice(states)
    partition = rng.choice(["small", "small", "big", "gpu", "gcp1-gpu-h100", "gcp1-cmp"])
    gpus = rng.choice([1, 2, 4]) if "gpu" in partition else 0
    cpus = gpus * 8 if gpus else rng.choice([1, 2, 4, 8, 16])
    mem_mb = cpus * rng.choice([2000, 4000, 8000])
    limit = timedelta(hours=rng.choice([1, 4, 12, 24, 48]))
    submit = NOW - timedelta(hours=rng.uniform(1, 160))
    start = submit + timedelta(minutes=rng.uniform(0, 120))
    if state == "TIMEOUT":
        elapsed = limit
    elif state == "RUNNING":
        elapsed = min(NOW - start, limit)
    else:
        elapsed = timedelta(seconds=rng.uniform(30, limit.total_seconds()))
    end = start + elapsed if state != "RUNNING" else None
    if end and end > NOW:
        end = NOW - timedelta(minutes=1)
        elapsed = end - start
    node = rng.choice(part_nodes[partition]).name
    name = rng.choice(JOB_NAMES)
    tres_alloc = f"billing={cpus},cpu={cpus},mem={mem_mb}M,node=1" + (f",gres/gpu={gpus}" if gpus else "")
    cpu_eff = rng.uniform(0.1, 1.0)
    total_cpu = timedelta(seconds=elapsed.total_seconds() * cpus * cpu_eff)
    rss_kb = int(mem_mb * 1024 * rng.uniform(0.05, 1.3 if state == "OUT_OF_MEMORY" else 0.95))
    exit_code = {
        "COMPLETED": "0:0",
        "FAILED": f"{rng.choice([1, 2, 137])}:0",
        "TIMEOUT": "0:0",
        "OUT_OF_MEMORY": "0:125",
        "NODE_FAIL": "0:0",
        "RUNNING": "0:0",
    }.get(state.split()[0], "0:0")
    base = {
        "JobID": str(hid),
        "JobIDRaw": str(hid),
        "JobName": name,
        "Partition": partition,
        "Account": "mllab",
        "User": WHOAMI,
        "State": state,
        "ExitCode": exit_code,
        "Elapsed": dur(elapsed),
        "Timelimit": dur(limit),
        "AllocCPUS": str(cpus),
        "AllocTRES": tres_alloc,
        "ReqMem": f"{mem_mb}M",
        "MaxRSS": "",
        "TotalCPU": dur(total_cpu),
        "Submit": ts(submit),
        "Start": ts(start),
        "End": ts(end) if end else "Unknown",
        "NodeList": node,
        "StdOut": f"/scratch/{WHOAMI}/{name}/slurm-%j.out",
        "WorkDir": f"/scratch/{WHOAMI}/{name}",
    }
    history_lines.append(DELIMITER.join(base[f] for f in SACCT_HISTORY_FIELDS))
    for step, step_name in (("batch", "batch"), ("extern", "extern"), ("0", "python")):
        step_row = dict(
            base,
            JobID=f"{hid}.{step}",
            JobIDRaw=f"{hid}.{step}",
            JobName=step_name,
            User="",
            ReqMem="",
            MaxRSS=str((rss_kb if step == "0" else rng.randint(1000, 90000)) * 1024),
            StdOut="",
            WorkDir="",
            Timelimit="",
            State=state.split()[0] if state != "RUNNING" else "RUNNING",
        )
        history_lines.append(DELIMITER.join(step_row[f] for f in SACCT_HISTORY_FIELDS))
(OUT / "history.txt").write_text("\n".join(history_lines) + "\n")

# --- recent_jobs.txt and account_usage.txt ---------------------------------
recent_lines = []
usage_lines = []
for _ in range(2500):
    user = rng.choice(USERS)
    account = USER_ACCOUNT[user]
    partition = rng.choices(partition_choices, partition_weights)[0]
    gpus = rng.choice([1, 2, 4, 8]) if "gpu" in partition else 0
    cpus = gpus * 8 if gpus else rng.choice([1, 2, 4, 8, 16, 32])
    start = NOW - timedelta(hours=rng.uniform(0, 7 * 24))
    end = start + timedelta(hours=rng.uniform(0.1, 30))
    end_text = ts(end) if end < NOW else "Unknown"
    recent_lines.append(DELIMITER.join((user, end_text)))
    node = rng.choice(part_nodes[partition]).name
    tres_alloc = f"billing={cpus},cpu={cpus},mem={cpus * 4000}M,node=1" + (f",gres/gpu={gpus}" if gpus else "")
    usage_lines.append(DELIMITER.join((account, partition, tres_alloc, node, ts(start), end_text)))
(OUT / "recent_jobs.txt").write_text("\n".join(recent_lines) + "\n")
(OUT / "account_usage.txt").write_text("\n".join(usage_lines) + "\n")
(OUT / "version.txt").write_text("slurm 24.11.7\n")
(OUT / "whoami.txt").write_text(WHOAMI + "\n")
print(f"wrote {len(nodes)} nodes, {len(jobs)} jobs, {len(history_lines)} history rows to {OUT}")
