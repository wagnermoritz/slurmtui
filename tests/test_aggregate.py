from datetime import datetime, timedelta

from slurmtui.data import aggregate
from slurmtui.model.derive import Deriver
from slurmtui.slurm.commands import DELIMITER
from slurmtui.slurm.parsers.jobs import parse_jobs
from slurmtui.slurm.parsers.nodes import parse_nodes
from slurmtui.slurm.parsers.partitions import parse_partitions
from slurmtui.slurm.parsers.reservations import parse_reservations
from slurmtui.slurm.parsers.sacct import parse_recent_counts, parse_usage
from slurmtui.slurm.parsers.shares import parse_shares
from tests.conftest import read


def test_users_and_accounts(demo_config, demo_dir):
    deriver = Deriver(demo_config)
    jobs = deriver.derive_jobs(parse_jobs(read(demo_dir, "jobs")))
    shares = parse_shares(read(demo_dir, "shares"))
    recent = parse_recent_counts(read(demo_dir, "recent_jobs"))
    users = aggregate.users(jobs, shares, recent)
    assert users and all(row.jobs_24h is not None for row in users)
    demo = next(row for row in users if row.user == "demo")
    assert demo.jobs_running + demo.jobs_pending > 0
    assert demo.usage is not None and demo.fairshare is not None
    running_cpus = sum(job.tres_alloc.cpu for job in jobs if job.is_running and job.user == "demo")
    assert demo.cpus == running_cpus
    assert demo.gpus == sum(job.gpus for job in jobs if job.is_running and job.user == "demo")
    assert demo.raw_usage is not None and demo.raw_usage >= 0
    without_recent = aggregate.users(jobs, shares)
    assert all(row.jobs_24h is None for row in without_recent)

    usage = aggregate.usage_hours(
        parse_usage(read(demo_dir, "account_usage")), deriver, datetime.now() - timedelta(days=7)
    )
    accounts = aggregate.accounts(shares, jobs, usage)
    assert len(accounts) == 12
    first = accounts[0]
    assert first.members >= first.members_active
    assert set(first.cpu_hours) <= {"z3", "GCP", "other"}
    pending = sum(row.jobs_pending for row in accounts)
    assert pending == sum(job.task_count for job in jobs if job.is_pending)


def test_usage_hours_clips_window():
    deriver = Deriver(__import__("slurmtui.config.loader", fromlist=["config_from_dict"]).config_from_dict({}))
    now = datetime(2026, 10, 19, 12, 0)
    start = now - timedelta(days=10)
    records = parse_usage(
        f"acct|p|cpu=4|n1|{(now - timedelta(days=10)).isoformat()}|{(now - timedelta(days=6)).isoformat()}\n".replace(
            "|", DELIMITER
        )
    )
    usage = aggregate.usage_hours(records, deriver, now - timedelta(days=7), now)
    assert round(usage["acct"][0]["cluster"]) == 4 * 24  # only one day inside the window
    assert start < now


def test_cluster_overview(demo_config, demo_dir):
    deriver = Deriver(demo_config)
    nodes = deriver.derive_nodes(parse_nodes(read(demo_dir, "nodes")), parse_partitions(read(demo_dir, "partitions")))
    jobs = deriver.derive_jobs(parse_jobs(read(demo_dir, "jobs")))
    reservations = parse_reservations(read(demo_dir, "reservations"))
    overview = aggregate.cluster_overview(
        nodes, jobs, reservations, demo_config.group_names, demo_config.ungrouped_name
    )
    assert set(overview) == {"z3", "GCP"}
    z3 = overview["z3"]
    assert z3.node_total == sum(1 for node in nodes if node.node_group == "z3")
    assert sum(bar.total for bar in z3.cpus) == sum(node.cpus_total for node in nodes if node.node_group == "z3")
    assert any(bar.label == "A40 48GB" for bar in z3.gpus)
    assert len(z3.reservations) == 2 and not overview["GCP"].reservations
    assert z3.running + overview["GCP"].running == sum(1 for job in jobs if job.is_running)


def test_job_helpers(demo_config, demo_dir):
    jobs = parse_jobs(read(demo_dir, "jobs"))
    node = next(job.node_list[0] for job in jobs if job.node_list)
    assert all(node in job.node_list for job in aggregate.jobs_on_node(jobs, node))
    running, _pending, other = aggregate.job_counts(jobs)
    assert running + other == sum(1 for job in jobs if not job.is_pending)
    counts = aggregate.running_jobs_per_node(jobs)
    assert counts[node] == sum(1 for job in aggregate.jobs_on_node(jobs, node) if job.is_running)
    nodes = parse_nodes(read(demo_dir, "nodes"))
    with_counts = aggregate.with_job_counts(nodes, jobs)
    assert sum(item.jobs_running for item in with_counts) == sum(len(job.node_list) for job in jobs if job.is_running)
    assert next(item for item in with_counts if item.name == node).jobs_running == counts[node]
