import time

from slurmtui.slurm.commands import DELIMITER, SQUEUE_FIELDS
from slurmtui.slurm.parsers.jobs import parse_jobs
from slurmtui.slurm.parsers.nodes import parse_nodes
from tests.conftest import read


def test_parse_many_jobs_is_fast(demo_dir):
    base = read(demo_dir, "jobs").splitlines()
    rows = []
    for index in range(10000):
        cells = base[index % len(base)].split(DELIMITER)
        cells[1] = str(5000000 + index)
        cells[0] = cells[1]
        rows.append(DELIMITER.join(cells))
    text = "\n".join(rows)
    assert len(SQUEUE_FIELDS) == len(rows[0].split(DELIMITER)) - 1
    start = time.perf_counter()
    jobs = parse_jobs(text)
    elapsed = time.perf_counter() - start
    assert len(jobs) == 10000
    assert elapsed < 2.5, f"parsing 10k jobs took {elapsed:.2f}s"


def test_parse_many_nodes_is_fast(demo_dir):
    lines = read(demo_dir, "nodes").splitlines()
    text = "\n".join(line.replace("NodeName=", f"NodeName=r{index}-", 1) for index in range(7) for line in lines)
    start = time.perf_counter()
    nodes = parse_nodes(text)
    elapsed = time.perf_counter() - start
    assert len(nodes) == 7 * len(lines)
    assert elapsed < 2.5, f"parsing {len(nodes)} nodes took {elapsed:.2f}s"
