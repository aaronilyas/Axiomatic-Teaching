"""stdio MCP server: the success gate, read-only lesson tools, and HTML present."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

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
from axiomatic_teaching.present import (
    CSS_MAX_CHARS,
    HTML_MAX_CHARS,
    MAX_PRESENT_BYTES,
    TITLE_MAX_CHARS,
    wrap_lesson_html,
)

_REPO: SqlRepository | None = None
_REPO_PATH: Path | None = None

RECORD_LESSON_SUCCESS_DESCRIPTION = (
    "Bank this lesson's knowledge after the learner has met the required success "
    "criterion (usually one, derived from the lesson's short success description). "
    "Use criterion_id values from get_lesson_criteria; do not invent ids. "
    "This tool rejects incomplete evidence (missing required items, too-short text, "
    "missing keywords, or met=false). This is the only way to bank knowledge — there "
    "is no other write path for completions, concepts, or style notes."
)

PRESENT_LESSON_HTML_DESCRIPTION = (
    "Show a self-contained lesson figure in the learner's default browser. "
    "Pass HTML (fragment or full document) plus an optional title and optional CSS. "
    "The TUI writes one file into this lesson's workspace and opens it via file://. "
    "This ACP session stays live. Chat in the TUI is the only place to ask questions "
    "— do not put questions, quizzes, forms, or JavaScript in the HTML. "
    "A return with ok=true means the host will write the file and open a tab; "
    "open_status will be host_pending and opened will be null because the TUI opens "
    "after this tool returns. Do not wait for a click on the page; keep teaching in "
    "this chat. Call again to show a new figure; each call is a new file and a new tab. "
    "Do not use this tool to bank knowledge — that remains record_lesson_success."
)


def _repository() -> SqlRepository:
    global _REPO, _REPO_PATH
    raw = os.environ.get("AXIOMATIC_DB")
    path = Path(raw).expanduser() if raw else default_db_path()
    if _REPO is not None and _REPO_PATH == path:
        return _REPO
    if _REPO is not None:
        try:
            _REPO.dispose()
        except Exception:
            pass
        _REPO = None
    _REPO = create_repository(path)
    _REPO_PATH = path
    return _REPO


def reset_repository_cache() -> None:
    """Drop the cached repository (tests)."""
    global _REPO, _REPO_PATH
    if _REPO is not None:
        try:
            _REPO.dispose()
        except Exception:
            pass
    _REPO = None
    _REPO_PATH = None


atexit.register(reset_repository_cache)


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
    try:
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
    except ValidationError as exc:
        return _dump(
            GateResult(
                accepted=False,
                lesson_id=lesson_id,
                unmet=[UnmetCriterion(reason="invalid record_lesson_success payload")],
                message=str(exc),
            )
        )
    try:
        result = _repository().record_success(request)
    except Exception as exc:  # noqa: BLE001 — MCP must return a structured gate result
        return _dump(
            GateResult(
                accepted=False,
                lesson_id=lesson_id,
                unmet=[UnmetCriterion(reason="internal error while evaluating the gate")],
                message=f"record_lesson_success failed: {exc}",
            )
        )
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


def list_banked_lessons() -> dict[str, Any]:
    """Return up to 20 banked lessons with id, title, and concept names.

    Wrapped in an object so an empty bank is not serialized as a blank MCP string.
    """
    summaries = _repository().list_banked_summaries()[:20]
    lessons = [
        {
            "id": item.id,
            "title": item.title,
            "topic": item.topic,
            "concepts": item.concepts,
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        }
        for item in summaries
    ]
    return {"lessons": lessons, "count": len(lessons)}


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


def _present_error(
    lesson_id: str | None,
    error: str,
    *,
    title: str = "",
) -> dict[str, Any]:
    return {
        "ok": False,
        "lesson_id": lesson_id,
        "title": title,
        "bytes": 0,
        "is_full_document": False,
        "css_inlined": False,
        "scripts_stripped": False,
        "host_action": "none",
        "open_status": "not_attempted",
        "opened": None,
        "written": False,
        "filename": None,
        "path": None,
        "file_url": None,
        "message": error if error.endswith(".") else f"{error}.",
        "error": error,
    }


def present_lesson_html(html: str, title: str = "", css: str = "") -> dict[str, Any]:
    """Validate an initial-reading HTML figure. The TUI writes the file and opens it."""
    lesson_id = _current_lesson_id()
    if lesson_id is None:
        return _present_error(None, "AXIOMATIC_LESSON_ID is not set")
    html_text = html if isinstance(html, str) else str(html or "")
    title_text = title if isinstance(title, str) else str(title or "")
    css_text = css if isinstance(css, str) else str(css or "")
    if not html_text.strip():
        return _present_error(lesson_id, "html must not be empty", title=title_text)
    if len(html_text) > HTML_MAX_CHARS:
        return _present_error(
            lesson_id, f"html exceeds {HTML_MAX_CHARS} characters", title=title_text
        )
    if len(css_text) > CSS_MAX_CHARS:
        return _present_error(
            lesson_id, f"css exceeds {CSS_MAX_CHARS} characters", title=title_text
        )
    if len(title_text) > TITLE_MAX_CHARS:
        return _present_error(
            lesson_id, f"title exceeds {TITLE_MAX_CHARS} characters", title=title_text
        )
    try:
        wrapped = wrap_lesson_html(html_text, title_text, css_text)
    except Exception as exc:
        return _present_error(lesson_id, f"could not assemble HTML: {exc}", title=title_text)
    byte_count = len(wrapped.document.encode("utf-8"))
    if byte_count > MAX_PRESENT_BYTES:
        return _present_error(
            lesson_id, "html exceeds maximum size after wrapping", title=title_text
        )
    return {
        "ok": True,
        "lesson_id": lesson_id,
        "title": wrapped.title,
        "bytes": byte_count,
        "is_full_document": wrapped.is_full_document,
        "css_inlined": wrapped.css_inlined,
        "scripts_stripped": wrapped.scripts_stripped,
        "host_action": "write_and_open",
        "open_status": "host_pending",
        "opened": None,
        "written": False,
        "filename": None,
        "path": None,
        "file_url": None,
        "message": (
            "Accepted. The TUI will write a self-contained HTML file into this "
            "lesson workspace and open the default browser. Keep asking questions "
            "in this chat; do not wait for a click on the page."
        ),
        "error": None,
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
            "Read the current lesson and its success criterion, including the "
            "criterion_id that record_lesson_success requires."
        )
    )(get_lesson_criteria)
    mcp.tool(
        description="List banked (completed) lessons with their concept names, capped at 20."
    )(list_banked_lessons)
    mcp.tool(
        description="Return 1-hop concept relations around the current lesson."
    )(get_connections)
    mcp.tool(description=PRESENT_LESSON_HTML_DESCRIPTION)(present_lesson_html)
    return mcp


mcp = _make_mcp()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
