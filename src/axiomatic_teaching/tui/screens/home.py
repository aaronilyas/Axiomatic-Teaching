"""Home: lessons by status, due reviews, recent banked, hints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from axiomatic_teaching.models import BankedLessonSummary, DueReview, Lesson, LessonStatus
from axiomatic_teaching.tui import format_dt
from axiomatic_teaching.tui.screens.knowledge import KnowledgeScreen
from axiomatic_teaching.tui.screens.lesson_wizard import LessonWizard
from axiomatic_teaching.tui.screens.review import ReviewScreen
from axiomatic_teaching.tui.screens.study import StudyScreen
from axiomatic_teaching.tui.widgets.lesson_list import LessonList
from axiomatic_teaching.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from axiomatic_teaching.app import AxiomaticApp


_HINTS = (
    "[bold]n[/] new  [bold]enter[/]/[bold]s[/] study  [bold]k[/] knowledge  "
    "[bold]r[/] review  [bold]q[/] quit  [bold]?[/] help"
)


class HomeScreen(Screen[None]):
    app: AxiomaticApp

    BINDINGS = [
        Binding("n", "new_lesson", "New"),
        Binding("s", "study", "Study"),
        Binding("k", "knowledge", "Knowledge"),
        Binding("r", "review", "Review"),
        Binding("q", "app.quit", "Quit"),
        Binding("question_mark", "app.help", "Help"),
    ]

    AUTO_FOCUS = "#home-lessons"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="home-body"):
            with Vertical(id="home-main", classes="panel"):
                yield Static("Lessons", classes="panel-title")
                yield LessonList(id="home-lessons")
            with Vertical(id="home-side"):
                with Vertical(id="home-due", classes="panel"):
                    yield Static("Due reviews", classes="panel-title")
                    yield OptionList(id="due-list", compact=True)
                with Vertical(id="home-banked", classes="panel"):
                    yield Static("Recently banked", classes="panel-title")
                    yield OptionList(id="banked-list", compact=True)
                yield Static(_HINTS, id="home-hints", classes="muted")
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Home"
        self.refresh_data()

    def on_screen_resume(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        app = self.app
        app.refresh_counts()
        lessons = app.list_lessons()
        self.query_one("#home-lessons", LessonList).set_lessons(lessons, group=True)
        due = app.list_due()
        banked = app.list_banked()
        self._fill_due(due)
        self._fill_banked(banked)
        try:
            self.query_one(StatusBar).refresh_status()
        except Exception:
            pass

    def _fill_due(self, due: list[DueReview]) -> None:
        widget = self.query_one("#due-list", OptionList)
        if not due:
            widget.set_options(
                [Option("[dim]Nothing due.[/]", id="__due_empty__", disabled=True)]
            )
            return
        widget.set_options(
            [
                Option(
                    f"{item.title}  [dim]{format_dt(item.due)}[/]",
                    id=item.lesson_id,
                )
                for item in due
            ]
        )

    def _fill_banked(self, banked: list[BankedLessonSummary]) -> None:
        widget = self.query_one("#banked-list", OptionList)
        if not banked:
            widget.set_options(
                [Option("[dim]Nothing banked yet.[/]", id="__bank_empty__", disabled=True)]
            )
            return
        widget.set_options(
            [
                Option(
                    f"{item.title}  [dim]{format_dt(item.completed_at)}[/]",
                    id=item.id,
                )
                for item in banked[:12]
            ]
        )

    def action_new_lesson(self) -> None:
        def _after(lesson: Lesson | None) -> None:
            self.refresh_data()
            if lesson is not None:
                self.notify(f"Created “{lesson.title}”.")

        self.app.push_screen(LessonWizard(), _after)

    def action_study(self) -> None:
        lesson = self.query_one("#home-lessons", LessonList).selected_lesson()
        self._open_study(lesson)

    def action_knowledge(self) -> None:
        self.app.push_screen(KnowledgeScreen())

    def action_review(self) -> None:
        self.app.push_screen(ReviewScreen())

    @on(LessonList.LessonChosen, "#home-lessons")
    def _lesson_chosen(self, event: LessonList.LessonChosen) -> None:
        self._open_study(event.lesson)

    @on(OptionList.OptionSelected, "#due-list")
    def _due_chosen(self, event: OptionList.OptionSelected) -> None:
        lesson_id = event.option_id
        if not lesson_id or lesson_id.startswith("__"):
            return
        self.app.push_screen(ReviewScreen(start_lesson_id=lesson_id))

    @on(OptionList.OptionSelected, "#banked-list")
    def _banked_chosen(self, event: OptionList.OptionSelected) -> None:
        lesson_id = event.option_id
        if not lesson_id or lesson_id.startswith("__"):
            return
        self.app.push_screen(KnowledgeScreen(lesson_id=lesson_id))

    def _open_study(self, lesson: Lesson | None) -> None:
        if lesson is None:
            self.notify("Select a lesson first.")
            return
        if lesson.status == LessonStatus.DRAFT:
            self.notify("Drafts cannot be studied. Finish creating the lesson.", severity="warning")
            return
        if lesson.status == LessonStatus.ARCHIVED:
            self.notify("Archived lessons cannot be studied.", severity="warning")
            return
        self.app.push_screen(StudyScreen(lesson))
