"""Shared Pydantic domain models used by the TUI, gate, MCP server, and context assembler."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LessonStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CriterionKind(StrEnum):
    EXPLAIN = "explain"
    APPLY = "apply"
    CONNECT = "connect"
    DEMONSTRATE = "demonstrate"
    RECALL = "recall"
    CUSTOM = "custom"


class RelationType(StrEnum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    APPLIES_TO = "applies_to"
    CONTRASTS = "contrasts"
    ELABORATES = "elaborates"


class Rating(StrEnum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


class Criterion(BaseModel):
    id: str
    lesson_id: str
    kind: CriterionKind
    statement: str
    required: bool = True
    min_evidence_chars: int = 40
    keywords: list[str] = Field(default_factory=list)
    sort_order: int = 0

    @field_validator("statement")
    @classmethod
    def statement_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("criterion statement must not be empty")
        return text

    @field_validator("min_evidence_chars")
    @classmethod
    def min_chars_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("min_evidence_chars must be >= 1")
        return value


class Lesson(BaseModel):
    id: str
    title: str
    topic: str
    description: str = ""
    success_description: str = ""
    status: LessonStatus = LessonStatus.DRAFT
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    last_session_id: str | None = None
    criteria: list[Criterion] = Field(default_factory=list)

    @field_validator("title", "topic")
    @classmethod
    def required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class EvidenceItem(BaseModel):
    criterion_id: str
    text: str
    met: bool = True


class ProposedConcept(BaseModel):
    name: str
    description: str = ""


class ProposedRelation(BaseModel):
    from_name: str = Field(alias="from")
    to_name: str = Field(alias="to")
    relation: RelationType
    notes: str = ""

    model_config = {"populate_by_name": True}


class RecordSuccessRequest(BaseModel):
    lesson_id: str
    evidence: list[EvidenceItem]
    notes: str = ""
    concepts: list[ProposedConcept] = Field(default_factory=list)
    relations: list[ProposedRelation] = Field(default_factory=list)
    style_note: str = ""
    acp_session_id: str | None = None


class UnmetCriterion(BaseModel):
    criterion_id: str | None = None
    reason: str


class GateResult(BaseModel):
    accepted: bool
    already_banked: bool = False
    lesson_id: str
    unmet: list[UnmetCriterion] = Field(default_factory=list)
    completion_id: str | None = None
    message: str = ""


class Completion(BaseModel):
    id: str
    lesson_id: str
    evidence: dict[str, Any]
    notes: str = ""
    recorded_at: datetime
    acp_session_id: str | None = None
    source: str = "record_lesson_success"


class Concept(BaseModel):
    id: str
    name: str
    description: str = ""
    source_lesson_id: str | None = None


class ConceptRelation(BaseModel):
    id: str
    from_concept_id: str
    to_concept_id: str
    from_name: str = ""
    to_name: str = ""
    relation: RelationType
    source_lesson_id: str | None = None
    notes: str = ""


class StyleNote(BaseModel):
    id: str
    lesson_id: str
    note: str
    created_at: datetime


class FsrsCard(BaseModel):
    lesson_id: str
    due: datetime
    stability: float = 0.0
    difficulty: float = 0.0
    elapsed_days: float = 0.0
    scheduled_days: float = 0.0
    reps: int = 0
    lapses: int = 0
    state: int = 0
    last_review: datetime | None = None
    card_json: str = "{}"


class DueReview(BaseModel):
    lesson_id: str
    title: str
    topic: str
    due: datetime


class BankedLessonSummary(BaseModel):
    id: str
    title: str
    topic: str
    description: str = ""
    concepts: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class CriterionDraft(BaseModel):
    kind: CriterionKind = CriterionKind.EXPLAIN
    statement: str
    required: bool = True
    min_evidence_chars: int = 40
    keywords: list[str] = Field(default_factory=list)

    @field_validator("statement")
    @classmethod
    def statement_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("criterion statement must not be empty")
        return text

    @field_validator("min_evidence_chars")
    @classmethod
    def min_chars_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("min_evidence_chars must be >= 1")
        return value


class NewLessonSpec(BaseModel):
    title: str
    topic: str
    description: str = ""
    success_description: str = ""
    tags: list[str] = Field(default_factory=list)
    criteria: list[CriterionDraft]

    @field_validator("title", "topic")
    @classmethod
    def required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("criteria")
    @classmethod
    def at_least_one_required(cls, value: list[CriterionDraft]) -> list[CriterionDraft]:
        if not any(item.required for item in value):
            raise ValueError("at least one required criterion is required")
        return value
