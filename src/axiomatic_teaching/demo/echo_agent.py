"""Minimal ACP agent that echoes the user and emits a fake success-gate tool call."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from acp import (
    Agent,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    PROTOCOL_VERSION,
    run_agent,
    start_tool_call,
    update_agent_message_text,
    update_tool_call,
)
from acp.interfaces import Client
from acp.schema import (
    AudioContentBlock,
    ClientCapabilities,
    EmbeddedResourceContentBlock,
    HttpMcpServer,
    ImageContentBlock,
    Implementation,
    McpServerStdio,
    ResourceContentBlock,
    SseMcpServer,
    TextContentBlock,
)

_TUTOR_REPLY = "Got it. Let's keep going — try restating the key idea in your own words."


def _block_text(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("text") or "")
    return str(getattr(block, "text", "") or "")


class EchoAgent(Agent):
    _conn: Client

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(protocol_version=PROTOCOL_VERSION)

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        return NewSessionResponse(session_id=uuid4().hex)

    async def prompt(
        self,
        session_id: str,
        prompt: list[
            TextContentBlock
            | ImageContentBlock
            | AudioContentBlock
            | ResourceContentBlock
            | EmbeddedResourceContentBlock
        ],
        **kwargs: Any,
    ) -> PromptResponse:
        user_text = "\n".join(text for block in prompt if (text := _block_text(block)))
        echo = user_text or "(empty)"
        await self._conn.session_update(
            session_id=session_id,
            update=update_agent_message_text(echo),
        )
        await self._conn.session_update(
            session_id=session_id,
            update=update_agent_message_text(_TUTOR_REPLY),
        )
        tool_call_id = f"echo-success-{uuid4().hex[:8]}"
        await self._conn.session_update(
            session_id=session_id,
            update=start_tool_call(
                tool_call_id,
                "record_lesson_success",
                kind="other",
                status="pending",
                raw_input={"name": "record_lesson_success"},
            ),
        )
        await self._conn.session_update(
            session_id=session_id,
            update=update_tool_call(
                tool_call_id,
                title="record_lesson_success",
                kind="other",
                status="completed",
                raw_output={"ok": True},
            ),
        )
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        return None


async def main() -> None:
    await run_agent(EchoAgent())


if __name__ == "__main__":
    asyncio.run(main())
