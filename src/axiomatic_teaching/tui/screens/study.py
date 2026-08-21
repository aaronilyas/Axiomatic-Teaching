"""Study session: chat with Grok through ACP, success criterion, connections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from axiomatic_teaching.acp_client.events import (
    AgentStatus,
    PlanEvent,
    SessionController,
    StreamChunk,
    ThoughtChunk,
    ToolCallEvent,
)
from axiomatic_teaching.graph.queries import select_related_banked
from axiomatic_teaching.models import GateResult, Lesson, LessonStatus
from axiomatic_teaching.tui import is_gate_tool, parse_gate_result
from axiomatic_teaching.tui.widgets.chat_stream import ChatStream
from axiomatic_teaching.tui.widgets.connections_panel import ConnectionsPanel
from axiomatic_teaching.tui.widgets.criteria_panel import CriteriaPanel
from axiomatic_teaching.tui.widgets.input_bar import InputBar
from axiomatic_teaching.tui.widgets.lesson_list import LessonList
from axiomatic_teaching.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from axiomatic_teaching.app import AxiomaticApp


class StudyScreen(Screen[None]):
    app: AxiomaticApp

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("ctrl+s", "send", "Send", priority=True),
        Binding("ctrl+c", "cancel_turn", "Cancel", priority=True),
        Binding("question_mark", "app.help", "Help"),
    ]

    def __init__(self, lesson: Lesson | None = None) -> None:
        super().__init__()
        self.lesson = lesson
        self.session: SessionController | None = None
        self._starting = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="study-body"):
            with Vertical(id="study-lessons", classes="panel"):
                yield LessonList(id="study-lesson-list")
            with Vertical(id="study-center"):
                yield ChatStream(id="study-chat")
                yield InputBar(id="study-input")
            with Vertical(id="study-right"):
                yield CriteriaPanel(id="study-criteria")
                yield ConnectionsPanel(id="study-connections")
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        lessons = [
            item
            for item in self.app.list_lessons()
            if item.status not in {LessonStatus.DRAFT, LessonStatus.ARCHIVED}
        ]
        if self.lesson is None and lessons:
            self.lesson = lessons[0]
        if self.lesson is None:
            self.notify("No studyable lesson.", severity="warning")
            self.app.pop_screen()
            return
        self.sub_title = self.lesson.title
        self.query_one("#study-lesson-list", LessonList).set_lessons(
            lessons, group=False, selected_id=self.lesson.id
        )
        if self.lesson.status == LessonStatus.COMPLETED:
            self.notify("Already banked — restudy only; the gate will not re-bank.")
        self._refresh_panels()
        chat = self.query_one(ChatStream)
        if self.app.session_factory is None:
            chat.write_system("ACP not connected")
            self.app.apply_agent_status(
                AgentStatus(connected=False, message="ACP not connected", busy=False)
            )
            self.query_one(StatusBar).refresh_status()
            self.query_one(InputBar).focus_input()
            return
        self.run_worker(self._boot_session(), exclusive=True, group="session")

    async def on_unmount(self) -> None:
        self._starting = False
        try:
            self.workers.cancel_group("acp-send")
            self.workers.cancel_group("session")
        except Exception:
            pass
        await self._shutdown_session()

    def handle_acp_event(self, event: object) -> None:
        chat = self.query_one(ChatStream)
        if isinstance(event, StreamChunk):
            chat.append_stream(event)
        elif isinstance(event, ThoughtChunk):
            chat.append_thought(event)
        elif isinstance(event, ToolCallEvent):
            chat.append_tool(event)
            if is_gate_tool(event):
                gate = parse_gate_result(event.raw_output)
                if gate is not None:
                    self._apply_gate(gate)
        elif isinstance(event, PlanEvent):
            chat.append_plan(event)
        elif isinstance(event, AgentStatus):
            self.app.apply_agent_status(event)
            self.query_one(StatusBar).refresh_status()
        elif isinstance(event, GateResult):
            self._apply_gate(event)

    def _refresh_panels(self) -> None:
        lesson = self.lesson
        if lesson is None:
            return
        fresh = self.app.repository.get_lesson(lesson.id)
        if fresh is not None:
            self.lesson = fresh
            lesson = fresh
        self.query_one(CriteriaPanel).set_lesson(lesson)
        if self.app.last_gate is not None and self.app.last_gate.lesson_id == lesson.id:
            self.query_one(CriteriaPanel).apply_gate(self.app.last_gate)
        relations = []
        concepts = []
        due = []
        try:
            relations = self.app.repository.one_hop_relations(lesson.id)
        except Exception:
            try:
                relations = self.app.repository.list_relations()
            except Exception:
                relations = []
        try:
            concepts = self.app.repository.list_concepts(lesson.id)
        except Exception:
            concepts = []
        try:
            due = self.app.list_due()
        except Exception:
            due = []
        related = []
        style_notes: list[str] = []
        try:
            related = select_related_banked(self.app.repository, lesson)
        except Exception:
            related = []
        try:
            style_notes = [item.note for item in self.app.repository.list_style_notes(limit=3)]
        except Exception:
            style_notes = []
        self.query_one(ConnectionsPanel).show(
            relations, due, concepts, related=related, style_notes=style_notes
        )
        try:
            lessons = [
                item
                for item in self.app.list_lessons()
                if item.status not in {LessonStatus.DRAFT, LessonStatus.ARCHIVED}
            ]
            self.query_one("#study-lesson-list", LessonList).set_lessons(
                lessons, group=False, selected_id=lesson.id
            )
        except Exception:
            pass
        self.app.refresh_counts()
        self.query_one(StatusBar).refresh_status()

    def _apply_gate(self, result: GateResult) -> None:
        self.app.last_gate = result
        self.query_one(CriteriaPanel).apply_gate(result)
        if result.accepted:
            self.query_one(ChatStream).write_system(
                result.message or "Gate PASS — lesson banked."
            )
        else:
            self.query_one(ChatStream).write_system(result.message or "Gate FAIL.")
        self._refresh_panels()

    async def _boot_session(self) -> None:
        lesson = self.lesson
        if lesson is None:
            return
        if self._starting:
            return
        self._starting = True
        chat = self.query_one(ChatStream)
        try:
            factory = self.app.session_factory
            if factory is None:
                chat.write_system("ACP not connected")
                return
            try:
                session = self.app.create_session(lesson.id)
            except Exception as exc:
                chat.write_system(f"ACP not connected ({exc})")
                self.app.apply_agent_status(
                    AgentStatus(connected=False, message="ACP not connected", busy=False)
                )
                self.query_one(StatusBar).refresh_status()
                return
            if session is None:
                chat.write_system("ACP not connected")
                self.app.apply_agent_status(
                    AgentStatus(connected=False, message="ACP not connected", busy=False)
                )
                self.query_one(StatusBar).refresh_status()
                return
            self.session = session
            rules = self.app.assemble_rules(lesson)
            kickoff = self.app.kickoff_prompt(lesson)
            try:
                await session.start(lesson.id, rules, kickoff)
            except Exception as exc:
                chat.write_system(f"Could not start ACP session: {exc}")
                self.app.apply_agent_status(
                    AgentStatus(connected=False, message=str(exc), busy=False)
                )
                self.query_one(StatusBar).refresh_status()
                return
            session_id = getattr(session, "session_id", None)
            if session_id:
                try:
                    now = datetime.now(timezone.utc)
                    self.app.repository.set_last_session(lesson.id, session_id)
                    self.app.repository.record_acp_session(
                        lesson.id, session_id, started_at=now
                    )
                except Exception:
                    pass
            self.app.apply_agent_status(
                AgentStatus(
                    connected=True,
                    message="connected",
                    busy=bool(getattr(session, "busy", False)),
                    session_id=session_id,
                )
            )
            self.query_one(StatusBar).refresh_status()
            self.query_one(InputBar).focus_input()
        finally:
            self._starting = False

    async def _shutdown_session(self) -> None:
        session = self.session
        self.session = None
        if session is None:
            return
        session_id = getattr(session, "session_id", None)
        lesson = self.lesson
        try:
            await session.cancel()
        except Exception:
            pass
        try:
            await session.shutdown()
        except Exception:
            pass
        if session_id and lesson is not None:
            try:
                self.app.repository.record_acp_session(
                    lesson.id,
                    session_id,
                    started_at=datetime.now(timezone.utc),
                    ended_at=datetime.now(timezone.utc),
                    stop_reason="shutdown",
                )
            except Exception:
                pass
        self.app.apply_agent_status(
            AgentStatus(connected=False, message="ACP not connected", busy=False)
        )

    def action_send(self) -> None:
        bar = self.query_one(InputBar)
        text = bar.take()
        if not text:
            return
        self._send_text(text)

    @on(InputBar.Submitted)
    def _submitted(self, event: InputBar.Submitted) -> None:
        if event.text.strip():
            self._send_text(event.text.strip())

    def _send_text(self, text: str) -> None:
        chat = self.query_one(ChatStream)
        chat.append_user(text)
        session = self.session
        if session is None:
            chat.write_system("ACP not connected")
            return
        if bool(getattr(session, "busy", False)) or self.app.acp_busy:
            self.notify("Agent is busy. Cancel with ctrl+c.", severity="warning")
            return
        self.app.acp_busy = True
        self.query_one(StatusBar).refresh_status()
        self.run_worker(self._send_worker(text), group="acp-send", exclusive=True)

    async def _send_worker(self, text: str) -> None:
        session = self.session
        if session is None:
            return
        self.app.acp_busy = True
        try:
            self.query_one(StatusBar).refresh_status()
        except Exception:
            pass
        try:
            await session.send(text)
        except Exception as exc:
            try:
                self.query_one(ChatStream).write_system(f"Send failed: {exc}")
            except Exception:
                pass
        finally:
            busy = bool(getattr(self.session, "busy", False)) if self.session else False
            self.app.acp_busy = busy
            try:
                self.query_one(StatusBar).refresh_status()
            except Exception:
                pass

    async def action_cancel_turn(self) -> None:
        session = self.session
        if session is None:
            return
        try:
            await session.cancel()
        except Exception as exc:
            self.notify(f"Cancel failed: {exc}", severity="error")
            return
        self.query_one(ChatStream).write_system("Turn cancelled.")
        self.app.acp_busy = False
        self.query_one(StatusBar).refresh_status()

    async def action_back(self) -> None:
        await self._shutdown_session()
        self.app.pop_screen()

    @on(LessonList.LessonChosen, "#study-lesson-list")
    def _switch_lesson(self, event: LessonList.LessonChosen) -> None:
        if self.lesson is not None and event.lesson.id == self.lesson.id:
            return
        self.run_worker(self._switch_worker(event.lesson), exclusive=True, group="session")

    async def _switch_worker(self, lesson: Lesson) -> None:
        await self._shutdown_session()
        self.lesson = lesson
        self.sub_title = lesson.title
        self.query_one(ChatStream).reset()
        self._refresh_panels()
        if self.app.session_factory is None:
            self.query_one(ChatStream).write_system("ACP not connected")
            return
        self._starting = False
        await self._boot_session()
