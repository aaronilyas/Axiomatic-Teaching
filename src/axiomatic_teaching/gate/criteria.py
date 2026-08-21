"""Auto-build a single success criterion from a short free-text description."""

from __future__ import annotations

import re

from axiomatic_teaching.config import (
    AUTO_MIN_EVIDENCE_CHARS,
    DEFAULT_SUCCESS_STATEMENT,
    SUCCESS_DESCRIPTION_MAX_CHARS,
)
from axiomatic_teaching.models import CriterionDraft, CriterionKind, NewLessonSpec

# Pedagogical filler and function words. Content from the title/topic/description
# survives; "explain"/"apply" do not become the gate unless they are the topic.
_STOPWORDS = {
    "a",
    "about",
    "able",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "apply",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "both",
    "but",
    "by",
    "call",
    "calls",
    "can",
    "connect",
    "core",
    "could",
    "demonstrate",
    "describe",
    "does",
    "each",
    "every",
    "example",
    "explain",
    "for",
    "from",
    "have",
    "how",
    "ideas",
    "if",
    "in",
    "including",
    "into",
    "is",
    "it",
    "its",
    "just",
    "know",
    "learner",
    "like",
    "look",
    "looks",
    "may",
    "me",
    "might",
    "more",
    "most",
    "must",
    "my",
    "no",
    "not",
    "of",
    "on",
    "or",
    "other",
    "our",
    "own",
    "plus",
    "recall",
    "should",
    "simple",
    "so",
    "some",
    "student",
    "such",
    "success",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "these",
    "they",
    "this",
    "those",
    "to",
    "too",
    "understand",
    "use",
    "used",
    "using",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "will",
    "with",
    "words",
    "would",
    "yes",
    "you",
    "your",
}

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
_KEYWORD_LIMIT = 5


def clip_success_description(
    text: str, *, max_chars: int = SUCCESS_DESCRIPTION_MAX_CHARS
) -> str:
    """Keep at most two sentences and cap length so the field stays a short contract."""
    compact = " ".join(text.split())
    if not compact:
        return ""
    sentences: list[str] = []
    buf: list[str] = []
    for char in compact:
        buf.append(char)
        if char in ".!?" and len("".join(buf).strip()) >= 8:
            sentences.append("".join(buf).strip())
            buf = []
            if len(sentences) >= 2:
                break
    remainder = "".join(buf).strip()
    if len(sentences) < 2 and remainder:
        sentences.append(remainder)
    clipped = " ".join(sentences[:2]) if sentences else compact
    if len(clipped) > max_chars:
        clipped = clipped[: max_chars - 1].rstrip() + "…"
    return clipped


def extract_keywords(text: str, *, limit: int = _KEYWORD_LIMIT) -> list[str]:
    """Content words from free text, lowercased, de-duplicated, stopwords removed."""
    if not text or limit <= 0:
        return []
    seen: set[str] = set()
    keywords: list[str] = []
    for raw in _TOKEN.findall(text):
        folded = raw.casefold().strip("-'")
        if len(folded) < 3 or folded in _STOPWORDS or folded in seen:
            continue
        seen.add(folded)
        keywords.append(folded)
        if len(keywords) >= limit:
            break
    return keywords


def build_auto_criterion(
    title: str,
    topic: str,
    success_description: str = "",
) -> CriterionDraft:
    """One required criterion: user text (or a default) plus extracted keywords."""
    clipped = clip_success_description(success_description)
    statement = clipped or DEFAULT_SUCCESS_STATEMENT
    keywords = extract_keywords(clipped)
    if not keywords:
        keywords = extract_keywords(f"{title} {topic}")
    return CriterionDraft(
        kind=CriterionKind.EXPLAIN,
        statement=statement,
        required=True,
        min_evidence_chars=AUTO_MIN_EVIDENCE_CHARS,
        keywords=keywords,
    )


def resolve_criteria(spec: NewLessonSpec) -> tuple[list[CriterionDraft], str]:
    """Criteria to persist plus the success_description stored on the lesson.

    Explicit drafts (tests, scripts) are kept as-is. Otherwise a single required
    criterion is derived from the optional success description.
    """
    success = clip_success_description(spec.success_description)
    if spec.criteria:
        return list(spec.criteria), success
    draft = build_auto_criterion(spec.title, spec.topic, success)
    return [draft], success or DEFAULT_SUCCESS_STATEMENT
