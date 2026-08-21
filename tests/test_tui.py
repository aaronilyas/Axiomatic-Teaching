"""Textual Pilot tests: new-lesson form → study shows criterion → knowledge after bank."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from axiomatic_teaching.app import AxiomaticApp
from axiomatic_teaching.config import Settings
from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.models import (
    Criterion,
    CriterionDraft,
    CriterionKind,
    EvidenceItem,
    GateResult,
    Lesson,
    LessonStatus,
    NewLessonSpec,
    RecordSuccessRequest,
    UnmetCriterion,
)
from axiomatic_teaching.tui import parse_gate_result
from axiomatic_teaching.tui.widgets.criteria_panel import _format_panel, _mark
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

        assert list(screen.query("#crit-kind")) == []
        assert list(screen.query("#crit-statement")) == []
        assert list(screen.query("#wizard-next")) == []
        assert list(screen.query("#wizard-step-label")) == []
        assert list(screen.query("#crit-required")) == []
        assert list(screen.query("#crit-min")) == []
        assert list(screen.query("#crit-keywords")) == []
        assert screen.query_one("#wizard-title") is not None
        help_text = str(screen.query_one("#success-help").render())
        assert "criteria editor" not in help_text.lower()

        screen.query_one("#field-title").value = "Recursion"
        screen.query_one("#field-topic").value = "algorithms"
        screen.query_one("#field-success").load_text(
            "Explain recursion, including a base case, in your own words."
        )
        await pilot.click("#wizard-create")
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
        assert "recursion" in {k.lower() for k in lesson.criteria[0].keywords}
        assert "base" in {k.lower() for k in lesson.criteria[0].keywords}


@pytest.mark.asyncio
async def test_wizard_blank_success_then_study_and_gate(tmp_path: Path) -> None:
    from axiomatic_teaching.config import AUTO_MIN_EVIDENCE_CHARS, DEFAULT_SUCCESS_STATEMENT

    app, repository = _app(tmp_path)
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, LessonWizard)
        screen = app.screen
        screen.query_one("#field-title").value = "Bayes"
        screen.query_one("#field-topic").value = "probability"
        await pilot.click("#wizard-create")
        await pilot.pause()
        for _ in range(4):
            if isinstance(app.screen, HomeScreen):
                break
            await pilot.press("escape")
            await pilot.pause()

        lessons = repository.list_lessons()
        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson.success_description == DEFAULT_SUCCESS_STATEMENT
        assert lesson.criteria[0].min_evidence_chars == AUTO_MIN_EVIDENCE_CHARS
        assert "bayes" in {k.lower() for k in lesson.criteria[0].keywords}

        app.push_screen(StudyScreen(lesson))
        await pilot.pause()
        assert isinstance(app.screen, StudyScreen)
        body = str(app.screen.query_one("#criteria-body").render())
        assert "core ideas" in body.lower() or "bayes" in body.lower()
        assert "○ Gate" not in body

        too_short = repository.record_success(
            RecordSuccessRequest(
                lesson_id=lesson.id,
                evidence=[
                    EvidenceItem(
                        criterion_id=lesson.criteria[0].id,
                        text="nope",
                        met=True,
                    )
                ],
            )
        )
        assert too_short.accepted is False
        assert repository.get_completion(lesson.id) is None

        passing = (
            "Bayes updates a prior with likelihood to get a posterior in probability. "
            "I can walk a simple diagnostic-test example in my own words."
        )
        accepted = repository.record_success(
            RecordSuccessRequest(
                lesson_id=lesson.id,
                evidence=[
                    EvidenceItem(
                        criterion_id=lesson.criteria[0].id,
                        text=passing,
                        met=True,
                    )
                ],
            )
        )
        assert accepted.accepted is True
        assert repository.get_completion(lesson.id) is not None

        reloaded = repository.get_lesson(lesson.id)
        app.screen.query_one("#study-criteria").set_lesson(reloaded)
        app.screen.query_one("#study-criteria").apply_gate(accepted)
        await pilot.pause()
        gated = str(app.screen.query_one("#criteria-body").render())
        assert "Gate PASS" in gated or "✓" in gated


@pytest.mark.asyncio
async def test_acp_events_reach_study_chat(tmp_path: Path) -> None:
    from axiomatic_teaching.acp_client.events import StreamChunk, ToolCallEvent
    from axiomatic_teaching.tui import ACPEvent

    assert ACPEvent.handler_name == "on_acp_event"
    app, repository = _app(tmp_path)
    lesson = repository.create_lesson(
        NewLessonSpec(
            title="Queues",
            topic="data-structures",
            criteria=[
                CriterionDraft(
                    statement="Define a queue using FIFO.",
                    required=True,
                    keywords=["fifo"],
                )
            ],
        )
    )
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.pause()
        app.push_screen(StudyScreen(lesson))
        await pilot.pause()
        app.dispatch_acp_event(StreamChunk(text="Hello from the tutor.", role="agent"))
        await pilot.pause()
        fail = GateResult(
            accepted=False,
            lesson_id=lesson.id,
            unmet=[UnmetCriterion(criterion_id=None, reason="evidence list is empty")],
            message="Success criteria were not met.",
        )
        app.dispatch_acp_event(
            ToolCallEvent(
                tool_call_id="t1",
                title="record_lesson_success",
                status="completed",
                raw_output=fail.model_dump(mode="json"),
                is_success_gate=True,
            )
        )
        await pilot.pause()
        chat = app.screen.query_one(ChatStream)
        joined = "\n".join(str(line) for line in getattr(chat, "lines", []))
        assert "Hello from the tutor" in joined
        assert "GATE" in joined or "gate" in joined.lower()
        body = str(app.screen.query_one("#criteria-body").render())
        assert "Gate FAIL" in body
        assert "✓" not in body


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


def test_format_panel_single_criterion_does_not_duplicate_description() -> None:
    statement = "Explain recursion in your own words."
    now = datetime.now(timezone.utc)
    lesson = Lesson(
        id="l1",
        title="Recursion",
        topic="algorithms",
        success_description=statement,
        created_at=now,
        updated_at=now,
        criteria=[
            Criterion(
                id="c1",
                lesson_id="l1",
                kind=CriterionKind.EXPLAIN,
                statement=statement,
                required=True,
                min_evidence_chars=50,
                keywords=["recursion"],
            )
        ],
    )
    body = _format_panel(lesson, None)
    assert statement in body
    assert body.count(statement) == 1
    assert "min 50 chars" in body
    assert "recursion" in body
    assert "○ Gate" not in body


def test_format_panel_legacy_multi_lists_each_statement() -> None:
    now = datetime.now(timezone.utc)
    lesson = Lesson(
        id="l1",
        title="Bayes",
        topic="probability",
        success_description="Master Bayes.",
        created_at=now,
        updated_at=now,
        criteria=[
            Criterion(
                id="c1",
                lesson_id="l1",
                kind=CriterionKind.EXPLAIN,
                statement="Explain Bayes",
                required=True,
                min_evidence_chars=40,
                keywords=["prior"],
                sort_order=0,
            ),
            Criterion(
                id="c2",
                lesson_id="l1",
                kind=CriterionKind.APPLY,
                statement="Compute a posterior",
                required=True,
                min_evidence_chars=40,
                keywords=["posterior"],
                sort_order=1,
            ),
        ],
    )
    body = _format_panel(lesson, None)
    assert "Master Bayes." in body
    assert "Explain Bayes" in body
    assert "Compute a posterior" in body
    fail = GateResult(
        accepted=False,
        lesson_id="l1",
        unmet=[UnmetCriterion(criterion_id="c2", reason="too short")],
    )
    failed = _format_panel(lesson, fail)
    assert "Gate FAIL" in failed
    assert "✗" in failed
    assert "too short" in failed


def test_criteria_mark_fail_is_not_all_green() -> None:
    criterion = Criterion(
        id="c1",
        lesson_id="l1",
        kind=CriterionKind.EXPLAIN,
        statement="Explain it",
        required=True,
    )
    fail = GateResult(
        accepted=False,
        lesson_id="l1",
        unmet=[UnmetCriterion(criterion_id=None, reason="evidence list is empty")],
        message="Success criteria were not met.",
    )
    assert "○" in _mark(criterion, fail)
    assert "✓" not in _mark(criterion, fail)
    unmet = GateResult(
        accepted=False,
        lesson_id="l1",
        unmet=[UnmetCriterion(criterion_id="c1", reason="too short")],
    )
    assert "✗" in _mark(criterion, unmet)
    passed = GateResult(accepted=True, lesson_id="l1")
    assert "✓" in _mark(criterion, passed)


def test_parse_gate_result_unwraps_mcp_content_array() -> None:
    payload = {
        "content": [
            {
                "type": "text",
                "text": (
                    '{"accepted": true, "already_banked": false, '
                    '"lesson_id": "xyz", "unmet": [], "completion_id": "c1", '
                    '"message": "Lesson banked."}'
                ),
            }
        ]
    }
    result = parse_gate_result(payload)
    assert result is not None
    assert result.accepted is True
    assert result.lesson_id == "xyz"
    assert result.completion_id == "c1"


def test_parse_gate_result_unwraps_fenced_json() -> None:
    payload = {
        "text": (
            "```json\n"
            '{"accepted": false, "already_banked": false, '
            '"lesson_id": "abc", "unmet": [], "message": "no"}\n'
            "```"
        )
    }
    result = parse_gate_result(payload)
    assert result is not None
    assert result.accepted is False
    assert result.lesson_id == "abc"


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
