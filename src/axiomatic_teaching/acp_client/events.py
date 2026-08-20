"""Typed events posted from the ACP client into the Textual app.

The TUI must not import ACP schema types. The ACP client translates session/update
notifications into these dataclasses / Textual messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class StreamChunk:
    """A piece of agent or user visible text."""

    text: str
    role: str = "agent"  # agent | user | system
    session_id: str = ""


@dataclass(slots=True)
class ThoughtChunk:
    text: str
    session_id: str = ""


@dataclass(slots=True)
class ToolCallEvent:
    tool_call_id: str
    title: str
    kind: str = ""
    status: str = "pending"  # pending | in_progress | completed | failed
    raw_input: dict[str, Any] = field(default_factory=dict)
    raw_output: dict[str, Any] | None = None
    session_id: str = ""
    is_success_gate: bool = False


@dataclass(slots=True)
class PlanEvent:
    entries: list[str] = field(default_factory=list)
    session_id: str = ""


@dataclass(slots=True)
class AgentStatus:
    connected: bool
    message: str = ""
    session_id: str | None = None
    busy: bool = False


class SessionController(Protocol):
    """Implemented by acp_client.grok.GrokSession. Consumed by the Study screen."""

    @property
    def busy(self) -> bool: ...

    @property
    def session_id(self) -> str | None: ...

    async def start(self, lesson_id: str, rules: str, kickoff_prompt: str) -> None: ...

    async def send(self, text: str) -> None: ...

    async def cancel(self) -> None: ...

    async def shutdown(self) -> None: ...
