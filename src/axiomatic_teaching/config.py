"""Runtime configuration for the TUI, ACP client, and MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from axiomatic_teaching.paths import default_db_path, lesson_workspace, log_dir


CONTEXT_CHAR_BUDGET = 6000
RELATED_LESSON_CAP = 5
RELATION_CAP = 8
STYLE_NOTE_CAP = 5
DUE_REVIEW_CAP = 5
DEFAULT_MIN_EVIDENCE_CHARS = 40


@dataclass(slots=True)
class Settings:
    db_path: Path = field(default_factory=default_db_path)
    agent: str = field(default_factory=lambda: os.environ.get("AXIOMATIC_AGENT", "grok"))
    grok_bin: str = field(default_factory=lambda: os.environ.get("AXIOMATIC_GROK_BIN", "grok"))
    demo: bool = False
    context_char_budget: int = CONTEXT_CHAR_BUDGET

    @classmethod
    def from_cli(
        cls,
        *,
        db: str | Path | None = None,
        demo: bool = False,
        agent: str | None = None,
        grok_bin: str | None = None,
    ) -> Settings:
        settings = cls()
        if db is not None:
            settings.db_path = Path(db).expanduser()
            settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        if demo:
            settings.demo = True
            settings.agent = "echo"
        if agent:
            settings.agent = agent
        if grok_bin:
            settings.grok_bin = grok_bin
        return settings

    @property
    def log_dir(self) -> Path:
        return log_dir()

    def workspace_for(self, lesson_id: str) -> Path:
        return lesson_workspace(lesson_id)
