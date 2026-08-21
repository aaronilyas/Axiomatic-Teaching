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
    present_lesson_html,
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


def test_present_lesson_html_validates_and_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXIOMATIC_HOME", str(tmp_path))
    _repo, lesson = _make_lesson(tmp_path, monkeypatch)
    _ = _repo

    empty = present_lesson_html(html="  ", title="Bayes")
    assert empty["ok"] is False
    assert empty["written"] is False
    assert empty["opened"] is None
    assert empty["open_status"] == "not_attempted"
    assert "empty" in empty["error"]

    ok = present_lesson_html(
        html="<p>Bayes updates a prior with evidence.</p>",
        title="Bayes plate",
        css="p { max-width: 40rem; }",
    )
    assert ok["ok"] is True
    assert ok["lesson_id"] == lesson.id
    assert ok["title"] == "Bayes plate"
    assert ok["written"] is False
    assert ok["opened"] is None
    assert ok["open_status"] == "host_pending"
    assert ok["host_action"] == "write_and_open"
    assert ok["is_full_document"] is False
    assert ok["css_inlined"] is True
    assert ok["bytes"] > 0
    assert "accepted" not in ok
    workspace = tmp_path / "lessons" / lesson.id
    assert list(workspace.glob("present-*.html")) == [] if workspace.exists() else True
    assert list(tmp_path.rglob("present-*.html")) == []


def test_present_lesson_html_requires_lesson_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AXIOMATIC_LESSON_ID", raising=False)
    result = present_lesson_html(html="<p>Hi</p>")
    assert result["ok"] is False
    assert "AXIOMATIC_LESSON_ID" in result["error"]
    assert result["host_action"] == "none"


def test_present_lesson_html_does_not_bank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, lesson = _make_lesson(tmp_path, monkeypatch)
    result = present_lesson_html(html="<p>A figure is not evidence.</p>", title="Fig")
    assert result["ok"] is True
    assert repo.get_completion(lesson.id) is None
    assert repo.get_lesson(lesson.id).status.value == "active"
    assert repo.list_concepts() == []
    assert repo.list_style_notes() == []


def test_present_lesson_html_rejects_oversize_wrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_lesson(tmp_path, monkeypatch)
    monkeypatch.setattr("axiomatic_teaching.mcp_server.server.MAX_PRESENT_BYTES", 80)
    result = present_lesson_html(html="<p>hello world this will wrap larger</p>")
    assert result["ok"] is False
    assert "maximum size" in result["error"]
    assert result["written"] is False


def test_present_lesson_html_full_document_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_lesson(tmp_path, monkeypatch)
    html = (
        "<!DOCTYPE html><html><head><title>Old</title></head>"
        "<body><h1>Full</h1></body></html>"
    )
    result = present_lesson_html(html=html, title="")
    assert result["ok"] is True
    assert result["is_full_document"] is True
    assert result["css_inlined"] is False
    assert result["written"] is False
