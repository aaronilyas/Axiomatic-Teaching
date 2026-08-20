"""Textual Pilot tests: wizard create → study shows criteria → knowledge after bank."""

from __future__ import annotations

from pathlib import Path

import pytest

from axiomatic_teaching.app import AxiomaticApp
from axiomatic_teaching.config import Settings
from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.models import (
    CriterionDraft,
    CriterionKind,
    EvidenceItem,
    LessonStatus,
    NewLessonSpec,
    RecordSuccessRequest,
)
from axiomatic_teaching.tui import parse_gate_result
from axiomatic_teaching.tui.screens.home import HomeScreen
from axiomatic_teaching.tui.screens.knowledge import KnowledgeScreen
from axiomatic_teaching.tui.screens.lesson_wizard import LessonWizard
from axiomatic_teaching.tui.screens.study import StudyScreen
from axiomatic_teaching.tui.widgets.chat_stream import ChatStream


def _app(tmp_path: Path) -> tuple[AxiomaticApp, object]:
    db = tmp_path / "axiomatic.db"
    settings = Settings.from_cli(db=db, demo=True)
    repository = create_repository(db)
    app = AxiomaticApp(settings, repository, session_factory=None)
    return app, repository


@pytest.mark.asyncio
async def test_home_then_wizard_creates_active_lesson(tmp_path: Path) -> None:
    app, repository = _app(tmp_path)
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, LessonWizard)
        screen = app.screen

        screen.query_one("#field-text").value = "Recursion"
        await pilot.click("#wizard-next")
        await pilot.pause()
        screen.query_one("#field-text").value = "algorithms"
        await pilot.click("#wizard-next")
        await pilot.pause()
        await pilot.click("#wizard-next")  # description
        await pilot.pause()
        await pilot.click("#wizard-next")  # tags
        await pilot.pause()
        await pilot.click("#wizard-next")  # success description
        await pilot.pause()

        statement = screen.query_one("#crit-statement")
        statement.load_text(
            "Explain recursion, including a base case, in your own words."
        )
        screen._save_criterion_form()
        screen._commit_lesson()
        await pilot.pause()
        for _ in range(4):
            if isinstance(app.screen, HomeScreen):
                break
            await pilot.press("escape")
            await pilot.pause()

        lessons = repository.list_lessons()
        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson.title == "Recursion"
        assert lesson.topic == "algorithms"
        assert lesson.status == LessonStatus.ACTIVE
        assert len(lesson.criteria) == 1
        assert lesson.criteria[0].required is True


@pytest.mark.asyncio
async def test_study_shows_criteria_without_acp(tmp_path: Path) -> None:
    app, repository = _app(tmp_path)
    lesson = repository.create_lesson(
        NewLessonSpec(
            title="Stacks",
            topic="data-structures",
            success_description="Push and pop with O(1).",
            criteria=[
                CriterionDraft(
                    kind=CriterionKind.EXPLAIN,
                    statement="Define a stack using LIFO.",
                    required=True,
                    min_evidence_chars=40,
                    keywords=["lifo"],
                )
            ],
        )
    )
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause()
        app.push_screen(StudyScreen(lesson))
        await pilot.pause()
        assert isinstance(app.screen, StudyScreen)
        body = str(app.screen.query_one("#criteria-body").render())
        assert "LIFO" in body or "stack" in body.lower() or "lifo" in body.lower()
        chat = app.screen.query_one(ChatStream)
        joined = "\n".join(str(line) for line in getattr(chat, "lines", []))
        assert "not connected" in joined.lower() or "ACP" in joined
        assert lesson.id == app.screen.lesson.id


@pytest.mark.asyncio
async def test_knowledge_shows_banked_evidence(tmp_path: Path) -> None:
    app, repository = _app(tmp_path)
    lesson = repository.create_lesson(
        NewLessonSpec(
            title="Big-O",
            topic="algorithms",
            criteria=[
                CriterionDraft(
                    kind=CriterionKind.EXPLAIN,
                    statement="Explain big-O as an upper bound on growth.",
                    required=True,
                    min_evidence_chars=40,
                    keywords=["growth"],
                )
            ],
        )
    )
    text = (
        "Big-O describes an upper bound on how an algorithm's cost growth "
        "behaves as the input size increases; constants are ignored."
    )
    result = repository.record_success(
        RecordSuccessRequest(
            lesson_id=lesson.id,
            evidence=[
                EvidenceItem(criterion_id=lesson.criteria[0].id, text=text, met=True)
            ],
            notes="banked from tui test",
        )
    )
    assert result.accepted is True
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()
        assert isinstance(app.screen, KnowledgeScreen)
        evidence = str(app.screen.query_one("#evidence-body").render())
        graph = str(app.screen.query_one("#graph-body").render())
        combined = evidence + graph
        assert "Big-O" in combined or "growth" in combined.lower() or "upper bound" in combined.lower()


def test_parse_gate_result_unwraps_grok_mcp_envelope() -> None:
    payload = {
        "type": "MCP",
        "tool_name": "record_lesson_success",
        "server_name": "axiomatic",
        "output": {
            "OkayOutput": (
                '{"accepted": false, "already_banked": false, '
                '"lesson_id": "abc", "unmet": [{"criterion_id": "c1", '
                '"reason": "too short"}], "completion_id": null, '
                '"message": "Success criteria were not met."}'
            )
        },
    }
    result = parse_gate_result(payload)
    assert result is not None
    assert result.accepted is False
    assert result.lesson_id == "abc"
    assert result.unmet and result.unmet[0].criterion_id == "c1"
