"""Auto-derived success criterion: keywords, clipping, and defaults."""

from __future__ import annotations

from axiomatic_teaching.config import (
    AUTO_MIN_EVIDENCE_CHARS,
    DEFAULT_SUCCESS_STATEMENT,
)
from axiomatic_teaching.gate.criteria import (
    build_auto_criterion,
    clip_success_description,
    extract_keywords,
    resolve_criteria,
)
from axiomatic_teaching.models import CriterionDraft, CriterionKind, NewLessonSpec


def test_extract_keywords_drops_stopwords_and_caps() -> None:
    words = extract_keywords(
        "Explain recursion with a base case and apply it to factorial."
    )
    assert "recursion" in words
    assert "base" in words
    assert "factorial" in words
    assert "explain" not in words
    assert "apply" not in words
    assert len(words) <= 5


def test_extract_keywords_from_title_topic() -> None:
    words = extract_keywords("Recursion algorithms")
    assert words == ["recursion", "algorithms"]


def test_clip_success_description_keeps_two_sentences() -> None:
    text = (
        "First sentence about Bayes. Second sentence about priors. "
        "Third sentence should be dropped."
    )
    clipped = clip_success_description(text)
    assert "First sentence" in clipped
    assert "Second sentence" in clipped
    assert "Third sentence" not in clipped


def test_build_auto_criterion_from_description() -> None:
    draft = build_auto_criterion(
        "Unused title",
        "unused",
        "Explain hashing plus collisions.",
    )
    assert draft.kind == CriterionKind.EXPLAIN
    assert draft.required is True
    assert draft.min_evidence_chars == AUTO_MIN_EVIDENCE_CHARS
    assert draft.statement == "Explain hashing plus collisions."
    assert "hashing" in draft.keywords
    assert "collisions" in draft.keywords
    assert "explain" not in draft.keywords
    assert "plus" not in draft.keywords


def test_build_auto_criterion_blank_uses_default_and_title_keywords() -> None:
    draft = build_auto_criterion("Recursion", "algorithms", "")
    assert draft.statement == DEFAULT_SUCCESS_STATEMENT
    assert "recursion" in draft.keywords
    assert "algorithms" in draft.keywords
    assert "explain" not in draft.keywords
    assert "ideas" not in draft.keywords


def test_resolve_criteria_keeps_explicit_drafts() -> None:
    spec = NewLessonSpec(
        title="Bayes",
        topic="probability",
        success_description="ignored when drafts are provided",
        criteria=[
            CriterionDraft(
                statement="Explain Bayes",
                required=True,
                min_evidence_chars=10,
                keywords=["alpha"],
            )
        ],
    )
    drafts, success = resolve_criteria(spec)
    assert len(drafts) == 1
    assert drafts[0].keywords == ["alpha"]
    assert drafts[0].min_evidence_chars == 10
    assert success == "ignored when drafts are provided"


def test_resolve_criteria_auto_fills_blank_success_description() -> None:
    spec = NewLessonSpec(title="Stacks", topic="data-structures")
    drafts, success = resolve_criteria(spec)
    assert success == DEFAULT_SUCCESS_STATEMENT
    assert len(drafts) == 1
    assert drafts[0].statement == DEFAULT_SUCCESS_STATEMENT
