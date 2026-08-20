"""SqlRepository: schema constraints, create_lesson, and gated writes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from axiomatic_teaching.db.engine import session_scope
from axiomatic_teaching.db.orm import (
    CompletionRow,
    ConceptRow,
    LessonRow,
    StyleNoteRow,
    SuccessCriterionRow,
)
from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.models import (
    CriterionDraft,
    CriterionKind,
    EvidenceItem,
    LessonStatus,
    NewLessonSpec,
    ProposedConcept,
    ProposedRelation,
    RecordSuccessRequest,
    RelationType,
)

PASSING_TEXT = "alpha " + ("word " * 20)


def _spec(*criteria: CriterionDraft) -> NewLessonSpec:
    if not criteria:
        criteria = (
            CriterionDraft(
                kind=CriterionKind.EXPLAIN,
                statement="Explain it",
                required=True,
                min_evidence_chars=10,
                keywords=["alpha"],
            ),
        )
    return NewLessonSpec(title="Lesson", topic="topic", tags=["t1"], criteria=list(criteria))


def test_create_lesson_assigns_uuids_and_active_status(tmp_path: Path) -> None:
    repo = create_repository(tmp_path / "db.sqlite")
    lesson = repo.create_lesson(_spec())
    assert lesson.id
    assert lesson.status == LessonStatus.ACTIVE
    assert len(lesson.criteria) == 1
    assert lesson.criteria[0].id
    assert lesson.criteria[0].lesson_id == lesson.id
    loaded = repo.get_lesson(lesson.id)
    assert loaded is not None
    assert loaded.title == "Lesson"
    assert loaded.tags == ["t1"]


def test_create_lesson_requires_required_criterion(tmp_path: Path) -> None:
    repo = create_repository(tmp_path / "db.sqlite")
    with pytest.raises(ValueError, match="required criterion"):
        repo.create_lesson(
            _spec(
                CriterionDraft(
                    statement="optional only",
                    required=False,
                )
            )
        )
    with pytest.raises(ValueError, match="required criterion"):
        repo.create_lesson(NewLessonSpec(title="A", topic="B", criteria=[]))


def test_foreign_key_cascade_deletes_criteria(tmp_path: Path) -> None:
    repo = create_repository(tmp_path / "db.sqlite")
    lesson = repo.create_lesson(_spec())
    criterion_id = lesson.criteria[0].id
    with session_scope(repo.engine) as session:
        flags = session.execute(text("PRAGMA foreign_keys")).one()
        assert flags[0] == 1
        session.execute(delete(LessonRow).where(LessonRow.id == lesson.id))
    assert repo.get_lesson(lesson.id) is None
    with session_scope(repo.engine) as session:
        assert session.get(SuccessCriterionRow, criterion_id) is None
        remaining = session.scalar(
            select(func.count()).select_from(SuccessCriterionRow).where(
                SuccessCriterionRow.lesson_id == lesson.id
            )
        )
        assert remaining == 0


def test_completion_unique_on_lesson_id(tmp_path: Path) -> None:
    repo = create_repository(tmp_path / "db.sqlite")
    lesson = repo.create_lesson(_spec())
    now = datetime.now(timezone.utc)
    with session_scope(repo.engine) as session:
        session.add(
            CompletionRow(
                id="c1",
                lesson_id=lesson.id,
                evidence_json="{}",
                notes="",
                unmet_json="[]",
                recorded_at=now,
                source="test",
            )
        )
    with pytest.raises(IntegrityError):
        with session_scope(repo.engine) as session:
            session.add(
                CompletionRow(
                    id="c2",
                    lesson_id=lesson.id,
                    evidence_json="{}",
                    notes="",
                    unmet_json="[]",
                    recorded_at=now,
                    source="test",
                )
            )


def test_fail_path_does_not_write_completion_style_or_concepts(tmp_path: Path) -> None:
    repo = create_repository(tmp_path / "db.sqlite")
    lesson = repo.create_lesson(_spec())
    result = repo.record_success(
        RecordSuccessRequest(
            lesson_id=lesson.id,
            evidence=[],
            concepts=[ProposedConcept(name="LeakedConcept")],
            relations=[
                ProposedRelation(
                    **{"from": "LeakedConcept", "to": "Other", "relation": RelationType.RELATED}
                )
            ],
            style_note="leaked style",
        )
    )
    assert result.accepted is False
    assert repo.get_completion(lesson.id) is None
    assert repo.list_concepts() == []
    assert repo.list_style_notes() == []
    assert repo.get_fsrs_card(lesson.id) is None
    assert repo.list_banked_summaries() == []
    with session_scope(repo.engine) as session:
        assert session.scalar(select(func.count()).select_from(CompletionRow)) == 0
        assert session.scalar(select(func.count()).select_from(StyleNoteRow)) == 0
        assert session.scalar(select(func.count()).select_from(ConceptRow)) == 0


def test_pass_path_writes_completion_graph_style_and_fsrs(tmp_path: Path) -> None:
    repo = create_repository(tmp_path / "db.sqlite")
    lesson = repo.create_lesson(_spec())
    crit = lesson.criteria[0]
    result = repo.record_success(
        RecordSuccessRequest(
            lesson_id=lesson.id,
            evidence=[EvidenceItem(criterion_id=crit.id, text=PASSING_TEXT, met=True)],
            notes="n1",
            concepts=[ProposedConcept(name="Bayes", description="conditional probability")],
            relations=[
                ProposedRelation(
                    **{
                        "from": "Bayes",
                        "to": "Probability",
                        "relation": RelationType.APPLIES_TO,
                        "notes": "specializes",
                    }
                )
            ],
            style_note="prefer concrete examples",
        )
    )
    assert result.accepted is True
    assert result.already_banked is False
    completion = repo.get_completion(lesson.id)
    assert completion is not None
    assert completion.id == result.completion_id
    assert completion.notes == "n1"
    assert completion.source == "record_lesson_success"
    banked = repo.get_lesson(lesson.id)
    assert banked is not None
    assert banked.status == LessonStatus.COMPLETED
    assert banked.completed_at is not None
    names = {c.name for c in repo.list_concepts(lesson.id)}
    assert names == {"Bayes", "Probability"}
    rels = repo.one_hop_relations(lesson.id)
    assert len(rels) == 1
    assert rels[0].from_name == "Bayes"
    assert rels[0].to_name == "Probability"
    assert rels[0].relation == RelationType.APPLIES_TO
    notes = repo.list_style_notes()
    assert len(notes) == 1
    assert notes[0].note == "prefer concrete examples"
    card = repo.get_fsrs_card(lesson.id)
    assert card is not None
    assert card.due is not None
    assert card.card_json and card.card_json != "{}"
    summaries = repo.list_banked_summaries()
    assert len(summaries) == 1
    assert summaries[0].id == lesson.id
    assert "Bayes" in summaries[0].concepts


def test_empty_style_note_not_inserted_on_pass(tmp_path: Path) -> None:
    repo = create_repository(tmp_path / "db.sqlite")
    lesson = repo.create_lesson(_spec())
    crit = lesson.criteria[0]
    repo.record_success(
        RecordSuccessRequest(
            lesson_id=lesson.id,
            evidence=[EvidenceItem(criterion_id=crit.id, text=PASSING_TEXT, met=True)],
            style_note="   ",
        )
    )
    assert repo.get_completion(lesson.id) is not None
    assert repo.list_style_notes() == []
