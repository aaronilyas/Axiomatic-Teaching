"""Shared pytest fixtures. SQLite paths use tmp_path (Windows-safe)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "axiomatic.db"


@pytest.fixture
def repository(db_path: Path):
    try:
        from axiomatic_teaching.db.repository import create_repository
    except ImportError:
        pytest.skip("create_repository is not implemented yet")

    try:
        from axiomatic_teaching.db.engine import init_engine
    except ImportError:
        init_engine = None
    if init_engine is not None:
        init_engine(db_path)

    return create_repository(db_path)
