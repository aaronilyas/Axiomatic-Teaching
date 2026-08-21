"""ACP client round-trip against the in-repo echo agent."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("acp", reason="agent-client-protocol is not installed")

from axiomatic_teaching.acp_client.events import StreamChunk, ToolCallEvent
from axiomatic_teaching.acp_client.grok import GrokSession
from axiomatic_teaching.config import Settings

_TIMEOUT = 20


@pytest.mark.asyncio
async def test_grok_session_echo_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXIOMATIC_HOME", str(tmp_path))
    events: list[object] = []
    settings = Settings.from_cli(demo=True, db=tmp_path / "axiomatic.db")
    session = GrokSession(settings, on_event=events.append, lesson_id="lesson-echo")

    async def _run() -> None:
        try:
            await session.start(
                "lesson-echo",
                rules="Be a concise tutor.",
                kickoff_prompt="Hello, let's study fractions.",
            )
            await session.send("What is 1/2 plus 1/4?")
            chunks = [event for event in events if isinstance(event, StreamChunk)]
            assert chunks, f"expected at least one StreamChunk, got {events!r}"
            assert any(event.text for event in chunks)
            assert session.session_id
            assert session.busy is False
            gates = [
                event
                for event in events
                if isinstance(event, ToolCallEvent) and event.is_success_gate
            ]
            assert not gates, f"demo echo must not fake record_lesson_success, got {gates!r}"
            presents = [
                event
                for event in events
                if isinstance(event, ToolCallEvent)
                and (
                    event.is_present_html
                    or "present_lesson_html"
                    in f"{event.title} {event.kind} {event.tool_call_id}".lower()
                )
            ]
            assert not presents, f"demo echo must not fake present_lesson_html, got {presents!r}"
        finally:
            await session.shutdown()
            assert session.busy is False
            assert session.session_id is None

    await asyncio.wait_for(_run(), timeout=_TIMEOUT)


@pytest.mark.asyncio
async def test_client_merges_tool_call_input_across_patches() -> None:
    from acp.schema import ToolCallStart, ToolCallUpdate

    from axiomatic_teaching.acp_client.client_impl import AxiomaticClient

    events: list[object] = []
    client = AxiomaticClient(events.append)
    await client.session_update(
        "sess",
        ToolCallStart(
            session_update="tool_call",
            tool_call_id="tc1",
            title="present_lesson_html",
            status="pending",
            raw_input={"html": "<p>keep me</p>", "title": "Fig"},
        ),
    )
    await client.session_update(
        "sess",
        ToolCallUpdate(
            tool_call_id="tc1",
            status="completed",
            raw_output={"ok": True, "open_status": "host_pending"},
        ),
    )
    completed = [
        event
        for event in events
        if isinstance(event, ToolCallEvent) and event.status == "completed"
    ]
    assert len(completed) == 1
    assert completed[0].raw_input.get("html") == "<p>keep me</p>"
    assert completed[0].title == "present_lesson_html"
    assert completed[0].is_present_html is True
    assert completed[0].is_success_gate is False
