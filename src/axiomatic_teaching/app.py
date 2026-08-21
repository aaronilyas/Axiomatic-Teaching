"""Textual application: Axiomatic Teaching."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding

from axiomatic_teaching.acp_client.events import AgentStatus, SessionController
from axiomatic_teaching.config import Settings
from axiomatic_teaching.db.repository import Repository
from axiomatic_teaching.models import (
    BankedLessonSummary,
    DueReview,
    GateResult,
    Lesson,
    LessonStatus,
)
from axiomatic_teaching.tui import ACPEvent, FALLBACK_RULES, invoke_flexible
from axiomatic_teaching.tui.screens.help import HelpScreen
from axiomatic_teaching.tui.screens.home import HomeScreen

_CSS_PATH = Path(__file__).parent / "tui" / "app.tcss"


class AxiomaticApp(App[None]):
    """Metacognitive study TUI. Completion is only via the MCP success gate."""

    TITLE = "Axiomatic Teaching"
    CSS_PATH = _CSS_PATH
    BINDINGS = [
        Binding("q", "quit", "q · Quit application"),
        Binding("ctrl+q", "quit", "Ctrl+Q · Quit application", show=False),
        Binding("question_mark", "help", "? · Show help"),
    ]

    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        session_factory: Callable[..., SessionController] | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.repository = repository
        self.session_factory = session_factory
        self.acp_connected = False
        self.acp_busy = False
        self.acp_message = "ACP not connected"
        self.banked_count = 0
        self.due_count = 0
        self.last_gate: GateResult | None = None

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.refresh_counts()
        self.push_screen(HomeScreen())

    def on_unmount(self) -> None:
        dispose = getattr(self.repository, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass

    def action_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            return
        self.push_screen(HelpScreen())

    def apply_agent_status(self, status: AgentStatus) -> None:
        self.acp_connected = status.connected
        self.acp_busy = status.busy
        if status.message:
            self.acp_message = status.message
        elif status.connected:
            self.acp_message = "connected"
        else:
            self.acp_message = "ACP not connected"

    def dispatch_acp_event(self, event: object) -> None:
        """ACP client entry point. Safe to call from a worker thread."""
        payload = event.payload if isinstance(event, ACPEvent) else event
        self.post_message(ACPEvent(payload))

    def on_acp_event(self, message: ACPEvent) -> None:
        payload = message.payload
        if isinstance(payload, AgentStatus):
            self.apply_agent_status(payload)
        if isinstance(payload, GateResult):
            self.last_gate = payload
            self.refresh_counts()
        handler = getattr(self.screen, "handle_acp_event", None)
        if callable(handler):
            handler(payload)

    def create_session(self, lesson_id: str | None = None) -> SessionController | None:
        factory = self.session_factory
        if factory is None:
            return None
        available: dict[str, Any] = {
            "app": self,
            "settings": self.settings,
            "repository": self.repository,
            "on_event": self.dispatch_acp_event,
            "post_message": self.post_message,
            "dispatch": self.dispatch_acp_event,
            "lesson_id": lesson_id,
        }
        try:
            session = invoke_flexible(factory, available)
        except TypeError:
            try:
                session = factory(self)
            except TypeError:
                try:
                    session = factory()
                except TypeError:
                    return None
        if session is None:
            return None
        return session

    def assemble_rules(self, lesson: Lesson) -> str:
        try:
            from axiomatic_teaching.context.assembler import assemble
        except ImportError:
            return FALLBACK_RULES
        try:
            result = assemble(
                self.repository,
                lesson,
                budget=self.settings.context_char_budget,
            )
        except TypeError:
            try:
                result = invoke_flexible(
                    assemble,
                    {
                        "repository": self.repository,
                        "repo": self.repository,
                        "lesson": lesson,
                        "lesson_id": lesson.id,
                        "settings": self.settings,
                    },
                )
            except Exception:
                return FALLBACK_RULES
        except Exception:
            return FALLBACK_RULES
        if isinstance(result, str) and result.strip():
            return result
        rules = getattr(result, "rules", None)
        if isinstance(rules, str) and rules.strip():
            return rules
        return FALLBACK_RULES

    def kickoff_prompt(self, lesson: Lesson) -> str:
        try:
            from axiomatic_teaching.context.assembler import kickoff_prompt as make_kickoff
        except ImportError:
            make_kickoff = None
        if make_kickoff is not None:
            try:
                text = make_kickoff(lesson)
                if isinstance(text, str) and text.strip():
                    return text
            except Exception:
                pass
        if lesson.status.value == "completed":
            return (
                f"This lesson titled {lesson.title} is already banked. Restudy only: "
                "do not call record_lesson_success. On this first tutor turn, (1) ask one "
                "diagnostic question at the edge of competence in this chat, and (2) you MUST "
                "call present_lesson_html in the same turn with self-contained exposition-only "
                "HTML (no questions, quizzes, or JavaScript). The learner already sees the "
                "success criterion — do not recap it. Do not lecture in this chat; wait for "
                "their answer before teaching here. Presenting HTML is not evidence. "
                "Do not use fs/write_text_file."
            )
        return (
            f"Begin the lesson titled {lesson.title}. "
            "On this first tutor turn, (1) ask one diagnostic question at the edge of "
            "competence in this chat, and (2) you MUST call present_lesson_html in the same "
            "turn with self-contained exposition-only HTML (no questions, quizzes, or "
            "JavaScript). The learner already sees the success criterion — do not recap it. "
            "Wait for their answer before teaching in this chat. Do not lecture. "
            "Do not declare the lesson complete yourself. Presenting HTML is not evidence. "
            "Do not use fs/write_text_file."
        )

    def list_lessons(self) -> list[Lesson]:
        try:
            return list(self.repository.list_lessons())
        except Exception:
            lessons: list[Lesson] = []
            for status in LessonStatus:
                if status == LessonStatus.DELETED:
                    continue
                try:
                    lessons.extend(self.repository.list_lessons_by_status(status.value))
                except Exception:
                    continue
            return lessons

    def list_due(self) -> list[DueReview]:
        try:
            return list(self.repository.list_due_reviews())
        except Exception:
            return []

    def list_banked(self) -> list[BankedLessonSummary]:
        try:
            return list(self.repository.list_banked_summaries())
        except Exception:
            completed = [
                lesson
                for lesson in self.list_lessons()
                if lesson.status == LessonStatus.COMPLETED
            ]
            return [
                BankedLessonSummary(
                    id=lesson.id,
                    title=lesson.title,
                    topic=lesson.topic,
                    description=lesson.description,
                    completed_at=lesson.completed_at,
                    tags=list(lesson.tags),
                )
                for lesson in completed
            ]

    def refresh_counts(self) -> None:
        try:
            self.banked_count = len(self.repository.list_banked_summaries())
        except Exception:
            self.banked_count = sum(
                1 for lesson in self.list_lessons() if lesson.status == LessonStatus.COMPLETED
            )
        try:
            self.due_count = len(self.repository.list_due_reviews())
        except Exception:
            self.due_count = 0
