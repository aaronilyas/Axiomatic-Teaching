"""Table-driven success-gate tests: pure evaluate() plus persist side effects."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from axiomatic_teaching.db.orm import CompletionRow, ConceptRow, GateAttemptRow, StyleNoteRow
from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.db.sql_repository import SqlRepository
from axiomatic_teaching.gate.success import evaluate
from axiomatic_teaching.models import (
    Criterion,
    CriterionDraft,
    CriterionKind,
    EvidenceItem,
    Lesson,
    LessonStatus,
    NewLessonSpec,
    ProposedConcept,
    RecordSuccessRequest,
)

PASSING_TEXT = "alpha " + ("word " * 20)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lesson(*, status: LessonStatus = LessonStatus.ACTIVE) -> Lesson:
    lesson_id = "lesson-1"
    return Lesson(
        id=lesson_id,
        title="Bayes",
        topic="probability",
        status=status,
        created_at=_now(),
        updated_at=_now(),
        criteria=[
            Criterion(
                id="c-req",
                lesson_id=lesson_id,
                kind=CriterionKind.EXPLAIN,
                statement="Explain Bayes",
                required=True,
                min_evidence_chars=10,
                keywords=["alpha"],
                sort_order=0,
            ),
            Criterion(
                id="c-opt",
                lesson_id=lesson_id,
                kind=CriterionKind.APPLY,
                statement="Optional apply",
                required=False,
                min_evidence_chars=10,
                keywords=["beta"],
                sort_order=1,
            ),
        ],
    )


def _request(lesson: Lesson, evidence: list[EvidenceItem]) -> RecordSuccessRequest:
    return RecordSuccessRequest(lesson_id=lesson.id, evidence=evidence)


EVALUATE_CASES = [
    {
        "id": "missing_required",
        "status": LessonStatus.ACTIVE,
        "evidence": [EvidenceItem(criterion_id="c-opt", text=PASSING_TEXT.replace("alpha", "beta"), met=True)],
        "accepted": False,
        "already_banked": False,
        "reason": "missing evidence for required criterion",
    },
    {
        "id": "empty_evidence",
        "status": LessonStatus.ACTIVE,
        "evidence": [],
        "accepted": False,
        "already_banked": False,
        "reason": "evidence list is empty",
    },
    {
        "id": "short_evidence",
        "status": LessonStatus.ACTIVE,
        "evidence": [EvidenceItem(criterion_id="c-req", text="alpha", met=True)],
        "accepted": False,
        "already_banked": False,
        "reason": "shorter than",
    },
    {
        "id": "missing_keyword",
        "status": LessonStatus.ACTIVE,
        "evidence": [EvidenceItem(criterion_id="c-req", text="word " * 20, met=True)],
        "accepted": False,
        "already_banked": False,
        "reason": "keyword 'alpha' not found",
    },
    {
        "id": "met_false",
        "status": LessonStatus.ACTIVE,
        "evidence": [EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=False)],
        "accepted": False,
        "already_banked": False,
        "reason": "not marked met",
    },
    {
        "id": "unknown_ids_ignored",
        "status": LessonStatus.ACTIVE,
        "evidence": [
            EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True),
            EvidenceItem(criterion_id="unknown", text="nope", met=False),
        ],
        "accepted": True,
        "already_banked": False,
        "reason": None,
    },
    {
        "id": "all_required_good",
        "status": LessonStatus.ACTIVE,
        "evidence": [EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True)],
        "accepted": True,
        "already_banked": False,
        "reason": None,
    },
    {
        "id": "already_completed",
        "status": LessonStatus.COMPLETED,
        "evidence": [],
        "accepted": True,
        "already_banked": True,
        "reason": None,
    },
    {
        "id": "optional_missing_ok",
        "status": LessonStatus.ACTIVE,
        "evidence": [EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True)],
        "accepted": True,
        "already_banked": False,
        "reason": None,
    },
    {
        "id": "draft_cannot_bank",
        "status": LessonStatus.DRAFT,
        "evidence": [EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True)],
        "accepted": False,
        "already_banked": False,
        "reason": "lesson is not active",
    },
    {
        "id": "archived_cannot_bank",
        "status": LessonStatus.ARCHIVED,
        "evidence": [EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True)],
        "accepted": False,
        "already_banked": False,
        "reason": "lesson is not active",
    },
    {
        "id": "deleted_cannot_bank",
        "status": LessonStatus.DELETED,
        "evidence": [EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True)],
        "accepted": False,
        "already_banked": False,
        "reason": "lesson has been deleted",
    },
    {
        "id": "optional_provided_must_pass",
        "status": LessonStatus.ACTIVE,
        "evidence": [
            EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True),
            EvidenceItem(criterion_id="c-opt", text="short", met=True),
        ],
        "accepted": False,
        "already_banked": False,
        "reason": "shorter than",
    },
    {
        "id": "keyword_whitespace_normalized",
        "status": LessonStatus.ACTIVE,
        "evidence": [EvidenceItem(criterion_id="c-req", text="ALPHA\n" + ("word " * 20), met=True)],
        "accepted": True,
        "already_banked": False,
        "reason": None,
    },
]


@pytest.mark.parametrize("case", EVALUATE_CASES, ids=lambda c: c["id"])
def test_evaluate_table(case: dict) -> None:
    lesson = _lesson(status=case["status"])
    result = evaluate(lesson, _request(lesson, case["evidence"]))
    assert result.accepted is case["accepted"]
    assert result.already_banked is case["already_banked"]
    assert result.lesson_id == lesson.id
    if case["accepted"]:
        assert result.unmet == []
    else:
        blob = " ".join(u.reason for u in result.unmet)
        assert case["reason"] in blob


def _repo(tmp_path: Path) -> SqlRepository:
    return create_repository(tmp_path / "axiomatic.db")


def _spec(*, optional: bool = True) -> NewLessonSpec:
    criteria = [
        CriterionDraft(
            kind=CriterionKind.EXPLAIN,
            statement="Explain Bayes",
            required=True,
            min_evidence_chars=10,
            keywords=["alpha"],
        )
    ]
    if optional:
        criteria.append(
            CriterionDraft(
                kind=CriterionKind.APPLY,
                statement="Optional apply",
                required=False,
                min_evidence_chars=10,
                keywords=["beta"],
            )
        )
    return NewLessonSpec(title="Bayes", topic="probability", criteria=criteria)


def _required_id(repo: SqlRepository, lesson_id: str) -> str:
    required = [c for c in repo.list_criteria(lesson_id) if c.required]
    assert required
    return required[0].id


def _count(session, model, **kwargs) -> int:
    from sqlalchemy import func, select

    stmt = select(func.count()).select_from(model)
    for key, value in kwargs.items():
        stmt = stmt.where(getattr(model, key) == value)
    return int(session.scalar(stmt) or 0)


@pytest.mark.parametrize(
    "case_id,evidence_builder,status,expect_accepted,expect_already_banked,expect_completion",
    [
        ("missing_required", "missing", LessonStatus.ACTIVE, False, False, False),
        ("short_evidence", "short", LessonStatus.ACTIVE, False, False, False),
        ("missing_keyword", "no_keyword", LessonStatus.ACTIVE, False, False, False),
        ("met_false", "met_false", LessonStatus.ACTIVE, False, False, False),
        ("unknown_ids_ignored", "unknown_ok", LessonStatus.ACTIVE, True, False, True),
        ("all_required_good", "good", LessonStatus.ACTIVE, True, False, True),
        ("optional_missing_ok", "good", LessonStatus.ACTIVE, True, False, True),
        ("draft_cannot_bank", "good", LessonStatus.DRAFT, False, False, False),
    ],
)
def test_record_success_persist_table(
    tmp_path: Path,
    case_id: str,
    evidence_builder: str,
    status: LessonStatus,
    expect_accepted: bool,
    expect_already_banked: bool,
    expect_completion: bool,
) -> None:
    _ = case_id
    repo = _repo(tmp_path)
    lesson = repo.create_lesson(_spec())
    if status != LessonStatus.ACTIVE:
        lesson.status = status
        lesson = repo.save_lesson(lesson)
    req_id = _required_id(repo, lesson.id)
    builders = {
        "missing": [EvidenceItem(criterion_id="nope", text=PASSING_TEXT, met=True)],
        "short": [EvidenceItem(criterion_id=req_id, text="alpha", met=True)],
        "no_keyword": [EvidenceItem(criterion_id=req_id, text="word " * 20, met=True)],
        "met_false": [EvidenceItem(criterion_id=req_id, text=PASSING_TEXT, met=False)],
        "unknown_ok": [
            EvidenceItem(criterion_id=req_id, text=PASSING_TEXT, met=True),
            EvidenceItem(criterion_id="ghost", text="x", met=False),
        ],
        "good": [EvidenceItem(criterion_id=req_id, text=PASSING_TEXT, met=True)],
    }
    result = repo.record_success(
        RecordSuccessRequest(
            lesson_id=lesson.id,
            evidence=builders[evidence_builder],
            concepts=[ProposedConcept(name="ShouldNotLeak")],
            style_note="should not leak on fail",
        )
    )
    assert result.accepted is expect_accepted
    assert result.already_banked is expect_already_banked
    completion = repo.get_completion(lesson.id)
    if expect_completion:
        assert completion is not None
        assert result.completion_id == completion.id
        assert repo.get_fsrs_card(lesson.id) is not None
    else:
        assert completion is None
        assert repo.list_concepts() == []
        assert repo.list_style_notes() == []
        assert repo.get_fsrs_card(lesson.id) is None

    from axiomatic_teaching.db.engine import session_scope

    with session_scope(repo.engine) as session:
        assert _count(session, GateAttemptRow, lesson_id=lesson.id) == 1
        assert _count(session, CompletionRow, lesson_id=lesson.id) == (1 if expect_completion else 0)


def test_already_completed_no_duplicate_completion(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    lesson = repo.create_lesson(_spec(optional=False))
    req_id = _required_id(repo, lesson.id)
    first = repo.record_success(
        RecordSuccessRequest(
            lesson_id=lesson.id,
            evidence=[EvidenceItem(criterion_id=req_id, text=PASSING_TEXT, met=True)],
            concepts=[ProposedConcept(name="Bayes")],
            style_note="concrete examples",
        )
    )
    assert first.accepted is True
    assert first.already_banked is False
    assert repo.get_completion(lesson.id) is not None

    second = repo.record_success(
        RecordSuccessRequest(
            lesson_id=lesson.id,
            evidence=[],
            concepts=[ProposedConcept(name="MustNotDuplicate")],
            style_note="must not write again",
        )
    )
    assert second.accepted is True
    assert second.already_banked is True
    assert second.completion_id == first.completion_id
    assert len(repo.list_completions()) == 1
    assert [c.name for c in repo.list_concepts()] == ["Bayes"]
    notes = repo.list_style_notes()
    assert len(notes) == 1
    assert notes[0].note == "concrete examples"

    from axiomatic_teaching.db.engine import session_scope

    with session_scope(repo.engine) as session:
        assert _count(session, GateAttemptRow, lesson_id=lesson.id) == 2
        assert _count(session, CompletionRow, lesson_id=lesson.id) == 1
        assert _count(session, StyleNoteRow, lesson_id=lesson.id) == 1
        assert _count(session, ConceptRow) == 1


def test_unknown_ids_mentioned_in_message() -> None:
    lesson = _lesson()
    result = evaluate(
        lesson,
        _request(
            lesson,
            [
                EvidenceItem(criterion_id="c-req", text=PASSING_TEXT, met=True),
                EvidenceItem(criterion_id="ghost", text="x", met=False),
            ],
        ),
    )
    assert result.accepted is True
    assert "ghost" in result.message


def test_concurrent_record_success_single_completion(tmp_path: Path) -> None:
    import threading

    repo = _repo(tmp_path)
    lesson = repo.create_lesson(_spec(optional=False))
    req_id = _required_id(repo, lesson.id)
    request = RecordSuccessRequest(
        lesson_id=lesson.id,
        evidence=[EvidenceItem(criterion_id=req_id, text=PASSING_TEXT, met=True)],
        style_note="only once",
    )
    results: list = []

    def _call() -> None:
        results.append(repo.record_success(request))

    threads = [threading.Thread(target=_call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 2
    assert all(item.accepted for item in results)
    assert sum(1 for item in results if item.already_banked) >= 1
    assert len(repo.list_completions()) == 1
    assert len(repo.list_style_notes()) == 1
