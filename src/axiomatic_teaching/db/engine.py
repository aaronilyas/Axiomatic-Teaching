"""SQLite engine setup: WAL, foreign keys, and session scope."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

SCHEMA_VERSION = 1
_SESSIONMAKERS: dict[int, sessionmaker[Session]] = {}


def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()
    # Let SQLAlchemy emit BEGIN IMMEDIATE via the begin hook below.
    dbapi_connection.isolation_level = None


def _begin_immediate(connection) -> None:
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def init_engine(path: Path | str) -> Engine:
    """Create a SQLite engine at `path`, enable FK/WAL, and create tables."""
    from axiomatic_teaching.db.orm import Base

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        "sqlite:///" + db_path.resolve().as_posix(),
        future=True,
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 5.0},
    )
    event.listen(engine, "connect", _set_sqlite_pragma)
    event.listen(engine, "begin", _begin_immediate)
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


def _sessionmaker_for(engine: Engine) -> sessionmaker[Session]:
    key = id(engine)
    factory = _SESSIONMAKERS.get(key)
    if factory is None:
        factory = sessionmaker(
            bind=engine,
            autoflush=True,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        _SESSIONMAKERS[key] = factory
    return factory


def dispose_engine(engine: Engine) -> None:
    """Dispose the engine and drop the cached sessionmaker."""
    _SESSIONMAKERS.pop(id(engine), None)
    engine.dispose()


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, rollback on error, always close the session."""
    session = _sessionmaker_for(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
