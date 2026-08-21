"""Minimal ACP agent for --demo. Echoes the user with a Socratic probe; does not bank."""

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
    update_agent_message_text,
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

_TUTOR_REPLY = (
    "Demo agent (no Grok). I cannot bank a lesson — only record_lesson_success "
    "against real Grok Build can. What is the core idea in your own words?"
)

_HOST_PROMPT_MARKERS = (
    "<axiomatic-context>",
    "# Pedagogy rules",
    "min_evidence_chars",
    "<user_info>",
    "<human_rules>",
)


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
        echo = user_text.strip() or "(empty)"
        if not _is_host_kickoff(echo):
            await self._conn.session_update(
                session_id=session_id,
                update=update_agent_message_text(echo),
            )
        await self._conn.session_update(
            session_id=session_id,
            update=update_agent_message_text(_TUTOR_REPLY),
        )
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        return None


def _is_host_kickoff(text: str) -> bool:
    """Do not echo host kickoff / assembled context as tutor text."""
    if any(marker in text for marker in _HOST_PROMPT_MARKERS):
        return True
    lower = text.lower()
    if "present_lesson_html" in lower:
        return True
    if "diagnostic question" in lower:
        return True
    if "begin the lesson titled" in lower:
        return True
    return False


async def main() -> None:
    await run_agent(EchoAgent())


if __name__ == "__main__":
    asyncio.run(main())
