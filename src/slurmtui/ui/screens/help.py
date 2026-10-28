"""Help screen: key bindings, filter and sort grammar, column keys of the current tab."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown

from slurmtui.columns.registry import ColumnDef
from slurmtui.config.schema import KeysConfig

FILTER_HELP = """
## Filter expressions

Terms are separated by spaces and all must match. Quote values with spaces.

| Term | Meaning |
| --- | --- |
| `word` | regular expression searched in the visible row text |
| `col=a,b` | column text equals a or b (case-insensitive) |
| `col~regex` | regular expression on the column text |
| `node_list=gpu001` | list columns (node lists, partitions) match per element |
| `col!=a`, `col!~re` | negations |
| `col>v`, `col<v`, `>=`, `<=` | typed comparison: numbers, memory (`64G`), durations (`2h`), dates, percentages |
| `@me` | shorthand for `user=<you>` |

Examples: `state=pending partition~gpu`, `@me time>1h`, `mem>100G gpus=0`, `mem_eff<50%`

## Sorting

Click a column header to cycle ascending → descending → off; the clicked
column becomes the primary key and the header shows `↑0`, `↓1`, …
The sort dialog takes the same thing as text: `state desc, name`.
"""


def _key_label(keys: list[str]) -> str:
    return ", ".join(key.replace("question_mark", "?").replace("slash", "/") for key in keys)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close"),
        Binding("q", "dismiss_screen", "Close", show=False),
    ]

    def __init__(self, keys: KeysConfig, tab_title: str, columns: dict[str, ColumnDef], version: str) -> None:
        super().__init__()
        self.keys = keys
        self.tab_title = tab_title
        self.columns = columns
        self.version = version

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"), VerticalScroll(classes="modal-body"):
            yield Markdown(self._markdown())

    def _markdown(self) -> str:
        bindings = [
            ("quit", "quit"),
            ("help", "this help"),
            ("refresh", "refresh the active tab"),
            ("refresh_all", "refresh every tab (expensive sources only when stale)"),
            ("toggle_auto_refresh", "toggle periodic refresh"),
            ("focus_filter", "focus the filter input"),
            ("clear_filter", "clear the filter"),
            ("next_tab", "next tab"),
            ("prev_tab", "previous tab"),
            ("my_jobs", "toggle `@me` in the JOBS filter"),
            ("settings", "settings"),
            ("sort_dialog", "sort dialog for the active tab"),
            ("close", "close a dialog / leave the filter input / restore the previous JOBS filter"),
            ("restore_filter", "JOBS: back to the filter replaced by a detail's *Show in JOBS*"),
        ]
        lines = [f"# slurmtui {self.version}", "", "## Keys", "", "| Key | Action |", "| --- | --- |"]
        for name, description in bindings:
            lines.append(f"| `{_key_label(getattr(self.keys, name))}` | {description} |")
        lines.append("| `Enter` | open the details of the selected row |")
        lines.append(FILTER_HELP)
        if self.columns:
            lines += [
                f"## Columns of {self.tab_title}",
                "",
                "| Key | Label | Type | Description |",
                "| --- | --- | --- | --- |",
            ]
            for key, column in sorted(self.columns.items()):
                lines.append(f"| `{key}` | {column.label} | {column.type} | {column.description} |")
        return "\n".join(lines)

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)
