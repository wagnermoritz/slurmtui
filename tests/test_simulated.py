from datetime import datetime, timedelta
from pathlib import Path

import pytest
from textual.widgets import DataTable, TabbedContent

from slurmtui.app import create_app
from slurmtui.cli import main
from slurmtui.config.loader import load_config
from slurmtui.config.state import State
from slurmtui.data.sources import build_service
from slurmtui.model.derive import Deriver
from slurmtui.slurm.simulated_backend import SimulatedBackend, demo_config_path


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def sim() -> tuple[SimulatedBackend, Clock]:
    clock = Clock(datetime(2026, 10, 27, 12, 0))
    return SimulatedBackend(clock=clock), clock


async def test_simulation_is_consistent_and_moves_with_the_clock(sim):
    backend, clock = sim
    nodes = await backend.nodes()
    assert len(nodes) == 18 and {node.state.compact for node in nodes} >= {"down", "drain"}
    jobs = await backend.jobs()
    running = [job for job in jobs if job.is_running]
    pending = [job for job in jobs if job.is_pending]
    assert running and pending
    assert all(job.node_list and job.tres_alloc.cpu for job in running)
    assert {job.reason for job in pending} & {"Priority", "Resources"}
    for node in nodes:  # node allocations and running jobs agree
        on_node = [job for job in running if job.node_list == (node.name,)]
        assert node.cpus_alloc == sum(job.cpus for job in on_node)
        assert node.gpus_alloc == sum(job.gpus for job in on_node)
    gpu_jobs = [job for job in jobs if job.partition == "gpu"]
    assert gpu_jobs and all(job.gpus > 0 for job in gpu_jobs)
    by_name = {node.name: node for node in nodes}
    for job in gpu_jobs:  # a running job's GPU type is the type of the node it runs on
        if job.is_running:
            assert job.tres_alloc.gpu_type == by_name[job.node_list[0]].gpu_gres_type
    assert {node.gpu_gres_type for node in nodes if node.gpus_total} == {"a100", "h200"}

    history = await backend.job_history("demo", clock.now - timedelta(days=7))
    assert history and all(record.user == "demo" for record in history)
    assert any(record.max_rss and record.mem_eff for record in history)
    partitions = await backend.partitions()
    assert {partition.name for partition in partitions} == {"cpu", "long", "gpu"}
    assert len(await backend.reservations()) == 1
    assert {entry.account for entry in await backend.shares()} == {"physics", "biology", "mlgroup"}
    assert await backend.account_usage(clock.now) and await backend.recent_job_counts(clock.now)

    ids = {job.job_id for job in jobs}
    clock.now += timedelta(hours=1)
    later = await backend.jobs()
    assert {job.job_id for job in later} != ids  # jobs finished and new ones arrived
    assert len(await backend.job_history("demo", clock.now)) > len(history)
    stats = await backend.scheduler_stats()
    assert stats.jobs_running == sum(1 for job in later if job.is_running)
    assert stats.jobs_pending == sum(1 for job in later if job.is_pending)


async def test_simulation_actions_and_details(sim):
    backend, clock = sim
    jobs = await backend.jobs()
    pending = next(job for job in jobs if job.is_pending and job.array_job_id is None and not job.dependency)
    assert (await backend.hold(pending.command_id)).ok
    clock.now += timedelta(hours=2)
    held = next(job for job in await backend.jobs() if job.job_id == pending.job_id)
    assert held.is_pending and held.reason == "JobHeldUser"  # held jobs never start
    assert (await backend.release(pending.command_id)).ok
    running = next(job for job in await backend.jobs() if job.is_running)
    assert (await backend.cancel(running.command_id)).ok
    assert all(job.job_id != running.job_id for job in await backend.jobs())
    assert not (await backend.cancel("1")).ok
    assert f"JobName={pending.name}" in await backend.job_detail(pending.command_id)
    assert "NodeName=n01" in await backend.node_detail("n01")


def demo_config():
    return load_config(site_config=demo_config_path(), use_default_locations=False).config


async def test_demo_config_fits_the_simulated_cluster(sim):
    backend, _clock = sim
    config = demo_config()
    deriver = Deriver(config)
    nodes = deriver.derive_nodes(await backend.nodes(), await backend.partitions())
    assert {node.node_group for node in nodes} == {"demo"}
    assert {node.gpu_type for node in nodes if node.gpus_total} == {"A100 40GB", "H200 141GB"}
    assert {node.cpu_type for node in nodes} == {
        "Intel Gold6338",
        "AMD EPYC7543",
        "AMD EPYC9454",
        "Intel Platinum8568Y",
    }
    jobs = deriver.derive_jobs(await backend.jobs())
    assert {job.node_group for job in jobs} == {"demo"}
    assert config.sources.account_usage.enabled and config.sources.recent_jobs.enabled


def test_packaged_demo_config_matches_example():
    """The packaged copy is synced from examples/demo/site-config.toml by tools/gen_docs.py."""
    example_dir = Path(__file__).parent.parent / "examples" / "demo"
    assert demo_config_path().read_text() == (example_dir / "site-config.toml").read_text()
    loaded = load_config(
        site_config=example_dir / "site-config.toml",
        extra_files=[example_dir / "user-config.toml"],
        use_default_locations=False,
    )
    assert loaded.config.table_tab("jobs").filter == "@me"


def test_demo_flag_uses_its_own_config(capsys, monkeypatch, tmp_path):
    # an installed site/user configuration must not leak into the demo
    site = tmp_path / "site.toml"
    site.write_text('[[node_groups]]\nname = "installed"\nnodes = ["rack*"]\n')
    monkeypatch.setenv("SLURMTUI_SITE_CONFIG", str(site))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["--demo", "check-config"]) == 0
    out = capsys.readouterr().out
    assert str(demo_config_path()) in out and "installed" not in out and 'name = "demo"' in out


async def test_app_runs_on_the_simulation(tmp_state_path):
    config = demo_config()
    backend = SimulatedBackend()
    service = build_service(config, backend)
    app = create_app(config, backend, service, State(), state_path=tmp_state_path)
    async with app.run_test(size=(160, 40)) as pilot:
        for name in ("nodes", "jobs", "users", "accounts", "history", "cluster"):
            app.query_one("#tabs", TabbedContent).active = f"pane-{name}"
            await pilot.pause(0.5)
            if name != "cluster":
                assert app.tabs[name].query_one(DataTable).row_count > 0
        groups = app.tabs["cluster"].query_one("#cluster-groups", TabbedContent)
        assert {pane.id for pane in groups.query("TabPane")} == {"group-demo"}
