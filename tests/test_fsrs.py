"""FSRS wrapper tests. Uses the domain FsrsCard, not SqlRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from axiomatic_teaching.models import FsrsCard, Rating
from axiomatic_teaching.schedule.fsrs import (
    apply_review,
    is_due,
    new_card,
    review_card,
    schedule_new_completion,
)


class FakeFsrsRepository:
    def __init__(self) -> None:
        self.cards: dict[str, FsrsCard] = {}
        self.reviews: list[tuple[str, str, float]] = []

    def upsert_fsrs_card(self, card: FsrsCard) -> FsrsCard:
        self.cards[card.lesson_id] = card
        return card

    def get_fsrs_card(self, lesson_id: str) -> FsrsCard | None:
        return self.cards.get(lesson_id)

    def add_review(self, lesson_id: str, rating: str, scheduled_days: float) -> None:
        self.reviews.append((lesson_id, rating, scheduled_days))


def test_new_card_good_review_moves_due_forward() -> None:
    card = new_card()
    original_due = card.due
    now = datetime.now(timezone.utc)
    reviewed = review_card(card, "good", now=now)
    assert reviewed.due > original_due
    assert reviewed.reps >= 1
    assert reviewed.last_review is not None


def test_again_increases_lapses_or_keeps_due_soon() -> None:
    card = new_card()
    now = datetime.now(timezone.utc)
    reviewed = review_card(card, Rating.AGAIN, now=now)
    interval = reviewed.due - (reviewed.last_review or now)
    assert reviewed.lapses > 0 or interval <= timedelta(hours=1)


def test_is_due_for_new_card() -> None:
    card = new_card()
    assert is_due(card)


def test_schedule_and_apply_review_via_repository() -> None:
    repo = FakeFsrsRepository()
    created = schedule_new_completion(repo, "lesson-1")
    assert created.lesson_id == "lesson-1"
    assert repo.cards["lesson-1"].due == created.due
    later = created.due + timedelta(days=1)
    updated = apply_review(repo, "lesson-1", "again")
    assert updated.lapses >= 1
    assert repo.reviews
    assert not is_due(created, now=created.last_review) or is_due(created, now=later)
