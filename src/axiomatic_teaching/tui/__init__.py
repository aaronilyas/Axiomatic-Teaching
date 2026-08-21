"""Textual TUI package. Helpers here are shared by screens and widgets."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, TypeVar

from textual.message import Message

from axiomatic_teaching.acp_client.events import ToolCallEvent
from axiomatic_teaching.models import Concept, ConceptRelation, GateResult

GATE_TOOL_NAME = "record_lesson_success"
PRESENT_HTML_TOOL_NAME = "present_lesson_html"

FALLBACK_RULES = (
    "You are a Socratic tutor inside Axiomatic Teaching. "
    "The learner never talks to you except through this TUI. "
    "Teach the current lesson. Do not claim the lesson is complete. "
    "When the learner has met the required success criterion, call the MCP tool "
    "record_lesson_success with evidence for that criterion. "
    "Never invent a mark-complete shortcut. The success gate is the only way to bank the lesson. "
    "Call present_lesson_html for exposition-only HTML; keep all probes in this chat."
)

T = TypeVar("T")


class ACPEvent(Message):
    """Thread-safe wrapper so an ACP client can post domain events into the app."""

    def __init__(self, payload: object) -> None:
        super().__init__()
        self.payload = payload


# Textual's camel_to_snake("ACPEvent") is "acpevent" (no aA boundary in the acronym).
# Pin the handler so App.on_acp_event is actually dispatched.
ACPEvent.handler_name = "on_acp_event"


def invoke_flexible(fn: Callable[..., T], available: Mapping[str, Any]) -> T:
    """Call ``fn`` binding arguments by name from ``available``."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        try:
            return fn(**{k: v for k, v in available.items()})
        except TypeError:
            return fn()

    accepts_var_kw = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    bound: dict[str, Any] = {}
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        if parameter.kind in {
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        }:
            continue
        if parameter.name in available:
            bound[parameter.name] = available[parameter.name]
    if accepts_var_kw:
        for key, value in available.items():
            bound.setdefault(key, value)
    try:
        return fn(**bound)
    except TypeError:
        positional: list[Any] = []
        used: set[str] = set()
        for parameter in signature.parameters.values():
            if parameter.name in {"self", "cls"}:
                continue
            if parameter.kind in {
                inspect.Parameter.VAR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.KEYWORD_ONLY,
            }:
                continue
            if parameter.name in available:
                positional.append(available[parameter.name])
                used.add(parameter.name)
        kwargs = {key: value for key, value in bound.items() if key not in used}
        return fn(*positional, **kwargs)


def is_gate_tool(event: ToolCallEvent) -> bool:
    if event.is_success_gate:
        return True
    return _tool_name_in_event(event, GATE_TOOL_NAME)


def is_present_html_tool(event: ToolCallEvent) -> bool:
    if getattr(event, "is_present_html", False):
        return True
    return _tool_name_in_event(event, PRESENT_HTML_TOOL_NAME)


def _tool_name_in_event(event: ToolCallEvent, name: str) -> bool:
    blob = " ".join(
        part
        for part in (event.title, event.kind, event.tool_call_id)
        if part
    ).lower()
    if name in blob:
        return True
    for raw in (event.raw_input, event.raw_output):
        if isinstance(raw, dict):
            label = str(
                raw.get("name") or raw.get("tool") or raw.get("toolName") or raw.get("tool_name") or ""
            )
            if name in label.lower():
                return True
    return False


def parse_gate_result(payload: object) -> GateResult | None:
    if payload is None:
        return None
    if isinstance(payload, GateResult):
        return payload
    return _parse_gate_result(payload, depth=0)


def _parse_gate_result(payload: object, depth: int) -> GateResult | None:
    if depth > 6 or payload is None:
        return None
    if isinstance(payload, GateResult):
        return payload
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        if text.startswith("```"):
            lines = text.splitlines()
            inner = "\n".join(line for line in lines if not line.strip().startswith("```"))
            text = inner.strip() or text
        try:
            return GateResult.model_validate_json(text)
        except Exception:
            return None
    if isinstance(payload, list):
        for item in payload:
            parsed = _parse_gate_result(item, depth + 1)
            if parsed is not None:
                return parsed
        return None
    if not isinstance(payload, dict):
        return None
    if "accepted" in payload and "lesson_id" in payload:
        try:
            return GateResult.model_validate(payload)
        except Exception:
            pass
    candidates: list[object] = []
    for key in (
        "result",
        "gate",
        "output",
        "data",
        "structuredContent",
        "structured_content",
        "content",
        "text",
        "OkayOutput",
    ):
        if key in payload:
            candidates.append(payload[key])
    nested = payload.get("output")
    if isinstance(nested, dict) and "OkayOutput" in nested:
        candidates.append(nested["OkayOutput"])
    for candidate in candidates:
        parsed = _parse_gate_result(candidate, depth + 1)
        if parsed is not None:
            return parsed
    return None


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def format_relation(
    relation: ConceptRelation,
    concepts: Sequence[Concept] | Mapping[str, Concept] | None = None,
) -> str:
    by_id: Mapping[str, Concept]
    if isinstance(concepts, Mapping):
        by_id = concepts
    elif concepts:
        by_id = {concept.id: concept for concept in concepts}
    else:
        by_id = {}
    left = relation.from_name.strip() if relation.from_name else ""
    right = relation.to_name.strip() if relation.to_name else ""
    if not left:
        source = by_id.get(relation.from_concept_id)
        left = source.name if source is not None else relation.from_concept_id
    if not right:
        target = by_id.get(relation.to_concept_id)
        right = target.name if target is not None else relation.to_concept_id
    return f"{left} —{relation.relation}→ {right}"
