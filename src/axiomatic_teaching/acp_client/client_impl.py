"""ACP Client implementation that translates session updates into TUI events."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from acp import Client, RequestError
from acp.schema import (
    AgentMessageChunk,
    AgentPlanContentUpdate,
    AgentPlanRemovedUpdate,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AllowedOutcome,
    CreateElicitationResponse,
    CreateTerminalResponse,
    DeclineElicitationResponse,
    DeniedOutcome,
    ElicitationMode,
    EnvVariable,
    KillTerminalResponse,
    PermissionOption,
    ReadTextFileResponse,
    ReleaseTerminalResponse,
    RequestPermissionResponse,
    TerminalOutputResponse,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
    UserMessageChunk,
    WaitForTerminalExitResponse,
    WriteTextFileResponse,
)

from axiomatic_teaching.acp_client.events import PlanEvent, StreamChunk, ThoughtChunk, ToolCallEvent

log = logging.getLogger(__name__)

_SUCCESS_GATE = "record_lesson_success"


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(content, dict):
        raw = content.get("text")
        if isinstance(raw, str):
            return raw
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump(mode="python", by_alias=False)
        if isinstance(dumped, dict):
            return dumped
    return {"value": value}


def _is_success_gate(
    title: str,
    kind: str,
    raw_input: dict[str, Any],
    raw_output: dict[str, Any] | None = None,
) -> bool:
    parts = [title, kind]
    blobs = [raw_input]
    if raw_output:
        blobs.append(raw_output)
    for blob in blobs:
        for key in ("name", "tool", "title", "toolName", "tool_name"):
            extra = blob.get(key)
            if extra:
                parts.append(str(extra))
    return _SUCCESS_GATE in " ".join(parts).lower()


def _plan_entries(update: Any) -> list[str]:
    entries = getattr(update, "entries", None)
    if entries is None:
        plan = getattr(update, "plan", None)
        entries = getattr(plan, "entries", None)
        if entries is None and plan is not None:
            inner = getattr(plan, "plan", None) or getattr(plan, "root", None)
            entries = getattr(inner, "entries", None)
    if not entries:
        return []
    lines: list[str] = []
    for entry in entries:
        content = getattr(entry, "content", None)
        lines.append(str(content if content is not None else entry))
    return lines


class AxiomaticClient(Client):
    """ACP client that maps session/update notifications into TUI dataclasses."""

    def __init__(self, on_event: Callable[[Any], None]) -> None:
        self._on_event = on_event

    def _emit(self, event: Any) -> None:
        try:
            self._on_event(event)
        except Exception:
            log.exception("on_event callback failed")

    async def request_permission(
        self,
        session_id: str,
        tool_call: ToolCallUpdate,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        # Auto-allow so the TUI cannot deadlock even without --always-approve.
        if not options:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=options[0].option_id),
        )

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        if isinstance(update, AgentMessageChunk):
            self._emit(
                StreamChunk(
                    text=_content_text(update.content),
                    role="agent",
                    session_id=session_id,
                )
            )
            return
        if isinstance(update, AgentThoughtChunk):
            self._emit(ThoughtChunk(text=_content_text(update.content), session_id=session_id))
            return
        if isinstance(update, (ToolCallStart, ToolCallProgress, ToolCallUpdate)):
            title = getattr(update, "title", None) or ""
            kind = str(getattr(update, "kind", None) or "")
            raw_input = _as_dict(getattr(update, "raw_input", None))
            raw_output_val = getattr(update, "raw_output", None)
            raw_output = _as_dict(raw_output_val) if raw_output_val is not None else None
            status = getattr(update, "status", None)
            if not status:
                status = "pending" if isinstance(update, ToolCallStart) else "in_progress"
            self._emit(
                ToolCallEvent(
                    tool_call_id=str(getattr(update, "tool_call_id", "") or ""),
                    title=title,
                    kind=kind,
                    status=str(status),
                    raw_input=raw_input,
                    raw_output=raw_output,
                    session_id=session_id,
                    is_success_gate=_is_success_gate(title, kind, raw_input, raw_output),
                )
            )
            return
        if isinstance(update, (AgentPlanUpdate, AgentPlanContentUpdate)):
            self._emit(PlanEvent(entries=_plan_entries(update), session_id=session_id))
            return
        if isinstance(update, AgentPlanRemovedUpdate):
            self._emit(PlanEvent(entries=[], session_id=session_id))
            return
        if isinstance(update, UserMessageChunk):
            self._emit(
                StreamChunk(text=_content_text(update.content), role="user", session_id=session_id)
            )

    async def write_text_file(
        self, session_id: str, path: str, content: str, **kwargs: Any
    ) -> WriteTextFileResponse | None:
        raise RequestError.method_not_found("fs/write_text_file")

    async def read_text_file(
        self, session_id: str, path: str, line: int | None = None, limit: int | None = None, **kwargs: Any
    ) -> ReadTextFileResponse:
        raise RequestError.method_not_found("fs/read_text_file")

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        env: list[EnvVariable] | None = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
        **kwargs: Any,
    ) -> CreateTerminalResponse:
        raise RequestError.method_not_found("terminal/create")

    async def terminal_output(self, session_id: str, terminal_id: str, **kwargs: Any) -> TerminalOutputResponse:
        raise RequestError.method_not_found("terminal/output")

    async def release_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> ReleaseTerminalResponse | None:
        raise RequestError.method_not_found("terminal/release")

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> WaitForTerminalExitResponse:
        raise RequestError.method_not_found("terminal/wait_for_exit")

    async def kill_terminal(self, session_id: str, terminal_id: str, **kwargs: Any) -> KillTerminalResponse | None:
        raise RequestError.method_not_found("terminal/kill")

    async def create_elicitation(self, message: str, mode: ElicitationMode, **kwargs: Any) -> CreateElicitationResponse:
        return DeclineElicitationResponse(action="decline")

    async def complete_elicitation(self, elicitation_id: str, **kwargs: Any) -> None:
        return None

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        # Grok Build sends x.ai extension methods; none are required for tutoring.
        log.debug("Ignoring ACP extension method %s", method)
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        # Grok Build pushes _x.ai/* notifications (MCP status, models, queue).
        # Swallow them so they do not error the JSON-RPC session.
        log.debug("Ignoring ACP extension notification %s", method)
