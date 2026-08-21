"""Graph helpers over the Repository protocol (no raw SQL / ORM coupling)."""

from __future__ import annotations

from axiomatic_teaching.config import RELATED_LESSON_CAP, RELATION_CAP
from axiomatic_teaching.db.repository import Repository
from axiomatic_teaching.models import (
    BankedLessonSummary,
    ConceptRelation,
    Lesson,
    LessonStatus,
)


def format_edge(rel: ConceptRelation) -> str:
    """Render a relation as ``A —prerequisite→ B``."""
    left = (rel.from_name or "").strip() or rel.from_concept_id
    right = (rel.to_name or "").strip() or rel.to_concept_id
    return f"{left} —{rel.relation}→ {right}"


def relatedness_score(
    current: Lesson,
    other: BankedLessonSummary,
    shared_concepts: set[str],
) -> int:
    """Rank related banked lessons.

    Higher is better. Order of importance:
    1. shared concepts (direct names and 1-hop neighbors)
    2. tag overlap
    3. topic equality, then containment
    4. recency of completion
    """
    shared = len(shared_concepts)
    current_tags = {tag.strip().lower() for tag in current.tags if tag.strip()}
    other_tags = {tag.strip().lower() for tag in other.tags if tag.strip()}
    tag_overlap = len(current_tags & other_tags)

    current_topic = current.topic.strip().lower()
    other_topic = other.topic.strip().lower()
    if current_topic and other_topic and current_topic == other_topic:
        topic_points = 2
    elif current_topic and other_topic and (
        current_topic in other_topic or other_topic in current_topic
    ):
        topic_points = 1
    else:
        topic_points = 0

    recency = 0
    if other.completed_at is not None:
        recency = int(other.completed_at.timestamp())

    # Packed int so a single descending sort preserves the four-tier ranking.
    # recency is unix seconds (~1.7e9); keep it below the topic place value.
    return shared * 10**13 + tag_overlap * 10**11 + topic_points * 10**10 + recency


def concept_names_for(repository: Repository, lesson_id: str) -> set[str]:
    """Concept names attached to a lesson; empty if the repository call fails."""
    names: set[str] = set()
    try:
        concepts = repository.list_concepts(lesson_id) or []
    except Exception:
        concepts = []
    for concept in concepts:
        name = (concept.name or "").strip()
        if name:
            names.add(name)
    if names:
        return names
    try:
        all_concepts = repository.list_concepts() or []
    except Exception:
        return names
    for concept in all_concepts:
        if concept.source_lesson_id == lesson_id:
            name = (concept.name or "").strip()
            if name:
                names.add(name)
    return names


def concept_ids_for(repository: Repository, lesson_id: str) -> list[str]:
    try:
        concepts = repository.list_concepts(lesson_id) or []
    except Exception:
        return []
    return [concept.id for concept in concepts if concept.id]


def neighbor_concept_names(
    repository: Repository,
    concept_ids: list[str],
    current_names: set[str],
) -> set[str]:
    """Names of concepts one hop away via ``list_relations``."""
    if not concept_ids:
        return set()
    try:
        relations = repository.list_relations(list(concept_ids)) or []
    except Exception:
        return set()
    names: set[str] = set()
    current_lower = {name.lower() for name in current_names}
    for rel in relations:
        for name in (rel.from_name, rel.to_name):
            text = (name or "").strip()
            if text and text.lower() not in current_lower:
                names.add(text)
    return names


def shared_concepts_with(
    other: BankedLessonSummary,
    current_names: set[str],
    neighbor_names: set[str],
    repository: Repository | None = None,
) -> set[str]:
    """Intersection of another lesson's concepts with current names or neighbors."""
    other_names = {(name or "").strip() for name in other.concepts if (name or "").strip()}
    if not other_names and repository is not None:
        other_names = concept_names_for(repository, other.id)
    if not other_names:
        return set()
    current_lower = {name.lower(): name for name in current_names}
    neighbor_lower = {name.lower(): name for name in neighbor_names}
    shared: set[str] = set()
    for name in other_names:
        key = name.lower()
        if key in current_lower or key in neighbor_lower:
            shared.add(name)
    return shared


