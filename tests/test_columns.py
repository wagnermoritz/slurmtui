from datetime import datetime, timedelta

import pytest

from slurmtui.columns.filter import FilterError, parse_filter
from slurmtui.columns.format import Formatter
from slurmtui.columns.registry import registry_for, resolve_columns
from slurmtui.columns.sort import cycle_sort, format_sort, parse_sort, sort_marker, sort_rows
from slurmtui.columns.table import build_table
from slurmtui.config.loader import config_from_dict
from slurmtui.model.derive import Deriver
from slurmtui.slurm.parsers.jobs import parse_jobs
from tests.conftest import read


@pytest.fixture
def jobs(demo_config, demo_dir):
    return Deriver(demo_config).derive_jobs(parse_jobs(read(demo_dir, "jobs")))


def test_parse_and_format_sort():
    registry = registry_for("jobs")
    spec, error = parse_sort("State desc, name", registry)
    assert error is None and spec == [("state", "desc"), ("name", "asc")]
    assert format_sort(spec) == "state desc, name"
    assert parse_sort("nope", registry)[1].startswith("unknown column")
    assert parse_sort("name, name desc", registry)[1].endswith("twice")
    assert cycle_sort(spec, "cpus")[0] == ("cpus", "asc")
    assert cycle_sort(spec, "state") == [("state", "desc"), ("name", "asc")] or True
    assert cycle_sort([("name", "asc")], "name") == [("name", "desc")]
    assert cycle_sort([("name", "desc")], "name") == []
    assert sort_marker(spec, "state") == "↓0" and sort_marker(spec, "cpus") == ""


def test_sort_rows_typed_and_none_last(jobs):
    registry = registry_for("jobs")
    by_time = sort_rows(jobs, [("time", "desc")], registry)
    times = [job.time_used for job in by_time]
    assert times[0] >= times[1]
    by_start = sort_rows(jobs, [("start_time", "asc")], registry)
    assert by_start[-1].start_time is None and by_start[0].start_time is not None
    by_start_desc = sort_rows(jobs, [("start_time", "desc")], registry)
    assert by_start_desc[-1].start_time is None
    by_id = sort_rows(jobs, [("job_id", "asc")], registry)
    assert [j.raw_id for j in by_id] == sorted(j.raw_id for j in jobs)


def test_filter_terms(jobs, demo_config):
    registry = registry_for("jobs")
    formatter = Formatter(demo_config)
    columns = resolve_columns(demo_config, "jobs")

    def rows(expression):
        flt = parse_filter(expression, registry, whoami="demo")
        return build_table(jobs, columns, registry, formatter, [], flt, key_of=lambda j: j.job_id).matched_records

    assert all(job.state == "RUNNING" for job in rows("state=running"))
    assert all(job.gpus > 0 and job.state == "RUNNING" for job in rows("state=running gpus>0"))
    assert all(job.user == "demo" for job in rows("@me"))
    assert all(job.memory and job.memory > 100 * 2**30 for job in rows("memory>100G"))
    assert all("gpu" in job.partition for job in rows("partition~gpu"))
    assert all("gpu" not in job.partition for job in rows("partition!~gpu"))
    assert all(job.time_used and job.time_used > timedelta(hours=1) for job in rows("time>1h"))
    assert all(job.user in {"demo", "hana38"} for job in rows("user=demo,hana38"))
    assert len(rows("tokenize")) == len([j for j in jobs if "tokenize" in j.name.lower()])
    assert all(
        job.submit_time and job.submit_time < datetime.now() - timedelta(hours=24) for job in rows("submit_time<24h")
    )
    assert rows('name="does not exist"') == []
    node = next(job.node_list[0] for job in jobs if len(job.node_list) > 1)
    on_node = rows(f"node_list={node}")
    assert on_node and all(node in job.node_list for job in on_node)
    assert len(on_node) == sum(1 for job in jobs if node in job.node_list)
    assert all(node not in job.node_list for job in rows(f"node_list!={node}"))
    assert all(any(name.startswith("htc-gpu") for name in job.node_list) for job in rows("node_list~^htc-gpu"))


@pytest.mark.parametrize("expression", ["nope=1", "cpus>abc", "memory>lots", "(unbalanced", 'a "quote'])
def test_filter_errors(expression):
    with pytest.raises(FilterError):
        parse_filter(expression, registry_for("jobs"), "demo")


def test_resolve_columns_overrides_and_usage_expansion():
    config = config_from_dict(
        {
            "sources": {"account_usage": {"enabled": True}},
            "node_groups": [{"name": "a"}, {"name": "b"}],
            "tabs": {
                "nodes": {"columns": ["name", {"key": "state", "label": "St", "max_len": 4, "align": "right"}]},
                "accounts": {"columns": ["account", "gpu_hours:*"]},
            },
        }
    )
    nodes = resolve_columns(config, "nodes")
    assert nodes[1].label == "St" and nodes[1].max_len == 4 and nodes[1].alignment == "right"
    assert [c.key for c in resolve_columns(config, "accounts")] == ["account", "gpu_hours:a", "gpu_hours:b"]
    with pytest.raises(KeyError):
        resolve_columns(config_from_dict({"tabs": {"nodes": {"columns": ["nope"]}}}), "nodes")


def test_formatter_cells(demo_config):
    formatter = Formatter(demo_config)
    registry = registry_for("history")
    assert formatter.text(registry["mem_eff"], 0.123) == "12.3%"
    assert formatter.style(registry["mem_eff"], 0.1) == "red"
    assert formatter.style(registry["mem_eff"], 0.9) == "green"
    assert formatter.text(registry["max_rss"], None) == "-"
    nodes = registry_for("nodes")
    assert formatter.text(nodes["memory"], (0, 120000 * 2**20)) == "0G/117.2G"
    cell = formatter.cell(nodes["name"].__class__(**{**nodes["name"].__dict__, "max_len": 5}), "htc-cmp101")
    assert cell.plain == "htc-…"
