"""SQLAlchemy implementation of the Repository protocol."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload

from axiomatic_teaching.db.engine import init_engine, session_scope
from axiomatic_teaching.db.orm import (
    AcpSessionRow,
    CompletionRow,
    ConceptRelationRow,
    ConceptRow,
    FsrsCardRow,
    GateAttemptRow,
    LessonConceptRow,
    LessonRow,
    ReviewRow,
    StyleNoteRow,
    SuccessCriterionRow,
)
from axiomatic_teaching.gate.success import evaluate
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
    Rating,
    RecordSuccessRequest,
    RelationType,
    StyleNote,
    UnmetCriterion,
)
from axiomatic_teaching.schedule.fsrs import new_card, review_card


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    return json.loads(raw)


def _criterion_to_model(row: SuccessCriterionRow) -> Criterion:
    return Criterion(
        id=row.id,
        lesson_id=row.lesson_id,
        kind=CriterionKind(row.kind),
        statement=row.statement,
        required=row.required,
        min_evidence_chars=row.min_evidence_chars,
        keywords=list(_loads(row.keywords_json, [])),
        sort_order=row.sort_order,
    )


def _lesson_to_model(row: LessonRow) -> Lesson:
    criteria = [_criterion_to_model(c) for c in sorted(row.criteria, key=lambda c: c.sort_order)]
    return Lesson(
        id=row.id,
        title=row.title,
        topic=row.topic,
        description=row.description,
        success_description=row.success_description,
        status=LessonStatus(row.status),
        tags=list(_loads(row.tags_json, [])),
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        last_session_id=row.last_session_id,
        criteria=criteria,
    )


def _completion_to_model(row: CompletionRow) -> Completion:
    evidence = _loads(row.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {"items": evidence}
    return Completion(
        id=row.id,
        lesson_id=row.lesson_id,
        evidence=evidence,
        notes=row.notes,
        recorded_at=row.recorded_at,
        acp_session_id=row.acp_session_id,
        source=row.source,
    )


def _style_to_model(row: StyleNoteRow) -> StyleNote:
    return StyleNote(
        id=row.id,
        lesson_id=row.lesson_id,
        note=row.note,
        created_at=row.created_at,
    )


def _concept_to_model(row: ConceptRow) -> Concept:
    return Concept(
        id=row.id,
        name=row.name,
        description=row.description,
        source_lesson_id=row.source_lesson_id,
    )


def _card_to_model(row: FsrsCardRow) -> FsrsCard:
    return FsrsCard(
        lesson_id=row.lesson_id,
        due=row.due,
        stability=row.stability,
        difficulty=row.difficulty,
        elapsed_days=row.elapsed_days,
        scheduled_days=row.scheduled_days,
        reps=row.reps,
        lapses=row.lapses,
        state=row.state,
        last_review=row.last_review,
        card_json=row.card_json,
    )


def _apply_card_row(row: FsrsCardRow, card: FsrsCard) -> None:
    row.due = card.due
    row.stability = card.stability
    row.difficulty = card.difficulty
    row.elapsed_days = card.elapsed_days
    row.scheduled_days = card.scheduled_days
    row.reps = card.reps
    row.lapses = card.lapses
    row.state = card.state
    row.last_review = card.last_review
    row.card_json = card.card_json


class SqlRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.engine = init_engine(self.db_path)

    def create_lesson(self, spec: NewLessonSpec) -> Lesson:
        if not any(c.required for c in spec.criteria):
            raise ValueError("at least one required criterion is required")
        now = _utcnow()
        lesson_id = _new_id()
        with session_scope(self.engine) as session:
            row = LessonRow(
                id=lesson_id,
                title=spec.title,
                topic=spec.topic,
                description=spec.description,
                success_description=spec.success_description,
                status=LessonStatus.ACTIVE.value,
                tags_json=_dumps(list(spec.tags)),
                created_at=now,
                updated_at=now,
                completed_at=None,
                last_session_id=None,
            )
            session.add(row)
            for index, draft in enumerate(spec.criteria):
                session.add(
                    SuccessCriterionRow(
                        id=_new_id(),
                        lesson_id=lesson_id,
                        kind=draft.kind.value,
                        statement=draft.statement,
                        required=draft.required,
                        min_evidence_chars=draft.min_evidence_chars,
                        keywords_json=_dumps(list(draft.keywords)),
                        sort_order=index,
                    )
                )
            session.flush()
            loaded = session.scalar(
                select(LessonRow)
                .options(selectinload(LessonRow.criteria))
                .where(LessonRow.id == lesson_id)
            )
            assert loaded is not None
            return _lesson_to_model(loaded)

    def get_lesson(self, lesson_id: str) -> Lesson | None:
        with session_scope(self.engine) as session:
            row = session.scalar(
                select(LessonRow)
                .options(selectinload(LessonRow.criteria))
                .where(LessonRow.id == lesson_id)
            )
            if row is None:
                return None
            return _lesson_to_model(row)

    def list_lessons(self) -> list[Lesson]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(LessonRow)
                .options(selectinload(LessonRow.criteria))
                .order_by(LessonRow.updated_at.desc())
            ).all()
            return [_lesson_to_model(row) for row in rows]

    def list_lessons_by_status(self, *statuses: str) -> list[Lesson]:
        if not statuses:
            return []
        values = [s.value if isinstance(s, LessonStatus) else str(s) for s in statuses]
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(LessonRow)
                .options(selectinload(LessonRow.criteria))
                .where(LessonRow.status.in_(values))
                .order_by(LessonRow.updated_at.desc())
            ).all()
            return [_lesson_to_model(row) for row in rows]

    def save_lesson(self, lesson: Lesson) -> Lesson:
        now = _utcnow()
        with session_scope(self.engine) as session:
            row = session.get(LessonRow, lesson.id)
            if row is None:
                row = LessonRow(
                    id=lesson.id,
                    title=lesson.title,
                    topic=lesson.topic,
                    description=lesson.description,
                    success_description=lesson.success_description,
                    status=lesson.status.value,
                    tags_json=_dumps(list(lesson.tags)),
                    created_at=lesson.created_at,
                    updated_at=now,
                    completed_at=lesson.completed_at,
                    last_session_id=lesson.last_session_id,
                )
                session.add(row)
            else:
                row.title = lesson.title
                row.topic = lesson.topic
                row.description = lesson.description
                row.success_description = lesson.success_description
                row.status = lesson.status.value
                row.tags_json = _dumps(list(lesson.tags))
                row.updated_at = now
                row.completed_at = lesson.completed_at
                row.last_session_id = lesson.last_session_id
            session.execute(
                delete(SuccessCriterionRow).where(SuccessCriterionRow.lesson_id == lesson.id)
            )
            session.flush()
            for criterion in lesson.criteria:
                session.add(
                    SuccessCriterionRow(
                        id=criterion.id or _new_id(),
                        lesson_id=lesson.id,
                        kind=criterion.kind.value,
                        statement=criterion.statement,
                        required=criterion.required,
                        min_evidence_chars=criterion.min_evidence_chars,
                        keywords_json=_dumps(list(criterion.keywords)),
                        sort_order=criterion.sort_order,
                    )
                )
            session.flush()
            session.expire(row, ["criteria"])
            loaded = session.scalar(
                select(LessonRow)
                .options(selectinload(LessonRow.criteria))
                .where(LessonRow.id == lesson.id)
            )
            assert loaded is not None
            return _lesson_to_model(loaded)

    def list_criteria(self, lesson_id: str) -> list[Criterion]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(SuccessCriterionRow)
                .where(SuccessCriterionRow.lesson_id == lesson_id)
                .order_by(SuccessCriterionRow.sort_order)
            ).all()
            return [_criterion_to_model(row) for row in rows]

    def record_success(self, request: RecordSuccessRequest) -> GateResult:
        """Evaluate the gate, always log the attempt, persist side effects only on pass."""
        with session_scope(self.engine) as session:
            lesson_row = session.scalar(
                select(LessonRow)
                .options(selectinload(LessonRow.criteria))
                .where(LessonRow.id == request.lesson_id)
            )
            if lesson_row is None:
                return GateResult(
                    accepted=False,
                    lesson_id=request.lesson_id,
                    unmet=[UnmetCriterion(reason="lesson not found")],
                    message="Lesson not found.",
                )

            lesson = _lesson_to_model(lesson_row)
            result = evaluate(lesson, request)

            existing = session.scalar(
                select(CompletionRow).where(CompletionRow.lesson_id == request.lesson_id)
            )
            if existing is not None:
                result.accepted = True
                result.already_banked = True
                result.unmet = []
                result.completion_id = existing.id
                result.message = "Lesson already banked."

            attempt = GateAttemptRow(
                id=_new_id(),
                lesson_id=request.lesson_id,
                accepted=result.accepted,
                payload_json=request.model_dump_json(),
                result_json=result.model_dump_json(),
                created_at=_utcnow(),
            )
            session.add(attempt)

            if result.already_banked or not result.accepted:
                return result

            now = _utcnow()
            completion_id = _new_id()
            evidence_payload = {
                item.criterion_id: {"text": item.text, "met": item.met}
                for item in request.evidence
            }
            session.add(
                CompletionRow(
                    id=completion_id,
                    lesson_id=request.lesson_id,
                    evidence_json=_dumps(evidence_payload),
                    notes=request.notes,
                    unmet_json=_dumps([u.model_dump(mode="json") for u in result.unmet]),
                    recorded_at=now,
                    acp_session_id=request.acp_session_id,
                    source="record_lesson_success",
                )
            )
            lesson_row.status = LessonStatus.COMPLETED.value
            lesson_row.completed_at = now
            lesson_row.updated_at = now

            self._upsert_graph(session, request)

            note = request.style_note.strip()
            if note:
                session.add(
                    StyleNoteRow(
                        id=_new_id(),
                        lesson_id=request.lesson_id,
                        note=note,
                        created_at=now,
                    )
                )

            fsrs = review_card(new_card(), Rating.GOOD).model_copy(
                update={"lesson_id": request.lesson_id}
            )
            card_row = session.get(FsrsCardRow, request.lesson_id)
            if card_row is None:
                card_row = FsrsCardRow(lesson_id=request.lesson_id)
                session.add(card_row)
            _apply_card_row(card_row, fsrs)

            result.completion_id = completion_id
            result.message = result.message or "Lesson banked."
            attempt.result_json = result.model_dump_json()
            return result

    def _upsert_graph(self, session, request: RecordSuccessRequest) -> None:
        names: dict[str, str] = {}
        for proposed in request.concepts:
            name = proposed.name.strip()
            if not name:
                continue
            names[name] = self._get_or_create_concept(
                session,
                name=name,
                description=proposed.description,
                source_lesson_id=request.lesson_id,
            )
            self._link_lesson_concept(session, request.lesson_id, names[name])

        for rel in request.relations:
            from_name = rel.from_name.strip()
            to_name = rel.to_name.strip()
            if not from_name or not to_name:
                continue
            from_id = names.get(from_name) or self._get_or_create_concept(
                session,
                name=from_name,
                description="",
                source_lesson_id=request.lesson_id,
            )
            to_id = names.get(to_name) or self._get_or_create_concept(
                session,
                name=to_name,
                description="",
                source_lesson_id=request.lesson_id,
            )
            names[from_name] = from_id
            names[to_name] = to_id
            self._link_lesson_concept(session, request.lesson_id, from_id)
            self._link_lesson_concept(session, request.lesson_id, to_id)
            existing = session.scalar(
                select(ConceptRelationRow).where(
                    ConceptRelationRow.from_concept_id == from_id,
                    ConceptRelationRow.to_concept_id == to_id,
                    ConceptRelationRow.relation == rel.relation.value,
                )
            )
            if existing is None:
                session.add(
                    ConceptRelationRow(
                        id=_new_id(),
                        from_concept_id=from_id,
                        to_concept_id=to_id,
                        relation=rel.relation.value,
                        source_lesson_id=request.lesson_id,
                        notes=rel.notes,
                    )
                )

    def _get_or_create_concept(
        self,
        session,
        *,
        name: str,
        description: str,
        source_lesson_id: str,
    ) -> str:
        row = session.scalar(select(ConceptRow).where(ConceptRow.name == name))
        if row is None:
            row = ConceptRow(
                id=_new_id(),
                name=name,
                description=description,
                source_lesson_id=source_lesson_id,
            )
            session.add(row)
            session.flush()
            return row.id
        if description:
            row.description = description
        return row.id

    def _link_lesson_concept(self, session, lesson_id: str, concept_id: str) -> None:
        existing = session.get(LessonConceptRow, (lesson_id, concept_id))
        if existing is None:
            session.add(LessonConceptRow(lesson_id=lesson_id, concept_id=concept_id))

    def get_completion(self, lesson_id: str) -> Completion | None:
        with session_scope(self.engine) as session:
            row = session.scalar(
                select(CompletionRow).where(CompletionRow.lesson_id == lesson_id)
            )
            if row is None:
                return None
            return _completion_to_model(row)

    def list_completions(self) -> list[Completion]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(CompletionRow).order_by(CompletionRow.recorded_at.desc())
            ).all()
            return [_completion_to_model(row) for row in rows]

    def list_banked_summaries(self) -> list[BankedLessonSummary]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(LessonRow)
                .options(selectinload(LessonRow.concepts))
                .where(LessonRow.status == LessonStatus.COMPLETED.value)
                .order_by(LessonRow.completed_at.desc())
            ).all()
            summaries: list[BankedLessonSummary] = []
            for row in rows:
                summaries.append(
                    BankedLessonSummary(
                        id=row.id,
                        title=row.title,
                        topic=row.topic,
                        description=row.description,
                        concepts=[c.name for c in row.concepts],
                        completed_at=row.completed_at,
                        tags=list(_loads(row.tags_json, [])),
                    )
                )
            return summaries

    def list_style_notes(self, limit: int = 5) -> list[StyleNote]:
        with session_scope(self.engine) as session:
            rows = session.scalars(
                select(StyleNoteRow)
                .order_by(StyleNoteRow.created_at.desc())
                .limit(limit)
            ).all()
            return [_style_to_model(row) for row in rows]

    def list_concepts(self, lesson_id: str | None = None) -> list[Concept]:
        with session_scope(self.engine) as session:
            stmt = select(ConceptRow).order_by(ConceptRow.name)
            if lesson_id is not None:
                stmt = (
                    select(ConceptRow)
                    .join(
                        LessonConceptRow,
                        LessonConceptRow.concept_id == ConceptRow.id,
                    )
                    .where(LessonConceptRow.lesson_id == lesson_id)
                    .order_by(ConceptRow.name)
                )
            rows = session.scalars(stmt).all()
            return [_concept_to_model(row) for row in rows]

    def list_relations(
        self, concept_ids: list[str] | None = None
    ) -> list[ConceptRelation]:
        with session_scope(self.engine) as session:
            stmt = select(ConceptRelationRow)
            if concept_ids:
                stmt = stmt.where(
                    or_(
                        ConceptRelationRow.from_concept_id.in_(concept_ids),
                        ConceptRelationRow.to_concept_id.in_(concept_ids),
                    )
                )
            rows = session.scalars(stmt).all()
            names = {
                c.id: c.name
                for c in session.scalars(select(ConceptRow)).all()
            }
            return [
                ConceptRelation(
                    id=row.id,
                    from_concept_id=row.from_concept_id,
                    to_concept_id=row.to_concept_id,
                    from_name=names.get(row.from_concept_id, ""),
                    to_name=names.get(row.to_concept_id, ""),
                    relation=RelationType(row.relation),
                    source_lesson_id=row.source_lesson_id,
                    notes=row.notes,
                )
                for row in rows
            ]

    def one_hop_relations(self, lesson_id: str) -> list[ConceptRelation]:
        concepts = self.list_concepts(lesson_id)
        if not concepts:
            return []
        return self.list_relations([c.id for c in concepts])

    def upsert_fsrs_card(self, card: FsrsCard) -> FsrsCard:
        with session_scope(self.engine) as session:
            row = session.get(FsrsCardRow, card.lesson_id)
            if row is None:
                row = FsrsCardRow(lesson_id=card.lesson_id)
                session.add(row)
            _apply_card_row(row, card)
            session.flush()
            return _card_to_model(row)

    def get_fsrs_card(self, lesson_id: str) -> FsrsCard | None:
        with session_scope(self.engine) as session:
            row = session.get(FsrsCardRow, lesson_id)
            if row is None:
                return None
            return _card_to_model(row)

    def list_due_reviews(self, now: datetime | None = None) -> list[DueReview]:
        moment = now or _utcnow()
        with session_scope(self.engine) as session:
            rows = session.execute(
                select(FsrsCardRow, LessonRow)
                .join(LessonRow, LessonRow.id == FsrsCardRow.lesson_id)
                .where(FsrsCardRow.due <= moment)
                .order_by(FsrsCardRow.due.asc())
            ).all()
            return [
                DueReview(
                    lesson_id=card.lesson_id,
                    title=lesson.title,
                    topic=lesson.topic,
                    due=card.due,
                )
                for card, lesson in rows
            ]

    def add_review(self, lesson_id: str, rating: str, scheduled_days: float) -> None:
        with session_scope(self.engine) as session:
            session.add(
                ReviewRow(
                    id=_new_id(),
                    lesson_id=lesson_id,
                    rating=rating,
                    reviewed_at=_utcnow(),
                    scheduled_days=scheduled_days,
                )
            )

    def set_last_session(self, lesson_id: str, session_id: str) -> None:
        with session_scope(self.engine) as session:
            row = session.get(LessonRow, lesson_id)
            if row is None:
                raise ValueError(f"lesson not found: {lesson_id}")
            row.last_session_id = session_id
            row.updated_at = _utcnow()

    def record_acp_session(
        self,
        lesson_id: str,
        acp_session_id: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        stop_reason: str | None = None,
    ) -> None:
        with session_scope(self.engine) as session:
            existing = session.scalar(
                select(AcpSessionRow).where(
                    AcpSessionRow.lesson_id == lesson_id,
                    AcpSessionRow.acp_session_id == acp_session_id,
                )
            )
            if existing is None:
                session.add(
                    AcpSessionRow(
                        id=_new_id(),
                        lesson_id=lesson_id,
                        acp_session_id=acp_session_id,
                        started_at=started_at,
                        ended_at=ended_at,
                        stop_reason=stop_reason,
                    )
                )
                return
            if ended_at is not None:
                existing.ended_at = ended_at
            if stop_reason is not None:
                existing.stop_reason = stop_reason
