"""Context assembler tests using an in-memory Repository double."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from axiomatic_teaching.config import CONTEXT_CHAR_BUDGET, RELATED_LESSON_CAP
from axiomatic_teaching.context import assemble, kickoff_prompt
from axiomatic_teaching.models import (
    BankedLessonSummary,
    Completion,
    Concept,
    ConceptRelation,
    Criterion,
    CriterionKind,
    DueReview,
    FsrsCard,
    GateResult,
    Lesson,
    LessonStatus,
    NewLessonSpec,
    RecordSuccessRequest,
    RelationType,
    StyleNote,
)


NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
CRITERION_STATEMENT = "Explain Bayes rule using likelihood, prior, and posterior."
CURRENT_TITLE = "Bayes rule in practice"
INCOMPLETE_TITLE = "UNBANKED draft on Bayes"


def _dt(days_ago: int) -> datetime:
    return NOW - timedelta(days=days_ago)


def _lesson(
    lesson_id: str,
    title: str,
    *,
    topic: str,
    status: LessonStatus,
    tags: list[str],
    description: str = "",
    completed_at: datetime | None = None,
    criteria: list[Criterion] | None = None,
) -> Lesson:
    return Lesson(
        id=lesson_id,
        title=title,
        topic=topic,
        description=description,
        success_description="Learner can use the idea independently.",
        status=status,
        tags=tags,
        created_at=_dt(30),
        updated_at=_dt(1),
        completed_at=completed_at,
        criteria=criteria or [],
    )


class FakeRepository:
    """In-memory Repository double. Does not depend on SqlRepository."""

    def __init__(self) -> None:
        long_desc = (
            "This banked lesson description is intentionally verbose so the assembler "
            "must honor CONTEXT_CHAR_BUDGET by truncating related descriptions before "
            "dropping style notes or relations. " * 8
        )
        self.current = _lesson(
            "current",
            CURRENT_TITLE,
            topic="Probability",
            status=LessonStatus.ACTIVE,
            tags=["bayes", "stats"],
            description="Apply Bayes rule to a diagnostic test.",
            criteria=[
                Criterion(
                    id="crit-1",
                    lesson_id="current",
                    kind=CriterionKind.EXPLAIN,
                    statement=CRITERION_STATEMENT,
                    required=True,
                    min_evidence_chars=40,
                    keywords=["posterior", "likelihood"],
                    sort_order=0,
                ),
                Criterion(
                    id="crit-2",
                    lesson_id="current",
                    kind=CriterionKind.APPLY,
                    statement="Compute a posterior from a prior and a likelihood.",
                    required=True,
                    min_evidence_chars=40,
                    keywords=["compute"],
                    sort_order=1,
                ),
            ],
        )
        completed = [
            _lesson(
                "c1",
                "Completed posterior update",
                topic="Probability",
                status=LessonStatus.COMPLETED,
                tags=["bayes", "stats"],
                description=long_desc,
                completed_at=_dt(1),
            ),
            _lesson(
                "c2",
                "Completed likelihood functions",
                topic="Statistics",
                status=LessonStatus.COMPLETED,
                tags=["modeling"],
                description=long_desc,
                completed_at=_dt(2),
            ),
            _lesson(
                "c3",
                "Completed tagged diagnostics",
                topic="Probability",
                status=LessonStatus.COMPLETED,
                tags=["bayes", "stats"],
                description=long_desc,
                completed_at=_dt(3),
            ),
            _lesson(
                "c4",
                "Completed tag-only inference",
                topic="Machine learning",
                status=LessonStatus.COMPLETED,
                tags=["stats"],
                description=long_desc,
                completed_at=_dt(4),
            ),
            _lesson(
                "c5",
                "Completed Probability basics",
                topic="Probability basics",
                status=LessonStatus.COMPLETED,
                tags=["intro"],
                description=long_desc,
                completed_at=_dt(5),
            ),
            _lesson(
                "c6",
                "Completed villanelle meter",
                topic="Poetry",
                status=LessonStatus.COMPLETED,
                tags=["verse"],
                description=long_desc,
                completed_at=_dt(400),
            ),
        ]
        self.incomplete = _lesson(
            "draft-1",
            INCOMPLETE_TITLE,
            topic="Probability",
            status=LessonStatus.DRAFT,
            tags=["bayes", "stats"],
            description="Should never appear as banked context.",
        )
        self.lessons: dict[str, Lesson] = {
            self.current.id: self.current,
            self.incomplete.id: self.incomplete,
            **{item.id: item for item in completed},
        }
        self.concepts = [
            Concept(id="k-post", name="posterior", source_lesson_id="current"),
            Concept(id="k-like", name="likelihood", source_lesson_id="current"),
            Concept(id="k-post-c1", name="posterior", source_lesson_id="c1"),
            Concept(id="k-like-c1", name="likelihood", source_lesson_id="c1"),
            Concept(id="k-post-c2", name="posterior", source_lesson_id="c2"),
            Concept(id="k-sonnet", name="sonnet", source_lesson_id="c6"),
            Concept(id="k-draft", name="posterior", source_lesson_id="draft-1"),
        ]
        self.relations = [
            ConceptRelation(
                id="r1",
                from_concept_id="k-like",
                to_concept_id="k-post",
                from_name="likelihood",
                to_name="posterior",
                relation=RelationType.PREREQUISITE,
                source_lesson_id="current",
            ),
            ConceptRelation(
                id="r2",
                from_concept_id="k-post",
                to_concept_id="k-post-c1",
                from_name="posterior",
                to_name="posterior",
                relation=RelationType.RELATED,
                source_lesson_id="c1",
            ),
        ]
        self.style_notes = [
            StyleNote(
                id=f"s{i}",
                lesson_id="c1",
                note=f"Style note {i}: prefer short probes.",
                created_at=_dt(i),
            )
            for i in range(1, 8)
        ]
        self.due_reviews = [
            DueReview(lesson_id=f"c{i}", title=f"Review {i}", topic="Probability", due=_dt(-i))
            for i in range(1, 8)
        ]
        self.concepts_by_lesson = {
            "current": ["posterior", "likelihood"],
            "c1": ["posterior", "likelihood"],
            "c2": ["posterior"],
            "c3": [],
            "c4": [],
            "c5": [],
            "c6": ["sonnet"],
            "draft-1": ["posterior"],
        }

    def create_lesson(self, spec: NewLessonSpec) -> Lesson:
        raise NotImplementedError

    def get_lesson(self, lesson_id: str) -> Lesson | None:
        return self.lessons.get(lesson_id)

    def list_lessons(self) -> list[Lesson]:
        return list(self.lessons.values())

    def list_lessons_by_status(self, *statuses: str) -> list[Lesson]:
        wanted = {str(status) for status in statuses}
        return [item for item in self.lessons.values() if str(item.status) in wanted]

    def save_lesson(self, lesson: Lesson) -> Lesson:
        self.lessons[lesson.id] = lesson
        return lesson

    def list_criteria(self, lesson_id: str) -> list[Criterion]:
        lesson = self.lessons.get(lesson_id)
        return list(lesson.criteria) if lesson else []

    def record_success(self, request: RecordSuccessRequest) -> GateResult:
        raise NotImplementedError

    def get_completion(self, lesson_id: str) -> Completion | None:
        return None

    def list_completions(self) -> list[Completion]:
        return []

    def list_banked_summaries(self) -> list[BankedLessonSummary]:
        summaries: list[BankedLessonSummary] = []
        for lesson in self.lessons.values():
            if lesson.status != LessonStatus.COMPLETED:
                continue
            summaries.append(
                BankedLessonSummary(
                    id=lesson.id,
                    title=lesson.title,
                    topic=lesson.topic,
                    description=lesson.description,
                    concepts=list(self.concepts_by_lesson.get(lesson.id, [])),
                    completed_at=lesson.completed_at,
                    tags=list(lesson.tags),
                )
            )
        return summaries

    def list_style_notes(self, limit: int = 5) -> list[StyleNote]:
        return self.style_notes[:limit]

    def list_concepts(self, lesson_id: str | None = None) -> list[Concept]:
        if lesson_id is None:
            return list(self.concepts)
        return [item for item in self.concepts if item.source_lesson_id == lesson_id]

    def list_relations(self, concept_ids: list[str] | None = None) -> list[ConceptRelation]:
        if not concept_ids:
            return list(self.relations)
        wanted = set(concept_ids)
        return [
            rel
            for rel in self.relations
            if rel.from_concept_id in wanted or rel.to_concept_id in wanted
        ]

    def one_hop_relations(self, lesson_id: str) -> list[ConceptRelation]:
        ids = {item.id for item in self.list_concepts(lesson_id)}
        return self.list_relations(list(ids))

    def upsert_fsrs_card(self, card: FsrsCard) -> FsrsCard:
        return card

    def get_fsrs_card(self, lesson_id: str) -> FsrsCard | None:
        return None

    def list_due_reviews(self, now: datetime | None = None) -> list[DueReview]:
        return list(self.due_reviews)

    def add_review(self, lesson_id: str, rating: str, scheduled_days: float) -> None:
        return None

    def set_last_session(self, lesson_id: str, session_id: str) -> None:
        return None

    def record_acp_session(
        self,
        lesson_id: str,
        acp_session_id: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        stop_reason: str | None = None,
    ) -> None:
        return None


def _related_section(text: str) -> str:
    marker = "## Related banked lessons"
    if marker not in text:
        return ""
    section = text.split(marker, 1)[1]
    nxt = section.find("\n## ")
    if nxt >= 0:
        section = section[:nxt]
    return section


def test_assemble_includes_current_criteria() -> None:
    repo = FakeRepository()
    text = assemble(repo, repo.current)
    assert CRITERION_STATEMENT in text
    assert "crit-1" in text
    assert "min_evidence_chars" in text


def test_assemble_caps_related_lessons_at_five() -> None:
    repo = FakeRepository()
    text = assemble(repo, repo.current)
    completed_titles = [
        lesson.title
        for lesson in repo.lessons.values()
        if lesson.status == LessonStatus.COMPLETED
    ]
    related = _related_section(text)
    present = [title for title in completed_titles if title in related]
    assert len(completed_titles) == 6
    assert len(present) <= RELATED_LESSON_CAP
    assert "Completed posterior update" in related
    assert "Completed villanelle meter" not in related


def test_incomplete_lessons_are_not_listed_as_banked() -> None:
    repo = FakeRepository()
    text = assemble(repo, repo.current)
    assert INCOMPLETE_TITLE not in text
    assert "UNBANKED" not in text


def test_assemble_respects_char_budget() -> None:
    repo = FakeRepository()
    text = assemble(repo, repo.current)
    assert len(text) <= CONTEXT_CHAR_BUDGET


def test_kickoff_prompt_mentions_title() -> None:
    repo = FakeRepository()
    prompt = kickoff_prompt(repo.current)
    assert CURRENT_TITLE in prompt
    assert "diagnostic question" in prompt
    assert "already sees" in prompt


def test_kickoff_prompt_restudy_for_completed() -> None:
    repo = FakeRepository()
    completed = repo.lessons["c1"]
    prompt = kickoff_prompt(completed)
    assert "already banked" in prompt
    assert "record_lesson_success" in prompt


def test_current_description_is_truncated() -> None:
    repo = FakeRepository()
    repo.current.description = "D" * 800
    repo.current.success_description = "S" * 800
    text = assemble(repo, repo.current)
    assert "D" * 241 not in text
    assert "S" * 241 not in text
    assert CRITERION_STATEMENT in text


def test_assemble_survives_empty_repository_methods() -> None:
    class EmptyRepo(FakeRepository):
        def list_banked_summaries(self) -> list[BankedLessonSummary]:
            raise RuntimeError("boom")

        def list_concepts(self, lesson_id: str | None = None) -> list[Concept]:
            raise RuntimeError("boom")

        def list_relations(self, concept_ids: list[str] | None = None) -> list[ConceptRelation]:
            raise RuntimeError("boom")

        def one_hop_relations(self, lesson_id: str) -> list[ConceptRelation]:
            raise RuntimeError("boom")

        def list_style_notes(self, limit: int = 5) -> list[StyleNote]:
            raise RuntimeError("boom")

        def list_due_reviews(self, now: datetime | None = None) -> list[DueReview]:
            raise RuntimeError("boom")

        def list_lessons(self) -> list[Lesson]:
            raise RuntimeError("boom")

    repo = EmptyRepo()
    text = assemble(repo, repo.current)
    assert CRITERION_STATEMENT in text
    assert "Pedagogy rules" in text or "zone of proximal development" in text
    assert CURRENT_TITLE in text
    assert len(text) <= CONTEXT_CHAR_BUDGET
