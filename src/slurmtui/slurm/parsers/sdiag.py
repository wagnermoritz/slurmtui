"""Parse the parts of ``sdiag`` output shown in the cluster overview."""

from __future__ import annotations

import contextlib
import re
from datetime import datetime

from slurmtui.model.records import SchedulerStats
from slurmtui.units import parse_timestamp


def _grab(pattern: str, text: str) -> int | None:
    match = re.search(pattern + r":\s*(\d+)", text)
    return int(match.group(1)) if match else None


def parse_sdiag(text: str) -> SchedulerStats:
    main, _, backfill = text.partition("Backfilling stats")
    since_match = re.search(r"Data since\s+(.*)", main)
    data_since = None
    if since_match:
        raw = re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", since_match.group(1)).strip())
        data_since = parse_timestamp(raw)
        if data_since is None:
            with contextlib.suppress(ValueError):
                data_since = datetime.strptime(raw, "%a %b %d %H:%M:%S %Y")
    return SchedulerStats(
        data_since=data_since,
        server_threads=_grab(r"Server thread count", main),
        jobs_submitted=_grab(r"Jobs submitted", main),
        jobs_started=_grab(r"Jobs started", main),
        jobs_completed=_grab(r"Jobs completed", main),
        jobs_canceled=_grab(r"Jobs canceled", main),
        jobs_failed=_grab(r"Jobs failed", main),
        jobs_pending=_grab(r"Jobs pending", main),
        jobs_running=_grab(r"Jobs running", main),
        queue_length=_grab(r"Last queue length", main),
        mean_cycle_us=_grab(r"Mean cycle", main),
        last_cycle_us=_grab(r"Last cycle", main),
        max_cycle_us=_grab(r"Max cycle", main),
        total_cycles=_grab(r"Total cycles", main),
        backfill_total_jobs=_grab(r"Total backfilled jobs \(since last slurm start\)", backfill),
        backfill_last_cycle_jobs=_grab(r"Total backfilled jobs \(since last stats cycle start\)", backfill),
        backfill_last_cycle_us=_grab(r"Last cycle", backfill),
        backfill_mean_cycle_us=_grab(r"Mean cycle", backfill),
        backfill_depth_mean=_grab(r"Depth Mean", backfill),
        backfill_queue_length=_grab(r"Last queue length", backfill),
    )
