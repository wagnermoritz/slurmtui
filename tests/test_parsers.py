from datetime import timedelta

import pytest

from slurmtui.model.output import expand_output_pattern
from slurmtui.model.states import NodeState
from slurmtui.slurm.commands import DELIMITER, SQUEUE_FIELDS
from slurmtui.slurm.parsers.common import array_task_count, gpu_request, parse_gres, parse_kv_line, parse_tres
from slurmtui.slurm.parsers.jobs import parse_jobs
from slurmtui.slurm.parsers.nodes import parse_nodes, parse_reason
from slurmtui.slurm.parsers.partitions import parse_partitions
from slurmtui.slurm.parsers.reservations import parse_reservations
from slurmtui.slurm.parsers.sacct import parse_history, parse_recent_counts, parse_usage
from slurmtui.slurm.parsers.sdiag import parse_sdiag
from slurmtui.slurm.parsers.shares import parse_shares
from tests.conftest import read

NODE_LINE = (
    "NodeName=gpu012 Arch=x86_64 CoresPerSocket=32 CPUAlloc=64 CPUEfctv=128 CPUTot=128 CPULoad=61.23 "
    "AvailableFeatures=Intel,Xeon,Gold6338,A40,A40-48GB,GPU-48GB,Infiniband "
    "ActiveFeatures=Intel,Xeon,Gold6338,A40,A40-48GB,GPU-48GB,Infiniband Gres=gpu:a40:4(S:0-1) GresDrain=N/A "
    "GresUsed=gpu:a40:2(IDX:0-1) NodeAddr=gpu012 NodeHostName=gpu012 Version=24.11.7 "
    "OS=Linux 6.12.111+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.111-1 "
    "(2026-09-28) RealMemory=512000 AllocMem=256000 FreeMem=200000 Sockets=2 Boards=1 State=MIXED+DRAIN "
    "ThreadsPerCore=2 TmpDisk=0 Weight=1 Owner=N/A MCS_label=N/A Partitions=small,gpu BootTime=2026-10-07T15:16:39 "
    "SlurmdStartTime=2026-10-07T15:16:44 LastBusyTime=Unknown ResumeAfterTime=None "
    "CfgTRES=cpu=128,mem=500G,billing=128,gres/gpu=4,gres/gpu:a40=4 "
    "AllocTRES=cpu=64,mem=250000M,gres/gpu=2,gres/gpu:a40=2 "
    "CurrentWatts=0 AveWatts=0 Reason=GPU failure, waiting for vendor [root@2026-10-18T09:12:00]"
)


def test_parse_kv_line_values_with_spaces():
    fields = parse_kv_line(NODE_LINE)
    assert fields["OS"].startswith("Linux 6.12.111+deb13-amd64 #1 SMP")
    assert fields["Reason"] == "GPU failure, waiting for vendor [root@2026-10-18T09:12:00]"
    assert fields["CfgTRES"] == "cpu=128,mem=500G,billing=128,gres/gpu=4,gres/gpu:a40=4"
    assert fields["AllocTRES"].startswith("cpu=64")
    # key=value fragments inside free text are not keys
    fields = parse_kv_line("NodeName=n1 State=DOWN Reason=GPU xid=79 error, see ticket=42 [root@2026-10-18T09:12:00]")
    assert fields["Reason"] == "GPU xid=79 error, see ticket=42 [root@2026-10-18T09:12:00]"
    assert set(fields) == {"NodeName", "State", "Reason"}


def test_parse_tres():
    tres = parse_tres("cpu=16,mem=63000M,billing=16,gres/gpu=4,gres/gpu:a40=4,energy=12")
    assert (tres.cpu, tres.mem, tres.gpu, tres.gpu_types, tres.other) == (
        16,
        63000 * 2**20,
        4,
        {"a40": 4},
        {"energy": "12"},
    )
    assert tres.gpu_type == "a40"
    assert parse_tres("(null)").is_empty
    assert parse_tres("N/A").is_empty
    assert parse_tres("gres/gpu:h100=2").gpu == 2


