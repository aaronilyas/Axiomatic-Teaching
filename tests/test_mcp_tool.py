"""In-process MCP tool handlers: gate writes only after sufficient evidence."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.mcp_server.server import (
    _repository,
    get_connections,
    get_lesson_criteria,
    list_banked_lessons,
    record_lesson_success,
    reset_repository_cache,
)
from axiomatic_teaching.models import (
    CriterionDraft,
    CriterionKind,
    NewLessonSpec,
    RelationType,
)

PASSING_TEXT = "alpha " + ("word " * 20)


@pytest.fixture(autouse=True)
def _reset_mcp_repo() -> Iterator[None]:
    reset_repository_cache()
    yield
    reset_repository_cache()


def _make_lesson(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "axiomatic.db"
    monkeypatch.setenv("AXIOMATIC_DB", str(db_path))
    repo = create_repository(db_path)
    lesson = repo.create_lesson(
        NewLessonSpec(
            title="Bayes",
            topic="probability",
            criteria=[
                CriterionDraft(
                    kind=CriterionKind.EXPLAIN,
                    statement="Explain Bayes",
                    required=True,
                    min_evidence_chars=10,
                    keywords=["alpha"],
                )
            ],
        )
    )
    monkeypatch.setenv("AXIOMATIC_LESSON_ID", lesson.id)
    return repo, lesson


def test_record_lesson_success_insufficient_then_sufficient(tmp_path: Path, monkeypatch) -> None:
    repo, lesson = _make_lesson(tmp_path, monkeypatch)
    crit_id = lesson.criteria[0].id

    insufficient = record_lesson_success(
        lesson_id=lesson.id,
        evidence=[{"criterion_id": crit_id, "text": "too short", "met": True}],
        concepts=[{"name": "ShouldNotExist"}],
        style_note="nope",
    )
    assert insufficient["accepted"] is False
    assert insufficient["already_banked"] is False
    assert repo.get_completion(lesson.id) is None
    assert repo.list_concepts() == []
    assert repo.list_style_notes() == []

    sufficient = record_lesson_success(
        lesson_id=lesson.id,
        evidence=[{"criterion_id": crit_id, "text": PASSING_TEXT, "met": True}],
        concepts=[{"name": "Bayes", "description": "P(H|E)"}],
        relations=[
            {
                "from": "Bayes",
                "to": "Evidence",
                "relation": RelationType.RELATED.value,
            }
        ],
        style_note="show the formula first",
        notes="banked via MCP",
    )
    assert sufficient["accepted"] is True
    assert sufficient["already_banked"] is False
    completion = repo.get_completion(lesson.id)
    assert completion is not None
    assert completion.id == sufficient["completion_id"]
    assert completion.notes == "banked via MCP"
    assert {c.name for c in repo.list_concepts(lesson.id)} == {"Bayes", "Evidence"}
    assert repo.list_style_notes()[0].note == "show the formula first"
    assert repo.get_fsrs_card(lesson.id) is not None

    banked = list_banked_lessons()
    rows = banked["lessons"] if isinstance(banked, dict) else banked
    assert any(item["id"] == lesson.id for item in rows)
    assert "Bayes" in rows[0]["concepts"] or any(
        "Bayes" in item.get("concepts", []) for item in rows
    )


def test_record_lesson_success_rejects_other_lesson_id(tmp_path: Path, monkeypatch) -> None:
    repo, lesson = _make_lesson(tmp_path, monkeypatch)
    other = repo.create_lesson(
        NewLessonSpec(
            title="Other",
            topic="other",
            criteria=[
                CriterionDraft(
                    statement="Other criterion",
                    required=True,
                    min_evidence_chars=10,
                    keywords=["alpha"],
                )
            ],
        )
    )
    result = record_lesson_success(
        lesson_id=other.id,
        evidence=[
            {"criterion_id": other.criteria[0].id, "text": PASSING_TEXT, "met": True}
        ],
    )
    assert result["accepted"] is False
    assert "AXIOMATIC_LESSON_ID" in result["message"] or any(
        "AXIOMATIC_LESSON_ID" in u["reason"] for u in result["unmet"]
    )
    assert repo.get_completion(other.id) is None
    assert repo.get_completion(lesson.id) is None


def test_get_lesson_criteria_returns_ids(tmp_path: Path, monkeypatch) -> None:
    _repo, lesson = _make_lesson(tmp_path, monkeypatch)
    payload = get_lesson_criteria()
    assert payload["lesson_id"] == lesson.id
    ids = [c["id"] for c in payload["criteria"]]
    assert lesson.criteria[0].id in ids
    assert payload["criteria"][0]["keywords"] == ["alpha"]


def test_get_connections_one_hop(tmp_path: Path, monkeypatch) -> None:
    repo, lesson = _make_lesson(tmp_path, monkeypatch)
    crit_id = lesson.criteria[0].id
    record_lesson_success(
        lesson_id=lesson.id,
        evidence=[{"criterion_id": crit_id, "text": PASSING_TEXT, "met": True}],
        concepts=[{"name": "Bayes"}],
        relations=[{"from": "Bayes", "to": "Stats", "relation": "related"}],
    )
    payload = get_connections()
    assert payload["lesson_id"] == lesson.id
    assert len(payload["relations"]) == 1
    rel = payload["relations"][0]
    assert {rel["from_name"], rel["to_name"]} == {"Bayes", "Stats"}
    _ = repo


def test_mcp_repository_is_cached(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "axiomatic.db"
    monkeypatch.setenv("AXIOMATIC_DB", str(db_path))
    first = _repository()
    second = _repository()
    assert first is second
