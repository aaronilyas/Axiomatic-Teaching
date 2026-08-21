"""Streaming chat log for ACP events."""

from __future__ import annotations

from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from textual.timer import Timer
from textual.widgets import RichLog

from axiomatic_teaching.acp_client.events import (
    PlanEvent,
    StreamChunk,
    ThoughtChunk,
    ToolCallEvent,
)
from axiomatic_teaching.tui import is_gate_tool, is_present_html_tool

# Host-injected session context / Grok system blobs must never reach the learner.
_HOST_CONTEXT_MARKERS = (
    "<axiomatic-context>",
    "</axiomatic-context>",
    "# Pedagogy rules",
    "min_evidence_chars",
    "<user_info>",
    "</user_info>",
    "<human_rules>",
    "</human_rules>",
    "<available_skills>",
    "</available_skills>",
)


def is_host_context_text(text: str) -> bool:
    """True when *text* looks like host rules, Grok system prompt, or assembled context."""
    if not text:
        return False
    for marker in _HOST_CONTEXT_MARKERS:
        if marker in text:
            return True
    if "- **keywords:**" in text and (
        "- **min_evidence_chars:**" in text or "min_evidence_chars" in text
    ):
        return True
    if "#### " in text and "- **id:**" in text and "- **statement:**" in text:
        return True
    return False


class ChatStream(RichLog):
    DEFAULT_CSS = """
    ChatStream {
        height: 1fr;
        width: 1fr;
        background: #080b0f;
        border: tall #1e2a36;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            highlight=False,
            markup=True,
            wrap=True,
            min_width=16,
            max_lines=4000,
            **kwargs,  # type: ignore[arg-type]
        )
        self._stream_role: str | None = None
        self._stream_buffer = ""
        self._partial_timer: Timer | None = None

    def write_system(self, text: str) -> None:
        self._flush_stream()
        self.write(f"[dim]{escape(text)}[/]")

    def append_stream(self, chunk: StreamChunk) -> None:
        role = chunk.role or "agent"
        # Learner turns are rendered only via append_user. Host user_message_chunk
        # (kickoff / echoed session/prompt) must never appear as a "you" line.
        if role.lower() == "user":
            return
        if is_host_context_text(chunk.text):
            return
        if self._stream_role not in (None, role):
            self._flush_stream()
        if self._stream_role is None:
            self._stream_role = role
            prefix = _role_prefix(role)
            if prefix:
                self.write(prefix)
        self._stream_buffer += chunk.text
        while "\n" in self._stream_buffer:
            line, self._stream_buffer = self._stream_buffer.split("\n", 1)
            self.write(escape(line) if line else "")
        self._arm_partial_flush()

    def append_thought(self, thought: ThoughtChunk) -> None:
        """Hide Grok's internal reasoning; ThoughtChunk events never write to the chat."""

    def append_tool(self, event: ToolCallEvent) -> None:
        self._flush_stream()
        gate = is_gate_tool(event)
        present = (not gate) and is_present_html_tool(event)
        title = event.title or event.kind or event.tool_call_id or "tool"
        status = event.status or "pending"
        heading = "GATE" if gate else "TOOL"
        accent = "cyan" if gate else "yellow"
        if status in {"pending", "in_progress"}:
            self.write(
                f"[{accent}]{heading}[/] {escape(title)}  [dim]{escape(status)}[/]"
            )
            return
        detail_lines = [f"[bold]{escape(title)}[/]", f"[dim]{escape(status)}[/]"]
        if present:
            label = "lesson page"
            given = ""
            if isinstance(event.raw_input, dict):
                given = str(event.raw_input.get("title") or "").strip()
            if (not given or given.lower() == "present_lesson_html") and event.title:
                given = event.title.strip()
            if given and given.lower() != "present_lesson_html":
                label = given
            detail_lines.append(f"[dim]{escape(label)}[/]")
        elif event.raw_output is not None:
            preview = _preview(event.raw_output)
            if preview and not is_host_context_text(str(event.raw_output)):
                detail_lines.append(preview)
        body = Text.from_markup("\n".join(detail_lines))
        self.write(
            Panel(
                body,
                title=heading,
                border_style=accent,
                padding=(0, 1),
            )
        )

    def append_plan(self, event: PlanEvent) -> None:
        self._flush_stream()
        if not event.entries:
            return
        lines = ["[dim]plan[/]"]
        for index, entry in enumerate(event.entries, start=1):
            lines.append(f"[dim]{index}. {escape(entry)}[/]")
        self.write("\n".join(lines))

    def append_user(self, text: str) -> None:
        self._flush_stream()
        self.write(f"[bold cyan]you[/] {escape(text)}")

    def reset(self) -> None:
        if self._partial_timer is not None:
            self._partial_timer.stop()
            self._partial_timer = None
        self._stream_role = None
        self._stream_buffer = ""
        self.clear()

    def _arm_partial_flush(self) -> None:
        if self._partial_timer is not None:
            self._partial_timer.stop()
        self._partial_timer = self.set_timer(0.08, self._flush_partial)

    def _flush_partial(self) -> None:
        self._partial_timer = None
        if self._stream_buffer:
            self.write(escape(self._stream_buffer))
            self._stream_buffer = ""

    def _flush_stream(self) -> None:
        if self._partial_timer is not None:
            self._partial_timer.stop()
            self._partial_timer = None
        leftover = self._stream_buffer
        self._stream_buffer = ""
        role = self._stream_role
        self._stream_role = None
        if leftover:
            self.write(escape(leftover))
        elif role is None:
            return


def _role_prefix(role: str) -> str:
    if role == "user":
        return "[bold cyan]you[/]"
    if role == "system":
        return "[dim]system[/]"
    return "[bold]tutor[/]"


def _preview(payload: object, limit: int = 240) -> str:
    text = str(payload).strip()
    if not text:
        return ""
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"[dim]{escape(text)}[/]"
