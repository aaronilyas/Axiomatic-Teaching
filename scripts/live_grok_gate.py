"""Live Grok ACP smoke: insufficient then sufficient record_lesson_success."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from axiomatic_teaching.acp_client.events import StreamChunk, ToolCallEvent
from axiomatic_teaching.acp_client.grok import GrokSession
from axiomatic_teaching.config import Settings
from axiomatic_teaching.db.repository import create_repository
from axiomatic_teaching.models import CriterionDraft, CriterionKind, NewLessonSpec


async def main() -> int:
    td = Path(tempfile.mkdtemp(prefix="axiomatic_gate_"))
    db = td / "axiomatic.db"
    os.environ["AXIOMATIC_HOME"] = str(td)
    os.environ["AXIOMATIC_DB"] = str(db)
    settings = Settings.from_cli(db=db, demo=False, agent="grok")
    repo = create_repository(db)
    lesson = repo.create_lesson(
        NewLessonSpec(
            title="Hash tables",
            topic="data-structures",
            success_description="Explain hashing plus collisions.",
            criteria=[
                CriterionDraft(
                    kind=CriterionKind.EXPLAIN,
                    statement="Explain hashing and collision handling.",
                    required=True,
                    min_evidence_chars=40,
                    keywords=["collision"],
                )
            ],
        )
    )
    os.environ["AXIOMATIC_LESSON_ID"] = lesson.id
    print("lesson", lesson.id)
    print("criterion", lesson.criteria[0].id)
    print("db", db)

    events: list[object] = []
    session = GrokSession(settings, on_event=events.append, lesson_id=lesson.id)
    prompt = (
        "This is a verification run, not a real student. "
        "First call get_lesson_criteria. "
        "Then call record_lesson_success with evidence text 'no' and met=true "
        "for the required criterion_id. "
        "After that tool returns, call record_lesson_success AGAIN with evidence "
        "that is at least 80 characters, includes the word collision, and met=true. "
        "Do not write files. After both tool calls, summarize the two tool results "
        "in one short paragraph."
    )
    try:
        await asyncio.wait_for(
            session.start(
                lesson.id,
                "You MUST use the axiomatic MCP tools. "
                "The only way to bank a lesson is record_lesson_success.",
                "Ready.",
            ),
            timeout=90,
        )
        print("session", session.session_id)
        await asyncio.wait_for(session.send(prompt), timeout=180)
    finally:
        await session.shutdown()

    tools = [event for event in events if isinstance(event, ToolCallEvent)]
    print("tool_events", len(tools))
    for event in tools:
        print("TOOL", event.title, event.status, event.is_success_gate, event.raw_output)
    text = "".join(event.text for event in events if isinstance(event, StreamChunk))
    print("TEXT_TAIL", text[-1500:])
    fresh = repo.get_lesson(lesson.id)
    completion = repo.get_completion(lesson.id)
    print("STATUS", None if fresh is None else fresh.status)
    print("COMPLETION", None if completion is None else completion.id)
    from axiomatic_teaching.db.engine import session_scope
    from axiomatic_teaching.db.orm import GateAttemptRow
    from sqlalchemy import select

    attempts = []
    with session_scope(repo.engine) as session:
        attempts = list(
            session.scalars(
                select(GateAttemptRow)
                .where(GateAttemptRow.lesson_id == lesson.id)
                .order_by(GateAttemptRow.created_at.asc())
            )
        )
    print("GATE_ATTEMPTS", len(attempts))
    for row in attempts:
        print("ATTEMPT", row.accepted, row.result_json[:200])
    if not attempts:
        print("FAIL: Grok never called record_lesson_success")
        return 2
    if attempts[0].accepted:
        print("WARN: first attempt was accepted; Grok skipped the insufficient-evidence call")
    if completion is None:
        print("FAIL: lesson was not banked after the sufficient call")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
