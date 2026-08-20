"""stdio MCP server: the success gate plus read-only lesson tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.db.sql_repository import SqlRepository
from axiomatic_teaching.models import (
    EvidenceItem,
    GateResult,
    ProposedConcept,
    ProposedRelation,
    RecordSuccessRequest,
    UnmetCriterion,
)
from axiomatic_teaching.paths import default_db_path

RECORD_LESSON_SUCCESS_DESCRIPTION = (
    "Bank this lesson's knowledge after the learner has met every required success "
    "criterion. Use criterion_id values from get_lesson_criteria; do not invent ids. "
    "This tool rejects incomplete evidence (missing required items, too-short text, "
    "missing keywords, or met=false). This is the only way to bank knowledge — there "
    "is no other write path for completions, concepts, or style notes."
)


def _repository() -> SqlRepository:
    raw = os.environ.get("AXIOMATIC_DB")
    path = Path(raw).expanduser() if raw else default_db_path()
    return create_repository(path)


def _current_lesson_id() -> str | None:
    value = os.environ.get("AXIOMATIC_LESSON_ID")
    if value is None:
        return None
    value = value.strip()
    return value or None


def _dump(result: GateResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def _mismatch_result(lesson_id: str) -> GateResult:
    return GateResult(
        accepted=False,
        lesson_id=lesson_id,
        unmet=[
            UnmetCriterion(
                criterion_id=None,
                reason="lesson_id does not match AXIOMATIC_LESSON_ID",
            )
        ],
        message="Refusing to bank a different lesson than the current session.",
    )


def record_lesson_success(
    lesson_id: str,
    evidence: list[EvidenceItem] | list[dict[str, Any]],
    notes: str = "",
    concepts: list[ProposedConcept] | list[dict[str, Any]] | None = None,
    relations: list[ProposedRelation] | list[dict[str, Any]] | None = None,
    style_note: str = "",
    acp_session_id: str | None = None,
) -> dict[str, Any]:
    """Run the success gate. Completions are written only when every required criterion is met."""
    current = _current_lesson_id()
    if current is not None and current != lesson_id:
        return _dump(_mismatch_result(lesson_id))
    request = RecordSuccessRequest.model_validate(
        {
            "lesson_id": lesson_id,
            "evidence": evidence,
            "notes": notes,
            "concepts": concepts or [],
            "relations": relations or [],
            "style_note": style_note,
            "acp_session_id": acp_session_id,
        }
    )
    result = _repository().record_success(request)
    return _dump(result)


def get_lesson_criteria() -> dict[str, Any]:
    """Return the current lesson and its criterion ids for record_lesson_success."""
    lesson_id = _current_lesson_id()
    if lesson_id is None:
        return {"error": "AXIOMATIC_LESSON_ID is not set"}
    lesson = _repository().get_lesson(lesson_id)
    if lesson is None:
        return {"error": "lesson not found", "lesson_id": lesson_id}
    return {
        "lesson_id": lesson.id,
        "title": lesson.title,
        "topic": lesson.topic,
        "status": lesson.status.value,
        "description": lesson.description,
        "success_description": lesson.success_description,
        "criteria": [
            {
                "id": c.id,
                "kind": c.kind.value,
                "statement": c.statement,
                "required": c.required,
                "min_evidence_chars": c.min_evidence_chars,
                "keywords": c.keywords,
                "sort_order": c.sort_order,
            }
            for c in lesson.criteria
        ],
    }


def list_banked_lessons() -> list[dict[str, Any]]:
    """Return up to 20 banked lessons with id, title, and concept names."""
    summaries = _repository().list_banked_summaries()[:20]
    return [
        {
            "id": item.id,
            "title": item.title,
            "topic": item.topic,
            "concepts": item.concepts,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        }
        for item in summaries
    ]


def get_connections() -> dict[str, Any]:
    """Return 1-hop concept relations around the current lesson."""
    lesson_id = _current_lesson_id()
    if lesson_id is None:
        return {"error": "AXIOMATIC_LESSON_ID is not set"}
    relations = _repository().one_hop_relations(lesson_id)
    return {
        "lesson_id": lesson_id,
        "relations": [rel.model_dump(mode="json") for rel in relations],
    }


def _make_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        from mcp.server import MCPServer as FastMCP

    mcp = FastMCP("axiomatic-teaching")
    mcp.tool(description=RECORD_LESSON_SUCCESS_DESCRIPTION)(record_lesson_success)
    mcp.tool(
        description=(
            "Read the current lesson and its success criteria, including criterion_id "
            "values that record_lesson_success requires."
        )
    )(get_lesson_criteria)
    mcp.tool(
        description="List banked (completed) lessons with their concept names, capped at 20."
    )(list_banked_lessons)
    mcp.tool(
        description="Return 1-hop concept relations around the current lesson."
    )(get_connections)
    return mcp


mcp = _make_mcp()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
