"""Hard confirmation before permanently hiding a lesson from the TUI."""

from __future__ import annotations

from rich.markup import escape
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static

from axiomatic_teaching.models import Lesson


_WARNING = (
    "This lesson will disappear from every list and will never appear again.\n\n"
    "Previously banked concepts, relations, and style notes from a successful "
    "completion of this lesson will be kept, so other lessons that already "
    "benefited still keep that graph knowledge.\n\n"
    "This action cannot be undone from the TUI."
)


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Require typing the lesson title before Delete permanently is enabled."""

    BINDINGS = [
        Binding("escape", "cancel", "Esc · Cancel deletion"),
        Binding("q", "cancel", "q · Cancel deletion", show=False),
        Binding("ctrl+enter", "confirm", "Ctrl+Enter · Delete permanently", show=False),
    ]

    def __init__(self, lesson: Lesson) -> None:
        super().__init__()
        self.lesson = lesson

    def compose(self) -> ComposeResult:
        title = escape(self.lesson.title)
        with Vertical(id="confirm-delete-card"):
            yield Static("Delete lesson permanently", classes="panel-title")
            yield Static(f"[bold]{title}[/]", id="confirm-delete-title")
            yield Static(_WARNING, id="confirm-delete-warning")
            yield Label("Type the lesson title exactly to enable deletion.")
            yield Input(
                placeholder=self.lesson.title,
                id="confirm-title",
            )
            yield Static(
                "[dim]Title does not match yet.[/]",
                id="confirm-delete-hint",
                classes="muted",
            )
            with Horizontal(id="confirm-delete-nav"):
                yield Button("Cancel", id="confirm-cancel", variant="primary")
                yield Button(
                    "Delete permanently",
                    id="confirm-delete",
                    variant="error",
                    disabled=True,
                )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#confirm-title", Input).focus()
        self._sync_delete_enabled()

    def _typed_title(self) -> str:
        return self.query_one("#confirm-title", Input).value.strip()

    def _title_matches(self) -> bool:
        return self._typed_title() == self.lesson.title.strip()

    def _sync_delete_enabled(self) -> None:
        matched = self._title_matches()
        self.query_one("#confirm-delete", Button).disabled = not matched
        hint = self.query_one("#confirm-delete-hint", Static)
        if matched:
            hint.update("[green]Title matches — Delete permanently is enabled.[/]")
        else:
            hint.update("[dim]Title does not match yet.[/]")

    @on(Input.Changed, "#confirm-title")
    def _title_changed(self) -> None:
        self._sync_delete_enabled()

    @on(Input.Submitted, "#confirm-title")
    def _title_submitted(self) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#confirm-cancel")
    def _cancel_clicked(self) -> None:
        self.action_cancel()

    @on(Button.Pressed, "#confirm-delete")
    def _delete_clicked(self) -> None:
        self.action_confirm()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self._sync_delete_enabled()
        if not self._title_matches():
            self.notify("Type the lesson title exactly to confirm.", severity="warning")
            self.query_one("#confirm-title", Input).focus()
            return
        self.dismiss(True)
