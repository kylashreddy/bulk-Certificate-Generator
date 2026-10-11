"""Engine and session factory."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


def build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        # Worker threads share the engine, so SQLite's same-thread check must go.
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
        event.listen(engine, "connect", _configure_sqlite_connection)
        return engine
    return create_engine(database_url, pool_pre_ping=True)


def _configure_sqlite_connection(
    dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry
) -> None:
    cursor = dbapi_connection.cursor()
    # WAL lets API reads proceed while a worker thread is writing; busy_timeout
    # makes concurrent writers wait instead of failing with "database is locked".
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False lets services return ORM objects after committing.
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """One unit of work for background code: commit on success, roll back on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
