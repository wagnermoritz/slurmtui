"""Pattern strings used throughout the configuration.

A pattern is a shell-style glob (full match, case-sensitive) unless it starts
with ``re:``, in which case the remainder is a Python regular expression that
is searched in the value.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from functools import lru_cache

REGEX_PREFIX = "re:"


class PatternError(ValueError):
    """Raised for a syntactically invalid pattern."""


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a pattern string to a regex. Globs become anchored regexes."""
    if pattern.startswith(REGEX_PREFIX):
        try:
            return re.compile(pattern[len(REGEX_PREFIX) :])
        except re.error as exc:
            raise PatternError(f"invalid regular expression {pattern!r}: {exc}") from exc
    return re.compile(fnmatch.translate(pattern))


def validate_pattern(pattern: str) -> str:
    """Return the pattern unchanged or raise PatternError."""
    compile_pattern(pattern)
    return pattern


def is_regex(pattern: str) -> bool:
    return pattern.startswith(REGEX_PREFIX)


def pattern_match(pattern: str, value: str) -> re.Match[str] | None:
    """Match a single pattern against a value. Regexes are searched, globs fully matched."""
    compiled = compile_pattern(pattern)
    if is_regex(pattern):
        return compiled.search(value)
    return compiled.fullmatch(value)


def matches(pattern: str, value: str) -> bool:
    return pattern_match(pattern, value) is not None


def any_matches(patterns: Iterable[str], value: str) -> bool:
    return any(matches(pattern, value) for pattern in patterns)


def any_value_matches(patterns: Iterable[str], values: Iterable[str]) -> bool:
    values = list(values)
    return any(matches(pattern, value) for pattern in patterns for value in values)
