"""Due FSRS review cards."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from axiomatic_teaching.models import DueReview, Rating
from axiomatic_teaching.tui import format_dt
from axiomatic_teaching.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from axiomatic_teaching.app import AxiomaticApp

_FALLBACK_DAYS = {
    Rating.AGAIN.value: 0.0,
    Rating.HARD.value: 1.0,
    Rating.GOOD.value: 3.0,
    Rating.EASY.value: 7.0,
}


class ReviewScreen(Screen[None]):
    app: AxiomaticApp

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("1,a", "rate('again')", "Again"),
        Binding("2,h", "rate('hard')", "Hard"),
        Binding("3,g", "rate('good')", "Good"),
        Binding("4,e", "rate('easy')", "Easy"),
        Binding("question_mark", "app.help", "Help"),
    ]

    def __init__(self, start_lesson_id: str | None = None) -> None:
        super().__init__()
        self._start_id = start_lesson_id
        self._queue: list[DueReview] = []
        self._fsrs_mod: Any | None = None
        self._fsrs_tried = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="review-card", classes="panel"):
            yield Static("Review", classes="panel-title", id="review-heading")
            yield Static("[dim]Loading…[/]", id="review-body")
            with Horizontal(id="review-buttons"):
                yield Button("Again", id="rate-again", variant="error")
                yield Button("Hard", id="rate-hard")
                yield Button("Good", id="rate-good", variant="primary")
                yield Button("Easy", id="rate-easy", variant="success")
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Review"
        self._load_queue()
        self.query_one(StatusBar).refresh_status()

    def _load_queue(self) -> None:
        due = self.app.list_due()
        if self._start_id:
            due.sort(key=lambda item: item.lesson_id != self._start_id)
        self._queue = due
        self._refresh_card()

    def _current(self) -> DueReview | None:
        return self._queue[0] if self._queue else None

    def _refresh_card(self) -> None:
        heading = self.query_one("#review-heading", Static)
        body = self.query_one("#review-body", Static)
        buttons = self.query_one("#review-buttons")
        current = self._current()
        remaining = len(self._queue)
        if current is None:
            heading.update("Review")
            body.update("[green]Nothing due. You're clear.[/]")
            buttons.display = False
            return
        buttons.display = True
        heading.update(f"Review  [dim]{remaining} due[/]")
        scheduler = "FSRS" if self._scheduler() is not None else "display only"
        body.update(
            f"[bold]{current.title}[/]\n"
            f"[dim]{current.topic}[/]\n"
            f"due {format_dt(current.due)}\n\n"
            f"[dim]Rate this card · scheduler: {scheduler}[/]"
        )

    def _scheduler(self) -> Any | None:
        if self._fsrs_tried:
            return self._fsrs_mod
        self._fsrs_tried = True
        try:
            from axiomatic_teaching.schedule import fsrs as fsrs_mod
        except ImportError:
            try:
                import axiomatic_teaching.schedule.fsrs as fsrs_mod
            except ImportError:
                self._fsrs_mod = None
                return None
        self._fsrs_mod = fsrs_mod
        return fsrs_mod

    def action_rate(self, rating: str) -> None:
        self._rate(rating)

    @on(Button.Pressed, "#rate-again")
    def _again(self) -> None:
        self._rate(Rating.AGAIN.value)

    @on(Button.Pressed, "#rate-hard")
    def _hard(self) -> None:
        self._rate(Rating.HARD.value)

    @on(Button.Pressed, "#rate-good")
    def _good(self) -> None:
        self._rate(Rating.GOOD.value)

    @on(Button.Pressed, "#rate-easy")
    def _easy(self) -> None:
        self._rate(Rating.EASY.value)

    def _rate(self, rating: str) -> None:
        current = self._current()
        if current is None:
            return
        fsrs_mod = self._scheduler()
        if fsrs_mod is None:
            self.notify("Scheduler not available; showing due list only.")
            self._queue.pop(0)
            self.app.refresh_counts()
            self.query_one(StatusBar).refresh_status()
            self._refresh_card()
            return
        apply_review = getattr(fsrs_mod, "apply_review", None)
        scheduled_days = _FALLBACK_DAYS.get(rating, 1.0)
        try:
            if callable(apply_review):
                updated = apply_review(self.app.repository, current.lesson_id, rating)
                scheduled_days = float(getattr(updated, "scheduled_days", scheduled_days) or scheduled_days)
            else:
                self.app.repository.add_review(current.lesson_id, rating, scheduled_days)
        except Exception as exc:
            self.notify(f"Could not record review: {exc}", severity="error")
            return
        self.notify(f"{rating} · next in {scheduled_days:g} day(s)")
        self._queue.pop(0)
        self.app.refresh_counts()
        self.query_one(StatusBar).refresh_status()
        self._refresh_card()
