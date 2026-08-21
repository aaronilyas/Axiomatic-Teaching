"""Assemble the `_meta.rules` markdown blob for a study session."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from axiomatic_teaching.config import (
    CONTEXT_CHAR_BUDGET,
    DUE_REVIEW_CAP,
    RELATED_LESSON_CAP,
    RELATION_CAP,
    STYLE_NOTE_CAP,
)
from axiomatic_teaching.context.pedagogy import PEDAGOGY_RULES
from axiomatic_teaching.db.repository import Repository
from axiomatic_teaching.graph.queries import (
    banked_summaries_for,
    deleted_lesson_ids,
    format_edge,
    one_hop_edges,
    select_related_banked,
)
from axiomatic_teaching.models import (
    BankedLessonSummary,
    ConceptRelation,
    Criterion,
    DueReview,
    Lesson,
    LessonStatus,
    StyleNote,
)

T = TypeVar("T")


def assemble(
    repository: Repository,
    lesson: Lesson,
    budget: int = CONTEXT_CHAR_BUDGET,
) -> str:
    """Build `_meta.rules` markdown.

    Current lesson criterion text is never truncated. Optional sections shrink in
    this order until ``budget`` is met: related descriptions,
    then style notes, then relations.
    """
    cap = budget if budget > 0 else CONTEXT_CHAR_BUDGET
    pedagogy = PEDAGOGY_RULES.strip()
    criteria = _criteria(repository, lesson)
    current_core = _format_current_lesson(lesson, criteria)
    mastery = _format_mastery(repository, lesson)

    hidden = _safe(lambda: deleted_lesson_ids(repository), set())
    related = [
        item
        for item in _safe(
            lambda: select_related_banked(repository, lesson, cap=RELATED_LESSON_CAP),
            [],
        )
        if item.id not in hidden
    ]
    relations = _safe(lambda: one_hop_edges(repository, lesson.id, cap=RELATION_CAP), [])
    style_notes = _safe(lambda: list(repository.list_style_notes(limit=STYLE_NOTE_CAP) or []), [])[
        :STYLE_NOTE_CAP
    ]
    due_reviews = [
        item
        for item in _safe(lambda: list(repository.list_due_reviews() or []), [])
        if item.lesson_id not in hidden
    ][:DUE_REVIEW_CAP]

    desc_limit: int | None = None
    n_styles = len(style_notes)
    n_rels = len(relations)
    related_keep = list(related)
    dues_keep = list(due_reviews)

    def render() -> str:
        parts = [
            pedagogy,
            current_core,
            mastery,
            _format_related(related_keep, desc_limit),
            _format_relations(relations[:n_rels]),
            _format_style_notes(style_notes[:n_styles]),
            _format_due_reviews(dues_keep),
        ]
        return "\n\n".join(part for part in parts if part).strip() + "\n"

    text = render()
    while len(text) > cap:
        if desc_limit is None:
            desc_limit = 160
        elif desc_limit > 0:
            desc_limit = 0 if desc_limit <= 40 else desc_limit // 2
        elif n_styles > 0:
            n_styles -= 1
        elif n_rels > 0:
            n_rels -= 1
        elif dues_keep:
            dues_keep.pop()
        elif related_keep:
            related_keep.pop()
        else:
            break
        text = render()

    if len(text) > cap:
        text = _required_within_budget(pedagogy, current_core, mastery, cap)
    return text


def kickoff_prompt(lesson: Lesson) -> str:
    """Short first session/prompt: one diagnostic plus present_lesson_html."""
    if lesson.status == LessonStatus.COMPLETED:
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


def _safe(fn: Callable[[], T], default: T) -> T:
    try:
        result = fn()
    except Exception:
        return default
    return default if result is None else result


def _criteria(repository: Repository, lesson: Lesson) -> list[Criterion]:
    if lesson.criteria:
        return sorted(lesson.criteria, key=lambda item: (item.sort_order, item.id))
    try:
        found = list(repository.list_criteria(lesson.id) or [])
    except Exception:
        return []
    return sorted(found, key=lambda item: (item.sort_order, item.id))


def _format_current_lesson(lesson: Lesson, criteria: list[Criterion]) -> str:
    lines = [
        "## Current lesson",
        f"- **Title:** {lesson.title}",
        f"- **Topic:** {lesson.topic}",
        f"- **Description:** {_truncate(lesson.description, 240)}",
        f"- **Success description:** {_truncate(lesson.success_description, 240)}",
        "",
        "### Success criterion" if len(criteria) <= 1 else "### Success criteria",
    ]
    if not criteria:
        lines.append("_No success criterion listed._")
        return "\n".join(lines)
    for criterion in criteria:
        keywords = ", ".join(criterion.keywords) if criterion.keywords else "(none)"
        required = "true" if criterion.required else "false"
        lines.extend(
            [
                f"#### {criterion.id}",
                f"- **id:** {criterion.id}",
                f"- **statement:** {criterion.statement}",
                f"- **required:** {required}",
                f"- **min_evidence_chars:** {criterion.min_evidence_chars}",
                f"- **keywords:** {keywords}",
            ]
        )
    return "\n".join(lines)


def _format_mastery(repository: Repository, lesson: Lesson) -> str:
    hidden = _safe(lambda: deleted_lesson_ids(repository), set())
    due_count = 0
    try:
        due_count = len(
            [
                item
                for item in (repository.list_due_reviews() or [])
                if item.lesson_id not in hidden
            ]
        )
    except Exception:
        due_count = 0
    titles: list[str] = []
    try:
        summaries = [
            item
            for item in banked_summaries_for(repository, lesson.id)
            if item.id not in hidden
        ]
        summaries = sorted(
            summaries,
            key=lambda item: _as_utc(item.completed_at),
            reverse=True,
        )
        titles = [item.title for item in summaries[:5] if item.title]
    except Exception:
        titles = []
    last_completed = "; ".join(titles) if titles else "(none)"
    status = getattr(lesson.status, "value", lesson.status)
    return "\n".join(
        [
            "## Mastery",
            f"- **Status:** {status}",
            f"- **Due count:** {due_count}",
            f"- **Last completed:** {last_completed}",
        ]
    )


def _format_related(
    related: list[BankedLessonSummary],
    desc_limit: int | None,
) -> str:
    if not related:
        return ""
    lines = ["## Related banked lessons"]
    for item in related:
        description = item.description or ""
        if desc_limit is not None:
            description = _truncate(description, desc_limit)
        concepts = ", ".join(name for name in item.concepts if name) or "(none)"
        lines.extend(
            [
                f"### {item.title}",
                f"- **Topic:** {item.topic}",
                f"- **Description:** {description}",
                f"- **Concepts:** {concepts}",
            ]
        )
    return "\n".join(lines)


def _format_relations(relations: list[ConceptRelation]) -> str:
    if not relations:
        return ""
    lines = ["## Concept relations"]
    lines.extend(f"- {format_edge(rel)}" for rel in relations)
    return "\n".join(lines)


def _format_style_notes(notes: list[StyleNote]) -> str:
    if not notes:
        return ""
    lines = ["## Style notes"]
    lines.extend(f"- {note.note}" for note in notes)
    return "\n".join(lines)


def _format_due_reviews(reviews: list[DueReview]) -> str:
    if not reviews:
        return ""
    lines = ["## Due reviews"]
    for review in reviews:
        due = review.due.isoformat()
        lines.append(f"- {review.title} (due {due})")
    return "\n".join(lines)


def _required_within_budget(
    pedagogy: str, current_core: str, mastery: str, budget: int = CONTEXT_CHAR_BUDGET
) -> str:
    """Fit required sections under the budget without cutting criteria."""
    required_parts = [part for part in (pedagogy, current_core, mastery) if part]
    required = "\n\n".join(required_parts).strip()
    if len(required) + 1 <= budget:
        return required + "\n"
    without_mastery = "\n\n".join(part for part in (pedagogy, current_core) if part).strip()
    if len(without_mastery) + 1 <= budget:
        return without_mastery + "\n"
    overhead = len(current_core) + 2  # blank line between pedagogy and current
    room = budget - overhead - 1
    if room > 0:
        clipped = pedagogy[:room].rstrip()
        return f"{clipped}\n\n{current_core}\n"
    # Pathological: criteria alone fill the budget. Keep them intact.
    return current_core if current_core.endswith("\n") else current_core + "\n"


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."
