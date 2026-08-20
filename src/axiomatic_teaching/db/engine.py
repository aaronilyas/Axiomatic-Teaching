"""SQLite engine setup: WAL, foreign keys, and session scope."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

SCHEMA_VERSION = 1


def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_engine(path: Path | str) -> Engine:
    """Create a SQLite engine at `path`, enable FK/WAL, and create tables."""
    from axiomatic_teaching.db.orm import Base

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        "sqlite:///" + db_path.resolve().as_posix(),
        future=True,
        connect_args={"check_same_thread": False, "timeout": 5.0},
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        row = conn.execute(
            text("SELECT version FROM schema_migrations WHERE version = :v"),
            {"v": SCHEMA_VERSION},
        ).first()
        if row is None:
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": SCHEMA_VERSION},
            )
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, rollback on error, always close the session."""
    factory = sessionmaker(
        bind=engine,
        autoflush=True,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
