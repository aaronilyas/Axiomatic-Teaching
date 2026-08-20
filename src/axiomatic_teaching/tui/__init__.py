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

FALLBACK_RULES = (
    "You are a Socratic tutor inside Axiomatic Teaching. "
    "The learner never talks to you except through this TUI. "
    "Teach the current lesson. Do not claim the lesson is complete. "
    "When the learner has met every required success criterion, call the MCP tool "
    "record_lesson_success with evidence for each criterion. "
    "Never invent a mark-complete shortcut. The success gate is the only way to bank the lesson."
)

T = TypeVar("T")


class ACPEvent(Message):
    """Thread-safe wrapper so an ACP client can post domain events into the app."""

    def __init__(self, payload: object) -> None:
        super().__init__()
        self.payload = payload


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
    blob = " ".join(
        part
        for part in (event.title, event.kind, event.tool_call_id)
        if part
    ).lower()
    if GATE_TOOL_NAME in blob:
        return True
    raw = event.raw_input
    if isinstance(raw, dict):
        name = str(raw.get("name") or raw.get("tool") or raw.get("toolName") or "")
        if GATE_TOOL_NAME in name.lower():
            return True
    return False


def parse_gate_result(payload: object) -> GateResult | None:
    if payload is None:
        return None
    if isinstance(payload, GateResult):
        return payload
    candidates: list[object] = [payload]
    if isinstance(payload, dict):
        for key in (
            "result",
            "gate",
            "output",
            "data",
            "structuredContent",
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
        if isinstance(candidate, GateResult):
            return candidate
        if isinstance(candidate, str):
            text = candidate.strip()
            if not text:
                continue
            try:
                return GateResult.model_validate_json(text)
            except Exception:
                continue
        if isinstance(candidate, dict) and "accepted" in candidate and "lesson_id" in candidate:
            try:
                return GateResult.model_validate(candidate)
            except Exception:
                continue
        if isinstance(candidate, list):
            for item in candidate:
                parsed = parse_gate_result(item)
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


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
