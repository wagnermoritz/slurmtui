"""Reading the tail of job output files safely."""

from __future__ import annotations

import re
from pathlib import Path

from slurmtui.config.schema import DetailConfig

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def tail_file(path: str, detail: DetailConfig) -> str:
    """Last lines of a file, bounded in bytes read, lines kept and line length.

    ANSI sequences are stripped and carriage-return progress bars collapsed to
    their final state. Permission and missing-file errors are reported as text.
    """
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - detail.stdout_tail_max_kb * 1024))
            raw = handle.read().decode("utf-8", errors="replace")
    except PermissionError:
        return f"No read permission for {path}"
    except (FileNotFoundError, NotADirectoryError):
        return f"{path} does not exist (yet)"
    except IsADirectoryError:
        return f"{path} is a directory"
    except OSError as exc:
        return f"Cannot read {path}: {exc.strerror or exc}"
    raw = _ANSI_RE.sub("", raw)
    lines = [line.rsplit("\r", 1)[-1] for line in raw.replace("\r\n", "\n").split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    lines = lines[-detail.stdout_tail_lines :]
    limit = detail.stdout_tail_line_len
    lines = [line if len(line) <= limit else line[:limit] + " …" for line in lines]
    if not lines:
        return f"{path} is empty"
    return "\n".join(lines)
