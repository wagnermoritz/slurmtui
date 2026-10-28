"""Type a sort specification for the current tab."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from slurmtui.columns.sort import SortSpec, format_sort, parse_sort


class SortDialog(ModalScreen[SortSpec | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self, current: SortSpec, valid_keys: Iterable[str], describe: Callable[[str], str] | None = None
    ) -> None:
        super().__init__()
        self.current = current
        self.valid_keys = list(valid_keys)
        self.describe = describe

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box small"):
            yield Static("Sort by (comma-separated columns, optional asc/desc, first = primary):", classes="modal-hint")
            yield Input(value=format_sort(self.current), placeholder="e.g. state desc, name", id="sort-input")
            yield Static("", id="sort-status", classes="modal-hint")
            yield Static("Columns: " + ", ".join(self.valid_keys), classes="modal-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._validate(format_sort(self.current))

    def _validate(self, text: str) -> SortSpec | None:
        spec, error = parse_sort(text, self.valid_keys)
        status = self.query_one("#sort-status", Static)
        if error:
            status.update(f"✗ {error}")
            return None
        status.update(f"✓ {format_sort(spec) or 'no sorting'}  (Enter applies)")
        return spec

    @on(Input.Changed)
    def _changed(self, event: Input.Changed) -> None:
        self._validate(event.value)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        spec = self._validate(event.value)
        if spec is not None:
            self.dismiss(spec)

    def action_cancel(self) -> None:
        self.dismiss(None)
