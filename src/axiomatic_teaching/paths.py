"""Filesystem locations for app data, the SQLite database, logs, and lesson workspaces."""

from __future__ import annotations

import os
from pathlib import Path


APP_DIR_NAME = "AxiomaticTeaching"


def app_data_dir() -> Path:
    """Return the per-user data directory, creating it if needed."""
    override = os.environ.get("AXIOMATIC_HOME")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(root) / APP_DIR_NAME
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        path = Path(xdg) / APP_DIR_NAME if xdg else Path.home() / ".local" / "share" / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    env = os.environ.get("AXIOMATIC_DB")
    if env:
        path = Path(env).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return app_data_dir() / "axiomatic.db"


def log_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lesson_workspace(lesson_id: str) -> Path:
    """Per-lesson cwd handed to Grok Build so it does not wander the source tree."""
    path = app_data_dir() / "lessons" / lesson_id
    path.mkdir(parents=True, exist_ok=True)
    return path
