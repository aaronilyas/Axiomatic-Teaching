"""Repository protocol and factory for the SQLite implementation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from axiomatic_teaching.models import (
    BankedLessonSummary,
    Completion,
    Concept,
    ConceptRelation,
    Criterion,
    DueReview,
    FsrsCard,
    GateResult,
    Lesson,
    NewLessonSpec,
    RecordSuccessRequest,
    StyleNote,
)

if TYPE_CHECKING:
    from axiomatic_teaching.db.sql_repository import SqlRepository


class Repository(Protocol):
    def create_lesson(self, spec: NewLessonSpec) -> Lesson: ...
    def get_lesson(self, lesson_id: str) -> Lesson | None: ...
    def list_lessons(self) -> list[Lesson]: ...
    def list_lessons_by_status(self, *statuses: str) -> list[Lesson]: ...
    def save_lesson(self, lesson: Lesson) -> Lesson: ...
    def list_criteria(self, lesson_id: str) -> list[Criterion]: ...

    def record_success(self, request: RecordSuccessRequest) -> GateResult:
        """Run the success gate and persist only on pass. Sole writer of completions."""
        ...

    def get_completion(self, lesson_id: str) -> Completion | None: ...
    def list_completions(self) -> list[Completion]: ...
    def list_banked_summaries(self) -> list[BankedLessonSummary]: ...
    def list_style_notes(self, limit: int = 5) -> list[StyleNote]: ...
    def list_concepts(self, lesson_id: str | None = None) -> list[Concept]: ...
    def list_relations(self, concept_ids: list[str] | None = None) -> list[ConceptRelation]: ...
    def one_hop_relations(self, lesson_id: str) -> list[ConceptRelation]: ...

    def upsert_fsrs_card(self, card: FsrsCard) -> FsrsCard: ...
    def get_fsrs_card(self, lesson_id: str) -> FsrsCard | None: ...
    def list_due_reviews(self, now: datetime | None = None) -> list[DueReview]: ...
    def add_review(self, lesson_id: str, rating: str, scheduled_days: float) -> None: ...

    def set_last_session(self, lesson_id: str, session_id: str) -> None: ...
    def record_acp_session(
        self,
        lesson_id: str,
        acp_session_id: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        stop_reason: str | None = None,
    ) -> None: ...


def create_repository(db_path: Path) -> SqlRepository:
    from axiomatic_teaching.db.sql_repository import SqlRepository

    return SqlRepository(db_path)