def test_gpu_request():
    # squeue prints requests in GRES form, with or without a type, and older releases with "gres:"
    assert gpu_request("gres/gpu:2") == 2
    assert gpu_request("gres/gpu:a40:2") == 2
    assert gpu_request("gres/gpu:a40") == 1
    assert gpu_request("gres:gpu:4") == 4
    assert gpu_request("gres/gpu=2") == 2
    assert gpu_request("gres/gpu:a40:2,gres/gpu:h100:1") == 3
    assert gpu_request("gres/shard:4") == 0
    assert gpu_request("N/A") == 0 and gpu_request(None) == 0


def test_parse_gres():
    assert [(g.name, g.type, g.count) for g in parse_gres("gpu:a40:4(S:0-1),gpu:h100-gcp:1")] == [
        ("gpu", "a40", 4),
        ("gpu", "h100-gcp", 1),
    ]
    assert parse_gres("gpu:4")[0].count == 4
    assert parse_gres("(null)") == []


def test_array_task_count():
    assert array_task_count("4093339_[12-64%5]") == 53
    assert array_task_count("4093339_[1,3,5-6]") == 4
    assert array_task_count("123_7") == 1
    assert array_task_count("123") == 1


def test_node_state():
    for text, compact, style in [
        ("IDLE+CLOUD+POWERED_DOWN", "idle~", "idle"),
        ("MIXED+DRAIN", "drng", "draining"),
        ("IDLE+DRAIN", "drain", "drained"),
        ("ALLOCATED", "alloc", "allocated"),
        ("DOWN+NOT_RESPONDING", "down*", "down"),
        ("MIXED+PLANNED", "mix-", "mixed"),
        ("IDLE+MAINTENANCE", "maint$", "maint"),
        ("ALLOCATED+COMPLETING", "comp", "completing"),
        ("IDLE+CLOUD+POWERING_UP", "idle#", "idle"),
    ]:
        state = NodeState.parse(text)
        assert state.compact == compact, text
        assert state.style_key == style, text
    assert NodeState.parse("idle~").flags == {"powered_down"}
    assert NodeState.parse("drng").base == "mixed"


def test_parse_nodes():
    node = parse_nodes(NODE_LINE)[0]
    assert node.name == "gpu012"
    assert node.state.compact == "drng"
    assert (node.cpus_alloc, node.cpus_total) == (64, 128)
    assert node.mem_total == 512000 * 2**20
    assert node.mem_alloc == 256000 * 2**20
    assert (node.gpus_alloc, node.gpus_total, node.gpu_gres_type) == (2, 4, "a40")
    assert node.partitions == ("small", "gpu")
    assert node.reason is not None and node.reason.user == "root"
    assert node.reason.text == "GPU failure, waiting for vendor"
    assert node.features[:3] == ("Intel", "Xeon", "Gold6338")


def test_parse_nodes_without_gpu_tres():
    """AccountingStorageTRES without gres/gpu: no GPU in CfgTRES/AllocTRES, Gres and GresUsed still tell."""
    line = NODE_LINE.replace(",gres/gpu=4,gres/gpu:a40=4", "").replace(",gres/gpu=2,gres/gpu:a40=2", "")
    node = parse_nodes(line)[0]
    assert (node.gpus_alloc, node.gpus_total, node.gpu_gres_type) == (2, 4, "a40")
    idle = parse_nodes(line.replace("GresUsed=gpu:a40:2(IDX:0-1)", "GresUsed=gpu:a40:0(IDX:N/A)"))[0]
    assert idle.gpus_alloc == 0


def test_parse_reason_variants():
    assert parse_reason("Not responding [slurm@2026-01-01T00:00:00]").user == "slurm"
    assert parse_reason("just text").text == "just text"
    assert parse_reason("(null)") is None


def test_parse_demo_nodes(demo_dir):
    nodes = parse_nodes(read(demo_dir, "nodes"))
    assert len(nodes) == 301
    assert {node.state.compact for node in nodes} >= {"idle~", "mix", "idle", "drain"}