def incomplete_lesson_ids(repository: Repository) -> set[str]:
    """Ids that must never appear as banked context."""
    incomplete: set[str] = set()
    try:
        lessons = repository.list_lessons() or []
        for lesson in lessons:
            if lesson.status != LessonStatus.COMPLETED:
                incomplete.add(lesson.id)
        return incomplete
    except Exception:
        pass
    try:
        for lesson in repository.list_lessons_by_status(
            LessonStatus.DRAFT,
            LessonStatus.ACTIVE,
            LessonStatus.ARCHIVED,
            LessonStatus.DELETED,
        ) or []:
            incomplete.add(lesson.id)
    except Exception:
        return incomplete
    return incomplete


def deleted_lesson_ids(repository: Repository) -> set[str]:
    """Ids of soft-deleted lessons; empty if the repository call fails."""
    try:
        found = repository.list_lessons_by_status(LessonStatus.DELETED) or []
    except Exception:
        return set()
    return {item.id for item in found if item.id}


def banked_summaries_for(
    repository: Repository,
    current_id: str,
) -> list[BankedLessonSummary]:
    """Completed/banked lessons only, excluding the current lesson."""
    try:
        summaries = list(repository.list_banked_summaries() or [])
    except Exception:
        summaries = []
        try:
            completed = repository.list_lessons_by_status(LessonStatus.COMPLETED) or []
            summaries = [_summary_from_lesson(item) for item in completed]
        except Exception:
            summaries = []

    blocked = incomplete_lesson_ids(repository)
    blocked.add(current_id)
    blocked.update(deleted_lesson_ids(repository))
    return [item for item in summaries if item.id not in blocked]


def select_related_banked(
    repository: Repository,
    lesson: Lesson,
    *,
    cap: int = RELATED_LESSON_CAP,
) -> list[BankedLessonSummary]:
    """Top related BANKED lessons using the four-tier ranking."""
    banked = banked_summaries_for(repository, lesson.id)
    if not banked:
        return []
    current_names = concept_names_for(repository, lesson.id)
    neighbor_names = neighbor_concept_names(
        repository,
        concept_ids_for(repository, lesson.id),
        current_names,
    )
    scored: list[tuple[int, BankedLessonSummary]] = []
    for other in banked:
        shared = shared_concepts_with(other, current_names, neighbor_names, repository)
        scored.append((relatedness_score(lesson, other, shared), other))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:cap]]


def one_hop_edges(
    repository: Repository,
    lesson_id: str,
    *,
    cap: int = RELATION_CAP,
) -> list[ConceptRelation]:
    """Up to ``cap`` 1-hop concept relations for a lesson."""
    relations: list[ConceptRelation] = []
    try:
        relations = list(repository.one_hop_relations(lesson_id) or [])
    except Exception:
        relations = []
    if not relations:
        ids = concept_ids_for(repository, lesson_id)
        if ids:
            try:
                relations = list(repository.list_relations(ids) or [])
            except Exception:
                relations = []
    unique: list[ConceptRelation] = []
    seen: set[str] = set()
    for rel in relations:
        if rel.id in seen:
            continue
        seen.add(rel.id)
        unique.append(rel)
        if len(unique) >= cap:
            break
    return unique


def _summary_from_lesson(lesson: Lesson) -> BankedLessonSummary:
    return BankedLessonSummary(
        id=lesson.id,
        title=lesson.title,
        topic=lesson.topic,
        description=lesson.description,
        concepts=[],
        completed_at=lesson.completed_at,
        tags=list(lesson.tags),
    )


__all__ = [
    "banked_summaries_for",
    "concept_ids_for",
    "concept_names_for",
    "deleted_lesson_ids",
    "format_edge",
    "incomplete_lesson_ids",
    "neighbor_concept_names",
    "one_hop_edges",
    "relatedness_score",
    "select_related_banked",
    "shared_concepts_with",
]
