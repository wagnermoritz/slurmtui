"""A generic detail screen: titled sections loaded asynchronously, optional actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from rich.console import RenderableType
from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static
from textual.widgets.button import ButtonVariant

from slurmtui.ui.screens.confirm import ConfirmScreen


@dataclass
class Section:
    title: str
    body: RenderableType | str
    plain: bool = True  # body is plain text that must be escaped


@dataclass
class Action:
    id: str
    label: str
    confirm: str | None = None
    variant: ButtonVariant = "primary"


@dataclass
class ActionOutcome:
    message: str
    ok: bool = True
    reload: bool = True
    close: bool = False


@dataclass
class DetailSpec:
    title: str
    loader: Callable[[], Awaitable[list[Section]]]
    actions: list[Action] = field(default_factory=list)
    on_action: Callable[[str], Awaitable[ActionOutcome]] | None = None


class DetailScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss_screen", "Close"),
        Binding("q", "dismiss_screen", "Close", show=False),
        Binding("r", "reload", "Reload"),
    ]

    def __init__(self, spec: DetailSpec) -> None:
        super().__init__()
        self.spec = spec

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-box"):
            yield Static(Text(self.spec.title, style="bold"), classes="modal-title")
            with Horizontal(classes="modal-actions"):
                for action in self.spec.actions:
                    yield Button(action.label, id=f"action-{action.id}", variant=action.variant)
                yield Button("Close", id="action-close")
            yield Static("", id="detail-message", classes="message")
            yield VerticalScroll(Static("Loading…", classes="modal-hint"), id="detail-body", classes="modal-body")

    def on_mount(self) -> None:
        self.load()

    @work(exclusive=True, group="detail-load")
    async def load(self) -> None:
        try:
            sections = await self.spec.loader()
        except Exception as exc:  # the loader talks to the backend; show, don't crash
            sections = [Section("Error", str(exc))]
        body = self.query_one("#detail-body", VerticalScroll)
        await body.remove_children()
        widgets: list[Static] = []
        for item in sections:
            widgets.append(Static(Text(item.title), classes="section-title"))
            content: RenderableType = item.body
            if isinstance(item.body, str):
                content = Text(item.body) if item.plain else Text.from_markup(item.body)
            widgets.append(Static(content, classes="section-body"))
        await body.mount_all(widgets)

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    def action_reload(self) -> None:
        self.load()

    @on(Button.Pressed)
    async def _button(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "action-close":
            self.dismiss(None)
            return
        action_id = button_id.removeprefix("action-")
        action = next((item for item in self.spec.actions if item.id == action_id), None)
        if action is None or self.spec.on_action is None:
            return
        if action.confirm:
            confirmed = await self.app.push_screen_wait(ConfirmScreen(action.confirm))
            if not confirmed:
                return
        self.perform_action(action_id)

    @work(exclusive=True, group="detail-action")
    async def perform_action(self, action_id: str) -> None:
        assert self.spec.on_action is not None
        message = self.query_one("#detail-message", Static)
        message.update(Text("Running…"))
        outcome = await self.spec.on_action(action_id)
        message.set_class(not outcome.ok, "error")
        message.set_class(outcome.ok, "success")
        message.update(Text.from_markup(escape(outcome.message)))
        if outcome.close:
            self.dismiss(None)
        elif outcome.reload:
            self.load()
