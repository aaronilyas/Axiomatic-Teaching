"""Pure success-gate evaluation. No I/O — persistence lives on the repository."""

from __future__ import annotations

from axiomatic_teaching.models import (
    Criterion,
    EvidenceItem,
    GateResult,
    Lesson,
    LessonStatus,
    RecordSuccessRequest,
    UnmetCriterion,
)


def _fold(text: str) -> str:
    """Case-fold and collapse whitespace so keyword checks are substring matches."""
    return " ".join(text.split()).casefold()


def _keywords_present(text: str, keywords: list[str]) -> list[str]:
    haystack = _fold(text)
    missing: list[str] = []
    for raw in keywords:
        needle = _fold(raw)
        if not needle:
            continue
        if needle not in haystack:
            missing.append(raw)
    return missing


def _check_item(criterion: Criterion, item: EvidenceItem) -> list[UnmetCriterion]:
    unmet: list[UnmetCriterion] = []
    if not item.met:
        role = "required" if criterion.required else "optional"
        unmet.append(
            UnmetCriterion(
                criterion_id=criterion.id,
                reason=f"{role} criterion is not marked met",
            )
        )
    stripped = item.text.strip()
    if len(stripped) < criterion.min_evidence_chars:
        unmet.append(
            UnmetCriterion(
                criterion_id=criterion.id,
                reason=(
                    f"evidence is shorter than {criterion.min_evidence_chars} characters"
                ),
            )
        )
    for keyword in _keywords_present(item.text, criterion.keywords):
        unmet.append(
            UnmetCriterion(
                criterion_id=criterion.id,
                reason=f"keyword {keyword!r} not found in evidence",
            )
        )
    return unmet


def evaluate(lesson: Lesson, request: RecordSuccessRequest) -> GateResult:
    """Return whether `request` satisfies every required (and any provided optional) criterion."""
    if lesson.status == LessonStatus.DELETED:
        return GateResult(
            accepted=False,
            lesson_id=lesson.id,
            unmet=[UnmetCriterion(criterion_id=None, reason="lesson has been deleted")],
            message="Lesson has been deleted and cannot be banked.",
        )
    if lesson.status == LessonStatus.COMPLETED:
        return GateResult(
            accepted=True,
            already_banked=True,
            lesson_id=lesson.id,
            unmet=[],
            message="Lesson already banked.",
        )
    if lesson.status != LessonStatus.ACTIVE:
        return GateResult(
            accepted=False,
            lesson_id=lesson.id,
            unmet=[
                UnmetCriterion(
                    criterion_id=None,
                    reason=f"lesson is not active (status={lesson.status})",
                )
            ],
            message="Lesson is not active and cannot be banked.",
        )

    known = {c.id: c for c in lesson.criteria}
    by_id: dict[str, EvidenceItem] = {}
    ignored: list[str] = []
    for item in request.evidence:
        if item.criterion_id not in known:
            ignored.append(item.criterion_id)
            continue
        by_id.setdefault(item.criterion_id, item)

    unmet: list[UnmetCriterion] = []
    if not request.evidence:
        unmet.append(
            UnmetCriterion(criterion_id=None, reason="evidence list is empty")
        )

    for criterion in lesson.criteria:
        item = by_id.get(criterion.id)
        if item is None:
            if criterion.required:
                unmet.append(
                    UnmetCriterion(
                        criterion_id=criterion.id,
                        reason="missing evidence for required criterion",
                    )
                )
            continue
        unmet.extend(_check_item(criterion, item))

    ignored_note = ""
    if ignored:
        ignored_note = " Ignored unknown criterion_id(s): " + ", ".join(ignored) + "."

    if unmet:
        return GateResult(
            accepted=False,
            lesson_id=lesson.id,
            unmet=unmet,
            message="Success criteria were not met." + ignored_note,
        )
    return GateResult(
        accepted=True,
        already_banked=False,
        lesson_id=lesson.id,
        unmet=[],
        message="Lesson banked." + ignored_note,
    )
