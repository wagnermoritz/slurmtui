from dataclasses import replace

from slurmtui.model.output import NO_ARRAY_TASK, expand_output_pattern, stdout_from_detail
from slurmtui.slurm.commands import DELIMITER
from slurmtui.slurm.parsers.jobs import parse_jobs
from slurmtui.slurm.parsers.sacct import parse_history
from tests.conftest import read


def test_expand_patterns_for_squeue_array_task(demo_dir):
    jobs = {job.job_id: job for job in parse_jobs(read(demo_dir, "jobs"))}
    task = jobs["4093014_10"]
    assert expand_output_pattern("/scratch/u/output/%A_%a", task) == "/scratch/u/output/4093014_10"
    assert expand_output_pattern("%x-%u-%j.out", task) == f"{task.name}-{task.user}-{task.raw_id}.out"
    assert expand_output_pattern("%N/%%/%n%t", task) == f"{task.node_list[0]}/%/00"


def test_expand_patterns_for_plain_job(demo_dir):
    job = next(job for job in parse_jobs(read(demo_dir, "jobs")) if job.array_job_id is None)
    assert expand_output_pattern("slurm-%A_%a.out", job) == f"slurm-{job.raw_id}_{NO_ARRAY_TASK}.out"
    assert expand_output_pattern("slurm-%j.out", job) == f"slurm-{job.raw_id}.out"


def test_expand_patterns_for_sacct_record():
    text = (
        "4093300_7|4093311|train|gpu|acc|me|COMPLETED|0:0|01:00:00|02:00:00|8|cpu=8,mem=16000M,node=1|16000M||"
        "04:00:00|2026-10-18T10:00:00|2026-10-18T10:05:00|2026-10-18T11:05:00|gpu012|/out/%A_%a_%j|/home\n"
    ).replace("|", DELIMITER)
    record = parse_history(text)[0]
    assert expand_output_pattern(record.stdout, record) == "/out/4093300_7_4093311"
    plain = replace(record, job_id="4093311", raw_id="4093311")
    assert expand_output_pattern("/out/%A_%a", plain) == f"/out/4093311_{NO_ARRAY_TASK}"


def test_stdout_from_scontrol_detail():
    detail = (
        "JobId=4093311 ArrayJobId=4093300 ArrayTaskId=7 JobName=train\n   StdOut=/out/4093300_7\n   StdErr=/out/e\n"
    )
    assert stdout_from_detail(detail) == "/out/4093300_7"
    assert stdout_from_detail("JobId=1\n   StdOut=/out/%A_%a\n") is None
    assert stdout_from_detail("JobId=1\n   Command=x\n") is None