def _job_row(**overrides):
    values = {
        "JobArrayID": "4093339_[12-64%5]",
        "JobID": "4093339",
        "ArrayJobID": "4093339",
        "ArrayTaskID": "12-64%5",
        "Partition": "gpu",
        "Name": "train",
        "UserName": "alice",
        "Account": "mllab",
        "QOS": "normal",
        "State": "PENDING",
        "Reason": "Priority",
        "TimeUsed": "0:00",
        "TimeLimit": "1-00:00:00",
        "SubmitTime": "2026-10-19T10:00:00",
        "StartTime": "N/A",
        "NumNodes": "1",
        "NumCPUs": "8",
        "NumTasks": "1",
        "MinMemory": "4000M",
        "tres-alloc": "N/A",
        "tres-per-job": "N/A",
        "tres-per-node": "gres/gpu:a40:2",
        "tres-per-task": "N/A",
        "PriorityLong": "31623",
        "NodeList": "",
        "SchedNodes": "(null)",
        "Dependency": "(null)",
        "WorkDir": "/home/x",
        "StdOut": "/home/x/out",
        "StdErr": "/home/x/out",
        "Command": "/home/x/run.sh",
    }
    values.update(overrides)
    return "".join(f"{values[name]}{DELIMITER}" for name, _ in SQUEUE_FIELDS)


def test_parse_jobs_pending_array_and_running():
    text = "\n".join(
        [
            _job_row(),
            _job_row(
                JobArrayID="4093340",
                JobID="4093340",
                ArrayJobID="N/A",
                ArrayTaskID="N/A",
                State="RUNNING",
                TimeUsed="3:12:05",
                NodeList="gpu[012-013]",
                NumNodes="2",
                **{"tres-alloc": "cpu=16,mem=8000M,node=2,billing=16,gres/gpu=4,gres/gpu:a40=4"},
            ),
        ]
    )
    pending, running = parse_jobs(text)
    assert pending.task_count == 53
    assert pending.gpus == 2
    assert pending.memory == 4000 * 2**20
    assert pending.command_id == "4093339"
    assert pending.is_pending and not pending.is_running
    assert running.gpus == 4
    assert running.node_list == ("gpu012", "gpu013")
    assert running.time_left == timedelta(hours=20, minutes=47, seconds=55)
    assert running.command_id == "4093340"


def test_parse_jobs_per_cpu_memory():
    job = parse_jobs(_job_row(MinMemory="3000Mc", NumCPUs="4"))[0]
    assert job.mem_requested == 12000 * 2**20


def test_parse_jobs_gpus_per_task_and_running_fallback():
    per_task = parse_jobs(_job_row(**{"tres-per-node": "N/A", "tres-per-task": "gres/gpu:1"}, NumTasks="4"))[0]
    assert per_task.gpus_requested == 4 and per_task.gpus == 4
    # running job on a cluster whose AllocTRES has no gres/gpu: the request is the best estimate
    running = parse_jobs(_job_row(State="RUNNING", **{"tres-alloc": "cpu=8,mem=4000M,node=1"}))[0]
    assert running.tres_alloc.gpu == 0 and running.gpus == 2


def test_parse_jobs_name_with_pipe_and_spaces():
    job = parse_jobs(_job_row(Name="eval|run 2", WorkDir="/data/a|b"))[0]
    assert (job.name, job.user, job.state, job.work_dir) == ("eval|run 2", "alice", "PENDING", "/data/a|b")


def test_parse_demo_jobs(demo_dir):
    jobs = parse_jobs(read(demo_dir, "jobs"))
    assert len(jobs) == 422
    assert any(job.task_count > 1 for job in jobs)


def test_parse_shares():
    entries = parse_shares(
        "root|||1.000000|12345|1.000000|||\n mllab||1|0.500000|100|0.300000||1.5\n"
        "  mllab|alice|1|0.010000|50|0.100000|0.75|\n other||parent|0.1|0|0.0||inf\n"
    )
    assert [e.account for e in entries] == ["mllab", "mllab", "other"]
    assert entries[0].is_account and entries[0].level_fs == 1.5
    assert entries[1].user == "alice" and entries[1].fairshare == 0.75
    assert entries[2].raw_shares is None and entries[2].level_fs == float("inf")


