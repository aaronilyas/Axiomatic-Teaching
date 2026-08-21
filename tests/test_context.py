"""Context assembler tests using an in-memory Repository double."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from axiomatic_teaching.config import CONTEXT_CHAR_BUDGET, RELATED_LESSON_CAP
from axiomatic_teaching.context import assemble, kickoff_prompt
from axiomatic_teaching.models import (
    BankedLessonSummary,
    Completion,
    Concept,
    ConceptRelation,
    Criterion,
    CriterionDraft,
    CriterionKind,
    DueReview,
    EvidenceItem,
    FsrsCard,
    GateResult,
    Lesson,
    LessonStatus,
    NewLessonSpec,
    ProposedConcept,
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
        return [
            item
            for item in self.lessons.values()
            if item.status != LessonStatus.DELETED
        ]

    def list_lessons_by_status(self, *statuses: str) -> list[Lesson]:
        wanted = {str(status) for status in statuses}
        return [item for item in self.lessons.values() if str(item.status) in wanted]

    def save_lesson(self, lesson: Lesson) -> Lesson:
        self.lessons[lesson.id] = lesson
        return lesson

    def delete_lesson(self, lesson_id: str) -> Lesson:
        lesson = self.lessons[lesson_id]
        updated = lesson.model_copy(update={"status": LessonStatus.DELETED})
        self.lessons[lesson_id] = updated
        return updated

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
        hidden = {
            item.id
            for item in self.lessons.values()
            if item.status == LessonStatus.DELETED
        }
        return [item for item in self.due_reviews if item.lesson_id not in hidden]

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


def test_deleted_lesson_is_not_listed_as_banked_or_due() -> None:
    repo = FakeRepository()
    doomed = repo.lessons["c1"]
    unique_title = doomed.title
    assert unique_title in assemble(repo, repo.current)
    repo.delete_lesson(doomed.id)
    text = assemble(repo, repo.current)
    assert unique_title not in text
    assert doomed.id not in {item.id for item in repo.list_lessons()}
    assert all(item.lesson_id != doomed.id for item in repo.list_due_reviews())
    assert CRITERION_STATEMENT in text


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
    assert "present_lesson_html" in prompt
    assert "MUST call present_lesson_html" in prompt
    assert "same turn" in prompt
    assert "After they answer, you may call" not in prompt
    assert "Wait for their answer before teaching in this chat" in prompt
    assert "fs/write_text_file" in prompt
    assert "<axiomatic-context>" not in prompt
    assert "min_evidence_chars" not in prompt
    assert "crit-1" not in prompt
    assert "posterior" not in prompt


def test_assemble_includes_html_present_rules() -> None:
    repo = FakeRepository()
    text = assemble(repo, repo.current)
    assert "present_lesson_html" in text
    assert "Initial reading" in text
    assert "not evidence" in text.lower()
    assert "same turn" in text
    assert "Do not wait for the learner's answer before presenting HTML" in text
    assert "fs/write_text_file" in text


def test_kickoff_prompt_restudy_for_completed() -> None:
    repo = FakeRepository()
    completed = repo.lessons["c1"]
    prompt = kickoff_prompt(completed)
    assert "already banked" in prompt
    assert "record_lesson_success" in prompt
    assert "MUST call present_lesson_html" in prompt
    assert "same turn" in prompt
    assert "After they answer, you may call" not in prompt


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


PASSING_TEXT = (
    "Bayes updates a prior with likelihood to get a posterior in probability. "
    "I can walk a simple diagnostic-test example in my own words."
)


def test_sql_assemble_omits_deleted_lesson_and_keeps_graph(tmp_path: Path) -> None:
    from axiomatic_teaching.db.repository import create_repository

    repo = create_repository(tmp_path / "axiomatic.db")
    doomed_title = "UniqueDeletedLessonTitleXYZ"
    keeper_title = "Keeper lesson on posteriors"
    doomed = repo.create_lesson(
        NewLessonSpec(
            title=doomed_title,
            topic="Probability",
            criteria=[
                CriterionDraft(
                    statement="Explain the posterior.",
                    required=True,
                    min_evidence_chars=10,
                    keywords=["posterior"],
                )
            ],
        )
    )
    keeper = repo.create_lesson(
        NewLessonSpec(
            title=keeper_title,
            topic="Probability",
            criteria=[
                CriterionDraft(
                    statement="Apply a posterior update.",
                    required=True,
                    min_evidence_chars=10,
                    keywords=["posterior"],
                )
            ],
        )
    )
    for lesson in (doomed, keeper):
        result = repo.record_success(
            RecordSuccessRequest(
                lesson_id=lesson.id,
                evidence=[
                    EvidenceItem(
                        criterion_id=lesson.criteria[0].id,
                        text=PASSING_TEXT,
                        met=True,
                    )
                ],
                concepts=[ProposedConcept(name="posterior", description="updated belief")],
                style_note="prefer short probes",
            )
        )
        assert result.accepted is True

    past = datetime.now(timezone.utc) - timedelta(days=1)
    card = repo.get_fsrs_card(doomed.id)
    assert card is not None
    repo.upsert_fsrs_card(card.model_copy(update={"due": past}))
    assert any(item.lesson_id == doomed.id for item in repo.list_due_reviews())

    before = assemble(repo, keeper)
    assert doomed_title in before

    deleted = repo.delete_lesson(doomed.id)
    assert deleted.status == LessonStatus.DELETED
    assert repo.get_completion(doomed.id) is not None
    names = {c.name for c in repo.list_concepts()}
    assert "posterior" in names
    assert repo.list_style_notes()
    assert all(item.id != doomed.id for item in repo.list_banked_summaries())
    assert all(item.lesson_id != doomed.id for item in repo.list_due_reviews())

    keeper = repo.get_lesson(keeper.id)
    assert keeper is not None
    after = assemble(repo, keeper)
    assert doomed_title not in after
    assert keeper_title in after
    assert "prefer short probes" in after
