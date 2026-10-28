"""Filter expressions: free regex terms plus ``column<op>value`` terms, all ANDed.

gpu                     regex over the visible row text
user=alice,bob          equality (case-insensitive) on the column text
state~RUN|PEND          regex on the column text
node_list=gpu001        list columns match per element
partition!=small        negation (also !~)
mem>64G  time<2h        typed comparison (int, float, bytes, duration, datetime, percent)
@me                     user=<current user>
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from slurmtui.columns.registry import ColumnDef
from slurmtui.units import parse_duration, parse_memory, parse_timestamp, parse_window

_TERM_RE = re.compile(r"^(?P<key>[A-Za-z_][\w:]*?)(?P<op>!=|!~|>=|<=|=|~|>|<)(?P<value>.*)$", re.DOTALL)
_OPS = {"=", "!=", "~", "!~", ">", "<", ">=", "<="}
_TEXT_OPS = {"=", "!=", "~", "!~"}


class FilterError(ValueError):
    pass


@dataclass(frozen=True)
class Term:
    key: str | None  # None: free regex over the row text
    op: str
    raw: str
    regex: re.Pattern[str] | None = None
    values: tuple[str, ...] = ()
    number: Any = None  # parsed comparison operand

    def matches(self, row_text: str, column_text: str | None, raw_value: Any) -> bool:
        if self.key is None:
            assert self.regex is not None
            return self.regex.search(row_text) is not None
        if self.op in _TEXT_OPS and _is_name_list(raw_value):
            # list columns (node_list, partitions, ...) match per element, so
            # node_list=gpu001 finds a multi-node job whose text is gpu[001-004]
            return self._matches_any(tuple(str(item) for item in raw_value))
        text = (column_text or "").lower()
        if self.op == "=":
            return text in self.values
        if self.op == "!=":
            return text not in self.values
        if self.op == "~":
            assert self.regex is not None
            return self.regex.search(column_text or "") is not None
        if self.op == "!~":
            assert self.regex is not None
            return self.regex.search(column_text or "") is None
        if raw_value is None or self.number is None:
            return False
        comparable = _comparable(raw_value)
        if comparable is None:
            return False
        try:
            if self.op == ">":
                return bool(comparable > self.number)
            if self.op == "<":
                return bool(comparable < self.number)
            if self.op == ">=":
                return bool(comparable >= self.number)
            return bool(comparable <= self.number)
        except TypeError:
            return False

    def _matches_any(self, items: tuple[str, ...]) -> bool:
        if self.op == "=":
            return any(item.lower() in self.values for item in items)
        if self.op == "!=":
            return not any(item.lower() in self.values for item in items)
        assert self.regex is not None
        hit = any(self.regex.search(item) is not None for item in items)
        return hit if self.op == "~" else not hit


def _is_name_list(value: Any) -> bool:
    return isinstance(value, tuple | list) and all(isinstance(item, str) for item in value)


def _comparable(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, int) for v in value):
        return value[0]
    if isinstance(value, timedelta):
        return value.total_seconds() if value != timedelta.max else float("inf")
    if isinstance(value, datetime | int | float):
        return value
    if isinstance(value, str) and value.replace(".", "", 1).isdigit():
        return float(value)
    return None


def _parse_operand(column: ColumnDef, text: str) -> Any:
    text = text.strip()
    kind = column.type
    if kind in {"int", "float", "fraction", "jobid"}:
        try:
            return float(text)
        except ValueError as exc:
            raise FilterError(f"{column.key}: expected a number, got {text!r}") from exc
    if kind in {"bytes", "bytes_fraction"}:
        value = parse_memory(text, default_unit="G")
        if value is None:
            raise FilterError(f"{column.key}: expected a memory size like 64G, got {text!r}")
        return value
    if kind == "duration":
        duration = parse_duration(text)
        if duration is None:
            window = parse_window(text)
            if window is None:
                raise FilterError(f"{column.key}: expected a duration like 1-00:00:00 or 2h, got {text!r}")
            duration = window
        return duration.total_seconds() if duration != timedelta.max else float("inf")
    if kind == "datetime":
        when = parse_timestamp(text)
        if when is None:
            window = parse_window(text)
            if window is None:
                raise FilterError(f"{column.key}: expected a timestamp or an age like 2h, got {text!r}")
            when = datetime.now() - window
        return when
    if kind == "percent":
        stripped = text.rstrip("%")
        try:
            number = float(stripped)
        except ValueError as exc:
            raise FilterError(f"{column.key}: expected a percentage, got {text!r}") from exc
        return number / 100 if text.endswith("%") or number > 1 else number
    raise FilterError(f"{column.key}: comparison operators need a numeric, size, time or date column")


@dataclass(frozen=True)
class Filter:
    terms: tuple[Term, ...]
    text: str

    @property
    def is_empty(self) -> bool:
        return not self.terms

    @property
    def needed_keys(self) -> set[str]:
        return {term.key for term in self.terms if term.key is not None}

    def matches(self, row_text: str, column_text: Callable[[str], str | None], raw_value: Callable[[str], Any]) -> bool:
        for term in self.terms:
            if term.key is None:
                if not term.matches(row_text, None, None):
                    return False
            elif not term.matches(row_text, column_text(term.key), raw_value(term.key)):
                return False
        return True


EMPTY_FILTER = Filter(terms=(), text="")


def parse_filter(text: str, columns: dict[str, ColumnDef], whoami: str | None = None) -> Filter:
    """Parse a filter expression. Raises FilterError with a message for the user."""
    if not text.strip():
        return EMPTY_FILTER
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise FilterError(f"unbalanced quotes: {exc}") from exc
    lookup = {key.lower(): key for key in columns}
    terms: list[Term] = []
    for token in tokens:
        if token == "@me":
            if "user" not in columns:
                raise FilterError("@me needs a user column")
            if not whoami:
                raise FilterError("@me: current user unknown")
            terms.append(Term(key="user", op="=", raw=whoami, values=(whoami.lower(),)))
            continue
        match = _TERM_RE.match(token)
        key = lookup.get(match.group("key").lower()) if match else None
        if match and key is not None:
            op, value = match.group("op"), match.group("value")
            column = columns[key]
            if op in {"=", "!="}:
                values = tuple(part.strip().lower() for part in value.split(",") if part.strip())
                if not values:
                    raise FilterError(f"{key}{op}: missing value")
                terms.append(Term(key=key, op=op, raw=value, values=values))
            elif op in {"~", "!~"}:
                terms.append(Term(key=key, op=op, raw=value, regex=_compile(value)))
            else:
                terms.append(Term(key=key, op=op, raw=value, number=_parse_operand(column, value)))
            continue
        if match and match.group("op") in _OPS and match.group("key"):
            raise FilterError(f"unknown column '{match.group('key')}'")
        terms.append(Term(key=None, op="regex", raw=token, regex=_compile(token)))
    return Filter(terms=tuple(terms), text=text)


def _compile(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise FilterError(f"invalid regex {pattern!r}: {exc}") from exc