HISTORY = (
    "4093300|4093300|train|gpu|mllab|alice|COMPLETED|0:0|01:00:00|02:00:00|8|cpu=8,mem=16000M,node=1,billing=8,gres/gpu=2|"
    "16000M||04:00:00|2026-10-18T10:00:00|2026-10-18T10:05:00|2026-10-18T11:05:00|gpu012|/home/x/slurm-%j.out|/home/x\n"
    "4093300.batch|4093300.batch|batch|gpu|mllab||COMPLETED|0:0|01:00:00||8|cpu=8,mem=16000M,node=1|||03:50:00|"
    "2026-10-18T10:05:00|2026-10-18T10:05:00|2026-10-18T11:05:00|gpu012||\n"
    "4093300.0|4093300.0|python|gpu|mllab||COMPLETED|0:0|00:59:00||8|cpu=8||MAXRSS|03:50:00|2026-10-18T10:05:00|"
    "2026-10-18T10:05:00|2026-10-18T11:05:00|gpu012||\n"
    "4093301|4093301|x|small|mllab|alice|CANCELLED by 1234|0:0|00:00:00|01:00:00|1|cpu=1,mem=3000M,node=1|3000M||"
    "00:00:00|2026-10-18T10:00:00|Unknown|Unknown|None assigned|/home/x/slurm-%j.out|/home/x\n"
).replace("|", DELIMITER)


@pytest.mark.parametrize(
    ("max_rss", "unit"),
    [
        ("8192000000", "auto"),  # sacct --noconvert on current Slurm: bare bytes
        ("8000000K", "auto"),  # older Slurm: kilobytes with suffix
        ("8000000", "K"),  # site override for bare numbers
        ("8000000K", "B"),  # a suffix always wins over the configured unit
    ],
)
def test_parse_history_aggregates_steps(max_rss, unit):
    done, cancelled = parse_history(HISTORY.replace("MAXRSS", max_rss), max_rss_unit=unit)
    assert done.max_rss == 8000000 * 2**10
    assert done.req_mem == 16000 * 2**20
    assert round(done.mem_eff, 4) == 0.4883
    assert done.cpu_eff == 0.5
    assert done.gpus == 2
    assert cancelled.state == "CANCELLED"
    assert cancelled.node_list == () and cancelled.start is None
    assert expand_output_pattern(done.stdout, done) == "/home/x/slurm-4093300.out"


def test_parse_recent_and_usage():
    counts = parse_recent_counts(
        "alice|2026-10-19T10:00:00\nalice|Unknown\nbob|2020-01-01T00:00:00\n".replace("|", DELIMITER)
    )
    assert counts["alice"].jobs_7d == 2 and counts["alice"].jobs_24h >= 1
    assert counts["bob"].jobs_24h == 0
    usage = parse_usage(
        "acct|gpu|cpu=8,gres/gpu=2|gpu012|2026-10-18T10:00:00|2026-10-18T11:00:00\n".replace("|", DELIMITER)
    )
    assert usage[0].tres_alloc.gpu == 2 and usage[0].node_list == ("gpu012",)


def test_parse_partitions_reservations_sdiag(demo_dir):
    partitions = parse_partitions(read(demo_dir, "partitions"))
    assert {p.name for p in partitions} >= {"small", "big", "gpu", "gcp1-cmp"}
    small = next(p for p in partitions if p.name == "small")
    assert small.is_default and small.max_time == timedelta(days=2, hours=2) and len(small.nodes) > 100
    reservations = parse_reservations(read(demo_dir, "reservations"))
    assert len(reservations) == 2 and reservations[0].is_active and len(reservations[0].nodes) == 6
    stats = parse_sdiag(read(demo_dir, "scheduler"))
    assert stats.backfill_total_jobs == 9123 and stats.mean_cycle_us == 53112 and stats.data_since is not None
    assert stats.backfill_depth_mean == 598
