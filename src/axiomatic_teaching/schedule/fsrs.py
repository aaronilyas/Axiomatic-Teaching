"""Thin wrapper around py-fsrs v6, persisted through the domain ``FsrsCard``."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fsrs import Card, Rating as FsrsRating, Scheduler

from axiomatic_teaching.models import FsrsCard, Rating

_SCHEDULER = Scheduler(enable_fuzzing=False)

_FSRS_BY_NAME: dict[str, FsrsRating] = {
    "again": FsrsRating.Again,
    "hard": FsrsRating.Hard,
    "good": FsrsRating.Good,
    "easy": FsrsRating.Easy,
}


def new_card() -> FsrsCard:
    """Create a domain card on the FSRS first schedule (due immediately)."""
    return _to_domain(Card(), lesson_id="", reps=0, lapses=0)


def review_card(
    card: FsrsCard,
    rating: Rating | str,
    now: datetime | None = None,
) -> FsrsCard:
    """Apply a review and return the updated domain card."""
    fsrs_card, reps, lapses = _from_domain(card)
    review_at = _as_utc(now)
    fsrs_rating = _fsrs_rating(rating)
    previous_review = fsrs_card.last_review
    elapsed_days = 0.0
    if previous_review is not None:
        elapsed_days = max((review_at - previous_review).total_seconds() / 86400.0, 0.0)
    reviewed, _log = _SCHEDULER.review_card(fsrs_card, fsrs_rating, review_datetime=review_at)
    reps += 1
    if fsrs_rating == FsrsRating.Again:
        lapses += 1
    return _to_domain(
        reviewed,
        lesson_id=card.lesson_id,
        reps=reps,
        lapses=lapses,
        elapsed_days=elapsed_days,
    )


def is_due(card: FsrsCard, now: datetime | None = None) -> bool:
    return _as_utc(card.due) <= _as_utc(now)


def schedule_new_completion(repository, lesson_id: str) -> FsrsCard:
    """Create and persist a card for a newly banked lesson (Good first schedule)."""
    existing = None
    getter = getattr(repository, "get_fsrs_card", None)
    if callable(getter):
        try:
            existing = getter(lesson_id)
        except Exception:
            existing = None
    if existing is not None:
        return existing
    card = review_card(new_card(), Rating.GOOD)
    card = card.model_copy(update={"lesson_id": lesson_id})
    return repository.upsert_fsrs_card(card)


def apply_review(repository, lesson_id: str, rating: str) -> FsrsCard:
    """Load, review, and persist a card; record the review when the repo supports it."""
    stored = None
    getter = getattr(repository, "get_fsrs_card", None)
    if callable(getter):
        stored = getter(lesson_id)
    if stored is None:
        stored = new_card().model_copy(update={"lesson_id": lesson_id})
    updated = review_card(stored, rating)
    saved = repository.upsert_fsrs_card(updated)
    add_review = getattr(repository, "add_review", None)
    if callable(add_review):
        try:
            add_review(lesson_id, str(rating), saved.scheduled_days)
        except Exception:
            pass
    return saved


def _fsrs_rating(rating: Rating | str | FsrsRating | int) -> FsrsRating:
    if isinstance(rating, FsrsRating):
        return rating
    if isinstance(rating, Rating):
        return _FSRS_BY_NAME[rating.value]
    if isinstance(rating, int):
        return FsrsRating(rating)
    key = str(rating).strip().lower()
    if key in _FSRS_BY_NAME:
        return _FSRS_BY_NAME[key]
    raise ValueError(f"unknown rating: {rating!r}")


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _from_domain(card: FsrsCard) -> tuple[Card, int, int]:
    raw = card.card_json or ""
    data: dict = {}
    if raw and raw != "{}":
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except (json.JSONDecodeError, TypeError):
            data = {}
    payload = data.get("card") if isinstance(data.get("card"), dict) else data
    fsrs_card: Card
    if payload:
        try:
            fsrs_card = Card.from_dict(payload)
        except Exception:
            fsrs_card = Card(due=_as_utc(card.due), last_review=_maybe_utc(card.last_review))
    else:
        fsrs_card = Card(due=_as_utc(card.due), last_review=_maybe_utc(card.last_review))
    reps = int(data.get("reps", card.reps) or 0)
    lapses = int(data.get("lapses", card.lapses) or 0)
    return fsrs_card, reps, lapses


def _maybe_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _as_utc(value)


def _to_domain(
    fsrs_card: Card,
    *,
    lesson_id: str,
    reps: int,
    lapses: int,
    elapsed_days: float = 0.0,
) -> FsrsCard:
    last_review = fsrs_card.last_review
    due = fsrs_card.due
    scheduled_days = 0.0
    if last_review is not None:
        scheduled_days = max((due - last_review).total_seconds() / 86400.0, 0.0)
    payload = {
        "card": fsrs_card.to_dict(),
        "reps": reps,
        "lapses": lapses,
    }
    return FsrsCard(
        lesson_id=lesson_id,
        due=due,
        stability=float(fsrs_card.stability or 0.0),
        difficulty=float(fsrs_card.difficulty or 0.0),
        elapsed_days=elapsed_days,
        scheduled_days=scheduled_days,
        reps=reps,
        lapses=lapses,
        state=int(fsrs_card.state),
        last_review=last_review,
        card_json=json.dumps(payload),
    )
