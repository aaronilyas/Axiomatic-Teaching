"""SQLAlchemy ORM mapping for the Axiomatic Teaching SQLite schema."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UtcDateTime(TypeDecorator):
    """Store datetimes in UTC and restore tzinfo on read (SQLite is naive)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class LessonRow(Base):
    __tablename__ = "lessons"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    success_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    criteria: Mapped[list[SuccessCriterionRow]] = relationship(
        back_populates="lesson",
        cascade="all, delete-orphan",
        order_by="SuccessCriterionRow.sort_order",
    )
    completion: Mapped[CompletionRow | None] = relationship(
        back_populates="lesson",
        cascade="all, delete-orphan",
        uselist=False,
    )
    concepts: Mapped[list[ConceptRow]] = relationship(
        secondary="lesson_concepts",
        back_populates="lessons",
    )


class SuccessCriterionRow(Base):
    __tablename__ = "success_criteria"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    lesson_id: Mapped[str] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_evidence_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    lesson: Mapped[LessonRow] = relationship(back_populates="criteria")


class CompletionRow(Base):
    __tablename__ = "completions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    lesson_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unmet_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recorded_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    acp_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="record_lesson_success")

    lesson: Mapped[LessonRow] = relationship(back_populates="completion")


class GateAttemptRow(Base):
    __tablename__ = "gate_attempts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    lesson_id: Mapped[str] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class ConceptRow(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_lesson_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )

    lessons: Mapped[list[LessonRow]] = relationship(
        secondary="lesson_concepts",
        back_populates="concepts",
    )


class ConceptRelationRow(Base):
    __tablename__ = "concept_relations"
    __table_args__ = (
        UniqueConstraint(
            "from_concept_id",
            "to_concept_id",
            "relation",
            name="uq_concept_relation",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_concept_id: Mapped[str] = mapped_column(
        Text, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
    )
    to_concept_id: Mapped[str] = mapped_column(
        Text, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    source_lesson_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class LessonConceptRow(Base):
    __tablename__ = "lesson_concepts"

    lesson_id: Mapped[str] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[str] = mapped_column(
        Text, ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )


class StyleNoteRow(Base):
    __tablename__ = "style_notes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    lesson_id: Mapped[str] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class FsrsCardRow(Base):
    __tablename__ = "fsrs_cards"

    lesson_id: Mapped[str] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True
    )
    due: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    stability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    elapsed_days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scheduled_days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_review: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    card_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class ReviewRow(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    lesson_id: Mapped[str] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rating: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    scheduled_days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class AcpSessionRow(Base):
    __tablename__ = "acp_sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    lesson_id: Mapped[str] = mapped_column(
        Text, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    acp_session_id: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SchemaMigrationRow(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
