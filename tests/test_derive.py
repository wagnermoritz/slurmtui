from datetime import timedelta

from slurmtui.config.loader import config_from_dict
from slurmtui.model.derive import Deriver
from slurmtui.model.records import Partition
from slurmtui.slurm.parsers.common import parse_tres
from slurmtui.slurm.parsers.jobs import parse_jobs
from slurmtui.slurm.parsers.nodes import parse_nodes
from tests.conftest import read


def _partition(name, state="UP", max_time=timedelta(days=2)):
    return Partition(name, state, max_time, None, False, (), 0, 0, parse_tres(None))


def test_groups_and_labels(demo_config, demo_dir):
    deriver = Deriver(demo_config)
    nodes = deriver.derive_nodes(parse_nodes(read(demo_dir, "nodes")), [_partition("small"), _partition("gpu")])
    by_name = {node.name: node for node in nodes}
    assert by_name["htc-gpu012"].node_group == "z3"
    assert by_name["gpu800"].node_group == "GCP"
    assert by_name["htc-gpu012"].gpu_type == "A40 48GB"
    assert by_name["gpu800"].gpu_type == "H100 80GB"
    assert by_name["htc-gpu012"].cpu_type == "Intel Gold6338"
    assert by_name["cmp820"].cpu_type == "AMD EPYC9B45"
    assert by_name["htc-cmp520"].cpu_type == "virtual"
    assert by_name["cmp820"].gpu_type is None
    assert by_name["htc-gpu012"].max_time == timedelta(days=2)


def test_fallbacks_and_avail():
    config = config_from_dict({})
    deriver = Deriver(config)
    line = (
        "NodeName=n1 Arch=x86_64 CPUTot=16 CPUAlloc=0 RealMemory=1000 AllocMem=0 Sockets=1 CoresPerSocket=8 "
        "ThreadsPerCore=2 State=IDLE Partitions=p1,p2 Gres=gpu:v100:2 "
        "CfgTRES=cpu=16,mem=1000M,gres/gpu=2,gres/gpu:v100=2"
    )
    node = deriver.derive_nodes(parse_nodes(line), [_partition("p1"), _partition("p2", state="DOWN")])[0]
    assert node.node_group == "cluster"
    assert node.gpu_type == "v100"
    assert node.cpu_type == "x86_64 16c"
    assert node.avail == "down"


def test_job_groups_and_gpu_class(demo_config, demo_dir):
    deriver = Deriver(demo_config)
    jobs = deriver.derive_jobs(parse_jobs(read(demo_dir, "jobs")))
    running = [job for job in jobs if job.is_running]
    assert all(job.node_group in {"z3", "GCP"} for job in running)
    gcp_pending = next(job for job in jobs if job.is_pending and job.partition.startswith("gcp"))
    assert gcp_pending.node_group == "GCP"
    assert all(job.is_gpu_job == (job.gpus > 0) for job in jobs)


def test_partition_rule_for_gpu_hours():
    config = config_from_dict({"usage": {"gpu_hours_when": "partition", "gpu_partitions": ["*gpu*"]}})
    deriver = Deriver(config)
    assert deriver.is_gpu_job("gcp1-gpu", 0)
    assert not deriver.is_gpu_job("small", 4)
