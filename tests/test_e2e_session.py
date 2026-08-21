"""End-to-end: echo ACP session + MCP success gate against the same SQLite file."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from axiomatic_teaching.acp_client.events import StreamChunk
from axiomatic_teaching.acp_client.grok import GrokSession
from axiomatic_teaching.config import Settings
from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.mcp_server.server import record_lesson_success
from axiomatic_teaching.models import (
    LessonStatus,
    NewLessonSpec,
)

pytest.importorskip("acp", reason="agent-client-protocol is not installed")


@pytest.mark.asyncio
async def test_echo_session_then_gate_pass_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "axiomatic.db"
    monkeypatch.setenv("AXIOMATIC_HOME", str(tmp_path))
    monkeypatch.setenv("AXIOMATIC_DB", str(db))
    settings = Settings.from_cli(db=db, demo=True)
    repository = create_repository(db)
    lesson = repository.create_lesson(
        NewLessonSpec(
            title="Linked lists",
            topic="data-structures",
            success_description="Explain a singly linked list and its next pointer.",
        )
    )
    monkeypatch.setenv("AXIOMATIC_LESSON_ID", lesson.id)

    events: list[object] = []
    session = GrokSession(settings, on_event=events.append, lesson_id=lesson.id)
    await asyncio.wait_for(
        session.start(lesson.id, "Stay in the ZPD.", "Begin the linked-list lesson."),
        timeout=20,
    )
    await asyncio.wait_for(session.send("A node holds a value and a next pointer."), timeout=20)
    chunks = [event for event in events if isinstance(event, StreamChunk) and event.text]
    assert chunks, f"echo session produced no text: {events!r}"
    await session.shutdown()

    rejected = record_lesson_success(
        lesson_id=lesson.id,
        evidence=[{"criterion_id": lesson.criteria[0].id, "text": "short", "met": True}],
    )
    assert rejected["accepted"] is False
    assert repository.get_completion(lesson.id) is None
    assert repository.get_lesson(lesson.id).status == LessonStatus.ACTIVE

    accepted = record_lesson_success(
        lesson_id=lesson.id,
        evidence=[
            {
                "criterion_id": lesson.criteria[0].id,
                "text": (
                    "A singly linked list is a chain of nodes. Each node stores a value "
                    "and a next pointer to the following node, or null at the tail."
                ),
                "met": True,
            }
        ],
        notes="Learner named the next pointer.",
        style_note="Explains with a chain metaphor.",
    )
    assert accepted["accepted"] is True
    assert repository.get_completion(lesson.id) is not None
    assert repository.get_lesson(lesson.id).status == LessonStatus.COMPLETED
    assert repository.get_completion(lesson.id) is not None
    # A second call must not duplicate the completion.
    again = record_lesson_success(
        lesson_id=lesson.id,
        evidence=[
            {
                "criterion_id": lesson.criteria[0].id,
                "text": (
                    "A singly linked list is a chain of nodes. Each node stores a value "
                    "and a next pointer to the following node, or null at the tail."
                ),
                "met": True,
            }
        ],
    )
    assert again["already_banked"] is True
    assert len(repository.list_completions()) == 1
