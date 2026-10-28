from datetime import datetime, timedelta

import pytest

from slurmtui.units import (
    UNLIMITED,
    format_duration,
    format_memory,
    format_memory_pair,
    format_percent,
    parse_duration,
    parse_memory,
    parse_timestamp,
    parse_window,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("63000M", 63000 * 2**20),
        ("3875G", 3875 * 2**30),
        ("1.5T", int(1.5 * 2**40)),
        ("8000000K", 8000000 * 2**10),
        ("4000", 4000 * 2**20),
        ("3000Mc", 3000 * 2**20),
        ("0", 0),
        ("", None),
        ("(null)", None),
        ("n/a", None),
        ("garbage", None),
    ],
)
def test_parse_memory(text, expected):
    assert parse_memory(text) == expected


def test_parse_memory_default_unit():
    assert parse_memory("1024", default_unit="K") == 2**20


def test_format_memory():
    assert format_memory(512 * 2**30) == "512G"
    assert format_memory(1536 * 2**20) == "1.5G"
    assert format_memory(2**41) == "2T"
    assert format_memory(100 * 2**20) == "100M"
    assert format_memory(2**30, "M") == "1024M"
    assert format_memory(None) == "-"
    assert format_memory_pair(0, 120000 * 2**20) == "0G/117.2G"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1-02:03:04", timedelta(days=1, hours=2, minutes=3, seconds=4)),
        ("02:03:04", timedelta(hours=2, minutes=3, seconds=4)),
        ("03:04", timedelta(minutes=3, seconds=4)),
        ("0:00", timedelta(0)),
        ("2-02", timedelta(days=2, hours=2)),
        ("30", timedelta(minutes=30)),
        ("00:00.123", timedelta(seconds=0.123)),
        ("UNLIMITED", UNLIMITED),
        ("N/A", None),
        ("INVALID", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


def test_format_duration():
    assert format_duration(timedelta(days=1, hours=2, minutes=3, seconds=4)) == "1-02:03:04"
    assert format_duration(timedelta(hours=2)) == "02:00:00"
    assert format_duration(timedelta(days=2, hours=3), "compact") == "2d 3h"
    assert format_duration(UNLIMITED) == "unlimited"
    assert format_duration(None) == "-"


def test_parse_timestamp():
    assert parse_timestamp("2026-10-07T15:16:39") == datetime(2026, 10, 7, 15, 16, 39)
    assert parse_timestamp("Unknown") is None
    assert parse_timestamp("None") is None
    assert parse_timestamp("") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12h", timedelta(hours=12)),
        ("3d", timedelta(days=3)),
        ("2w", timedelta(weeks=2)),
        ("2 days", timedelta(days=2)),
        ("5", timedelta(days=5)),
        ("1.5h", timedelta(hours=1.5)),
        ("3 months", None),
        ("", None),
    ],
)
def test_parse_window(text, expected):
    assert parse_window(text) == expected


def test_format_percent():
    assert format_percent(0.4876) == "48.8%"
    assert format_percent(None) == "-"
