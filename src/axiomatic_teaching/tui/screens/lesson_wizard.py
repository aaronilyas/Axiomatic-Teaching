"""New-lesson form. Title and topic required; success description optional."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea

from axiomatic_teaching.config import DEFAULT_SUCCESS_STATEMENT
from axiomatic_teaching.models import Lesson, LessonStatus, NewLessonSpec

if TYPE_CHECKING:
    from axiomatic_teaching.app import AxiomaticApp


class LessonWizard(Screen[Lesson | None]):
    app: AxiomaticApp

    BINDINGS = [
        Binding("escape", "cancel", "Esc · Cancel form"),
        Binding("ctrl+enter", "create", "Ctrl+Enter · Create lesson", priority=True),
        Binding("question_mark", "app.help", "? · Show help"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="wizard-card"):
            yield Static("New lesson", id="wizard-title", classes="panel-title")
            yield Static(
                "Title and topic are required. Success is optional — one or two sentences.",
                id="wizard-hint",
                classes="muted",
            )
            yield Label("Title")
            yield Input(placeholder="What is this lesson called?", id="field-title")
            yield Label("Topic")
            yield Input(placeholder="Subject or domain", id="field-topic")
            yield Label("What does success look like? (optional)")
            yield TextArea(id="field-success", show_line_numbers=False)
            yield Static(
                "Leave blank to use: "
                f"{DEFAULT_SUCCESS_STATEMENT} "
                "A single criterion is derived automatically (keywords and a minimum length).",
                classes="muted",
                id="success-help",
            )
            with Horizontal(id="wizard-nav"):
                yield Button("Create lesson", id="wizard-create", variant="success")
                yield Button("Cancel", id="wizard-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "New lesson"
        self.query_one("#field-title", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_create(self) -> None:
        self._commit_lesson()

    @on(Button.Pressed, "#wizard-cancel")
    def _cancel_clicked(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#wizard-create")
    def _create(self) -> None:
        self._commit_lesson()

    def _commit_lesson(self) -> None:
        title = self.query_one("#field-title", Input).value.strip()
        topic = self.query_one("#field-topic", Input).value.strip()
        success = self.query_one("#field-success", TextArea).text
        if not title:
            self.notify("Title is required.", severity="error")
            self.query_one("#field-title", Input).focus()
            return
        if not topic:
            self.notify("Topic is required.", severity="error")
            self.query_one("#field-topic", Input).focus()
            return
        try:
            spec = NewLessonSpec(
                title=title,
                topic=topic,
                success_description=success,
            )
        except ValidationError as exc:
            self.notify(str(exc), severity="error")
            return
        try:
            lesson = self.app.repository.create_lesson(spec)
        except Exception as exc:
            self.notify(f"Could not create lesson: {exc}", severity="error")
            return
        if lesson.status != LessonStatus.ACTIVE:
            lesson.status = LessonStatus.ACTIVE
            try:
                lesson = self.app.repository.save_lesson(lesson)
            except Exception:
                pass
        self.dismiss(lesson)
