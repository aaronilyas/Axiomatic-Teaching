"""ACP Client implementation that translates session updates into TUI events."""

from __future__ import annotations

import json
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
_PRESENT_HTML = "present_lesson_html"
_TOOL_NAME_KEYS = ("name", "tool", "toolName", "tool_name")
_DISPATCHER_IDS = frozenset({"search_tool", "use_tool", "callmcptool", "call_mcp_tool"})


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
        try:
            dumped = dump(mode="python", by_alias=False)
        except TypeError:
            dumped = dump()
        if isinstance(dumped, dict):
            return dumped
        value = dumped
    parsed = _json_object(value)
    if parsed is not None:
        return parsed
    return {"value": value}


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip() or text
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _merge_dicts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge tool-call input patches by key. Nested dicts merge; omitted keys stay."""
    out = dict(base)
    for key, value in patch.items():
        if value is None:
            continue
        existing = out.get(key)
        incoming = _json_object(value) if isinstance(value, str) else value
        previous = _json_object(existing) if isinstance(existing, str) else existing
        if isinstance(incoming, dict) and isinstance(previous, dict):
            out[key] = _merge_dicts(previous, incoming)
        elif isinstance(incoming, dict):
            out[key] = incoming
        else:
            out[key] = value
    return out


def _iter_content_texts(value: Any, depth: int = 0) -> list[str]:
    if depth > 6 or value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        texts: list[str] = []
        for item in value:
            texts.extend(_iter_content_texts(item, depth + 1))
        return texts
    texts: list[str] = []
    text = getattr(value, "text", None)
    if isinstance(text, str) and text.strip():
        texts.append(text)
    inner = getattr(value, "content", None)
    if inner is not None:
        texts.extend(_iter_content_texts(inner, depth + 1))
    if isinstance(value, dict):
        raw = value.get("text")
        if isinstance(raw, str) and raw.strip():
            texts.append(raw)
        if "content" in value:
            texts.extend(_iter_content_texts(value.get("content"), depth + 1))
    return texts


def _merge_content_payload(raw_input: dict[str, Any], content: Any) -> dict[str, Any]:
    from axiomatic_teaching.present import parse_present_html

    out = dict(raw_input)
    for text in _iter_content_texts(content):
        if parse_present_html(text) is None:
            continue
        blob = _as_dict(text)
        if blob and list(blob.keys()) != ["value"]:
            out = _merge_dicts(out, blob)
    return out


def _name_from_source(source: Any) -> str:
    if source is None:
        return ""
    if isinstance(source, dict):
        for key in ("toolName", "tool_name", "name"):
            value = source.get(key)
            if value:
                return str(value)
        return ""
    for key in ("toolName", "tool_name", "name"):
        value = getattr(source, key, None)
        if value:
            return str(value)
    extra = getattr(source, "model_extra", None)
    found = _name_from_source(extra) if extra else ""
    if found:
        return found
    meta = getattr(source, "field_meta", None)
    return _name_from_source(meta) if meta else ""


def _update_tool_name(update: Any, prev: dict[str, Any]) -> str:
    return _name_from_source(update) or str(prev.get("name") or "")


def _is_dispatcher_label(label: str) -> bool:
    text = (label or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("search tools:"):
        return True
    ident = lowered.rsplit("__", 1)[-1]
    return ident in _DISPATCHER_IDS or lowered in _DISPATCHER_IDS


def _identity_matches(label: str, needle: str) -> bool:
    text = (label or "").strip()
    if not text:
        return False
    lowered = text.lower()
    target = needle.lower()
    return lowered == target or lowered.endswith("__" + target)


def _prefer_allow(options: list[PermissionOption]) -> PermissionOption:
    for option in options:
        blob = " ".join(
            str(part or "")
            for part in (
                getattr(option, "kind", None),
                getattr(option, "name", None),
                getattr(option, "option_id", None),
            )
        ).lower()
        if "allow" in blob or "approve" in blob:
            return option
    return options[0]


def _mentions_tool(
    needle: str,
    title: str,
    kind: str,
    raw_input: dict[str, Any],
    raw_output: dict[str, Any] | None = None,
    extra: str = "",
) -> bool:
    candidates: list[str] = []
    # Title/kind/extra are identities, not search-query haystacks.
    if extra and not _is_dispatcher_label(extra):
        candidates.append(extra)
    if kind and not _is_dispatcher_label(kind):
        candidates.append(kind)
    if title and not _is_dispatcher_label(title):
        candidates.append(title)
    blobs: list[dict[str, Any]] = [raw_input]
    if raw_output:
        blobs.append(raw_output)
    for blob in blobs:
        if not isinstance(blob, dict):
            parsed = _as_dict(blob)
            blob = parsed
        # Do not scan argument `title` (present_lesson_html's page title).
        for key in _TOOL_NAME_KEYS:
            value = blob.get(key)
            if value:
                candidates.append(str(value))
    return any(_identity_matches(candidate, needle) for candidate in candidates)


def _is_success_gate(
    title: str,
    kind: str,
    raw_input: dict[str, Any],
    raw_output: dict[str, Any] | None = None,
    extra: str = "",
) -> bool:
    return _mentions_tool(_SUCCESS_GATE, title, kind, raw_input, raw_output, extra=extra)


def _is_present_html(
    title: str,
    kind: str,
    raw_input: dict[str, Any],
    raw_output: dict[str, Any] | None = None,
    extra: str = "",
) -> bool:
    if _mentions_tool(_PRESENT_HTML, title, kind, raw_input, raw_output, extra=extra):
        return True
    from axiomatic_teaching.present import parse_present_html

    if parse_present_html(raw_input) is not None:
        return True
    if raw_output is not None and parse_present_html(raw_output) is not None:
        return True
    return False


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
        self._tool_calls: dict[str, dict[str, Any]] = {}

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
        chosen = _prefer_allow(options)
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=chosen.option_id),
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
            tool_call_id = str(getattr(update, "tool_call_id", "") or "")
            prev = self._tool_calls.get(tool_call_id, {})
            title = getattr(update, "title", None) or prev.get("title") or ""
            kind = str(getattr(update, "kind", None) or prev.get("kind") or "")
            name = _update_tool_name(update, prev)
            incoming_input = getattr(update, "raw_input", None)
            raw_input = dict(prev.get("raw_input") or {})
            if incoming_input is not None:
                raw_input = _merge_dicts(raw_input, _as_dict(incoming_input))
            raw_input = _merge_content_payload(
                raw_input, getattr(update, "content", None)
            )
            raw_output_val = getattr(update, "raw_output", None)
            raw_output = _as_dict(raw_output_val) if raw_output_val is not None else None
            status = getattr(update, "status", None)
            if not status:
                status = "pending" if isinstance(update, ToolCallStart) else "in_progress"
            self._tool_calls[tool_call_id] = {
                "title": title,
                "kind": kind,
                "name": name,
                "raw_input": raw_input,
            }
            if str(status) in {"completed", "failed"}:
                self._tool_calls.pop(tool_call_id, None)
            gate = _is_success_gate(title, kind, raw_input, raw_output, extra=name)
            self._emit(
                ToolCallEvent(
                    tool_call_id=tool_call_id,
                    title=title,
                    kind=kind,
                    status=str(status),
                    raw_input=raw_input,
                    raw_output=raw_output,
                    session_id=session_id,
                    is_success_gate=gate,
                    is_present_html=(
                        False
                        if gate
                        else _is_present_html(
                            title, kind, raw_input, raw_output, extra=name
                        )
                    ),
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
