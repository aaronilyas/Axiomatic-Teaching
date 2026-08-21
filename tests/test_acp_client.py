"""ACP client round-trip against the in-repo echo agent."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("acp", reason="agent-client-protocol is not installed")

from axiomatic_teaching.acp_client.events import StreamChunk, ToolCallEvent
from axiomatic_teaching.acp_client.grok import GrokSession, axiomatic_mcp_ready
from axiomatic_teaching.config import Settings

_TIMEOUT = 20

_HOST_RULES = (
    "# Pedagogy rules\n\n"
    "#### 11111111-2222-3333-4444-555555555555\n"
    "- **id:** 11111111-2222-3333-4444-555555555555\n"
    "- **min_evidence_chars:** 40\n"
    "- **keywords:** posterior, likelihood\n"
)
_SHORT_KICKOFF = (
    "Begin the lesson titled Fractions. On this first tutor turn, (1) ask one "
    "diagnostic question and (2) you MUST call present_lesson_html in the same turn."
)


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


def _prompt_text(prompt: object) -> str:
    blocks = prompt
    if isinstance(prompt, dict):
        blocks = prompt.get("prompt") or []
    parts: list[str] = []
    for block in blocks or []:
        if isinstance(block, str):
            parts.append(block)
            continue
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
            continue
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def test_wrap_kickoff_is_gone() -> None:
    import axiomatic_teaching.acp_client.grok as grok_mod

    assert not hasattr(grok_mod, "_wrap_kickoff")


def test_axiomatic_mcp_ready_from_status_and_tools() -> None:
    assert axiomatic_mcp_ready(
        "x.ai/mcp/server_status",
        {"name": "axiomatic", "status": "ready"},
    )
    assert axiomatic_mcp_ready(
        "_x.ai/mcp/server_status",
        {
            "name": "axiomatic",
            "status": "ready",
            "tools": [{"name": "present_lesson_html"}],
        },
    )
    assert axiomatic_mcp_ready(
        "x.ai/mcp/servers_updated",
        {
            "servers": [
                {
                    "name": "axiomatic",
                    "session": {"status": "ready", "tools": ["present_lesson_html"]},
                }
            ]
        },
    )
    assert not axiomatic_mcp_ready(
        "x.ai/mcp/server_status",
        {"name": "github", "status": "ready"},
    )
    assert not axiomatic_mcp_ready("x.ai/models", {"name": "axiomatic"})


@pytest.mark.asyncio
async def test_start_first_prompt_is_short_kickoff_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXIOMATIC_HOME", str(tmp_path))
    captured: dict[str, object] = {}

    class FakeConn:
        async def initialize(self, **kwargs: object) -> None:
            return None

        async def new_session(self, **kwargs: object) -> SimpleNamespace:
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="sess-test")

        async def prompt(self, **kwargs: object) -> None:
            captured["prompt"] = kwargs

        async def close(self) -> None:
            return None

        async def cancel(self, **kwargs: object) -> None:
            return None

    class FakeProc:
        stdin = object()
        stdout = object()
        returncode = 0
        pid = 1

    async def fake_exec(*_args: object, **_kwargs: object) -> FakeProc:
        return FakeProc()

    def fake_connect(_client: object, _stdin: object, _stdout: object) -> FakeConn:
        captured["client"] = _client
        return FakeConn()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr("acp.connect_to_agent", fake_connect)

    settings = Settings.from_cli(demo=True, db=tmp_path / "axiomatic.db")
    session = GrokSession(settings, on_event=lambda _e: None, lesson_id="L")
    try:
        await session.start("L", _HOST_RULES, _SHORT_KICKOFF)
    finally:
        await session.shutdown()

    ns = captured["new_session"]
    assert isinstance(ns, dict)
    assert ns["rules"] == _HOST_RULES
    assert ns["yoloMode"] is True
    prompt = captured["prompt"]
    assert isinstance(prompt, dict)
    joined = _prompt_text(prompt)
    assert joined == _SHORT_KICKOFF
    assert "<axiomatic-context>" not in joined
    assert "# Pedagogy rules" not in joined
    assert "min_evidence_chars" not in joined
    assert "11111111-2222-3333-4444-555555555555" not in joined
    assert "posterior" not in joined
    assert "likelihood" not in joined


@pytest.mark.asyncio
async def test_start_waits_for_mcp_ready_then_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import axiomatic_teaching.acp_client.grok as grok_mod

    monkeypatch.setenv("AXIOMATIC_HOME", str(tmp_path))
    monkeypatch.setattr(grok_mod, "_is_echo", lambda _settings: False)
    monkeypatch.setattr(grok_mod, "_agent_command", lambda _settings: ("grok", ["agent"]))
    monkeypatch.setattr(grok_mod, "_MCP_READY_TIMEOUT", 2.0)
    captured: dict[str, object] = {}
    order: list[str] = []

    class FakeConn:
        async def initialize(self, **kwargs: object) -> None:
            return None

        async def new_session(self, **kwargs: object) -> SimpleNamespace:
            order.append("new_session")
            client = captured["client"]
            await client.ext_notification(  # type: ignore[union-attr]
                "x.ai/mcp/server_status",
                {
                    "name": "axiomatic",
                    "status": "ready",
                    "tools": [{"name": "present_lesson_html"}],
                },
            )
            return SimpleNamespace(session_id="sess-mcp")

        async def prompt(self, **kwargs: object) -> None:
            order.append("prompt")
            captured["prompt"] = kwargs

        async def close(self) -> None:
            return None

        async def cancel(self, **kwargs: object) -> None:
            return None

    class FakeProc:
        stdin = object()
        stdout = object()
        returncode = 0
        pid = 1

    async def fake_exec(*_args: object, **_kwargs: object) -> FakeProc:
        return FakeProc()

    def fake_connect(client: object, _stdin: object, _stdout: object) -> FakeConn:
        captured["client"] = client
        return FakeConn()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr("acp.connect_to_agent", fake_connect)

    settings = Settings.from_cli(demo=False, db=tmp_path / "axiomatic.db")
    session = GrokSession(settings, on_event=lambda _e: None, lesson_id="L")
    try:
        await asyncio.wait_for(session.start("L", _HOST_RULES, _SHORT_KICKOFF), timeout=5)
    finally:
        await session.shutdown()

    assert order == ["new_session", "prompt"]
    assert _prompt_text(captured["prompt"]) == _SHORT_KICKOFF


@pytest.mark.asyncio
async def test_start_prompts_after_mcp_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import axiomatic_teaching.acp_client.grok as grok_mod

    monkeypatch.setenv("AXIOMATIC_HOME", str(tmp_path))
    monkeypatch.setattr(grok_mod, "_is_echo", lambda _settings: False)
    monkeypatch.setattr(grok_mod, "_agent_command", lambda _settings: ("grok", ["agent"]))
    monkeypatch.setattr(grok_mod, "_MCP_READY_TIMEOUT", 0.05)

    captured: dict[str, object] = {}

    class FakeConn:
        async def initialize(self, **kwargs: object) -> None:
            return None

        async def new_session(self, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(session_id="sess-timeout")

        async def prompt(self, **kwargs: object) -> None:
            captured["prompt"] = kwargs

        async def close(self) -> None:
            return None

        async def cancel(self, **kwargs: object) -> None:
            return None

    class FakeProc:
        stdin = object()
        stdout = object()
        returncode = 0
        pid = 1

    async def fake_exec(*_args: object, **_kwargs: object) -> FakeProc:
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr("acp.connect_to_agent", lambda *_a, **_k: FakeConn())

    settings = Settings.from_cli(demo=False, db=tmp_path / "axiomatic.db")
    session = GrokSession(settings, on_event=lambda _e: None, lesson_id="L")
    try:
        await asyncio.wait_for(session.start("L", _HOST_RULES, _SHORT_KICKOFF), timeout=5)
    finally:
        await session.shutdown()

    assert "prompt" in captured
    assert _prompt_text(captured["prompt"]) == _SHORT_KICKOFF


@pytest.mark.asyncio
async def test_echo_roundtrip_does_not_leak_host_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXIOMATIC_HOME", str(tmp_path))
    events: list[object] = []
    settings = Settings.from_cli(demo=True, db=tmp_path / "axiomatic.db")
    session = GrokSession(settings, on_event=events.append, lesson_id="lesson-echo")

    async def _run() -> None:
        try:
            await session.start("lesson-echo", _HOST_RULES, _SHORT_KICKOFF)
            after_start = [event for event in events if isinstance(event, StreamChunk)]
            leaked = "\n".join(event.text for event in after_start)
            assert "<axiomatic-context>" not in leaked
            assert "# Pedagogy rules" not in leaked
            assert "min_evidence_chars" not in leaked
            assert "posterior, likelihood" not in leaked
            assert "11111111-2222-3333-4444-555555555555" not in leaked
            assert _SHORT_KICKOFF not in leaked
            assert any("Demo agent" in event.text for event in after_start)
            presents = [
                event
                for event in events
                if isinstance(event, ToolCallEvent)
                and (event.is_present_html or event.is_success_gate)
            ]
            assert not presents, f"demo echo must not fake present/gate, got {presents!r}"
            await session.send("hello from the learner")
            after_send = [event for event in events if isinstance(event, StreamChunk)]
            assert any("hello from the learner" in event.text for event in after_send)
        finally:
            await session.shutdown()

    await asyncio.wait_for(_run(), timeout=_TIMEOUT)


@pytest.mark.asyncio
async def test_client_detects_present_by_html_payload_not_title() -> None:
    from acp.schema import ToolCallStart, ToolCallUpdate

    from axiomatic_teaching.acp_client.client_impl import AxiomaticClient

    events: list[object] = []
    client = AxiomaticClient(events.append)
    await client.session_update(
        "sess",
        ToolCallStart(
            session_update="tool_call",
            tool_call_id="fig1",
            title="Lesson figure",
            status="pending",
            raw_input={"html": "<p>Hi</p>", "title": "Fig"},
        ),
    )
    await client.session_update(
        "sess",
        ToolCallUpdate(
            tool_call_id="fig1",
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
    assert completed[0].title == "Lesson figure"
    assert completed[0].raw_input.get("html") == "<p>Hi</p>"
    assert completed[0].is_present_html is True
    assert completed[0].is_success_gate is False
