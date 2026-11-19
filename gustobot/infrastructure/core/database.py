"""
Database configuration helpers and session utilities.
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gustobot.config import settings

_DEFAULT_LOG_ECHO = bool(settings.DEBUG)


def create_database_engine(url: str | URL, *, echo: bool = False) -> Engine:
    """Create a lazy application connection pool for the supported MySQL driver."""
    database_url = make_url(url)
    if database_url.drivername != "mysql+pymysql":
        raise ValueError("Application database requires a mysql+pymysql connection URL")
    database_url = database_url.update_query_dict({"charset": "utf8mb4"})
    return create_engine(
        database_url, echo=echo, future=True, pool_pre_ping=True, hide_parameters=True
    )


engine = create_database_engine(settings.DATABASE_URL, echo=_DEFAULT_LOG_ECHO)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Shared mapped metadata; entities declare their own typed fields."""


def init_db(*, create_all: bool = False) -> None:
    """
    Initialize the database engine.

    ``create_all=True`` explicitly applies the versioned schema migrations.
    Importing this module and calling ``init_db()`` never connects or migrates.
    """
    if create_all:
        migrate_database(engine)


def migrate_database(database_engine: Engine) -> list[str]:
    """Apply pending forward migrations and return their revision identifiers."""
    from migrations import migrate_database as apply_migrations

    return apply_migrations(database_engine)


def get_db() -> Generator[Session, None, None]:
    """
    Provide a database session dependency for FastAPI routes.
    """
    with session_scope(commit=False) as db:
        yield db


@contextmanager
def session_scope(*, commit: bool = True) -> Iterator[Session]:
    """
    Context manager that handles commit/rollback automatically.
    """
    session = SessionLocal()
    try:
        yield session
        if commit:
            session.commit()
    except BaseException:
        try:
            rollback_session(session)
        finally:
            try:
                session.close()
            # Cleanup errors must not replace the original transaction failure.
            except Exception:  # noqa: BLE001
                logger.exception("Close failed while handling a database operation error")
        raise
    else:
        session.close()


def rollback_session(session: Session) -> None:
    """Keep the operation error visible; attempt invalidation if rollback fails."""
    try:
        session.rollback()
    # Cleanup errors must not replace the original transaction failure.
    except Exception:  # noqa: BLE001
        logger.exception("Rollback failed while handling a database operation error")
        try:
            session.invalidate()
        # This session is not known to be reusable; its request owner will still close it.
        except Exception:  # noqa: BLE001
            logger.exception(
                "Connection invalidation failed while handling a database operation error"
            )


def commit_session(session: Session) -> None:
    """Commit a CRUD-owned transaction without hiding failed commit or cleanup."""
    try:
        session.commit()
    except BaseException:
        rollback_session(session)
        raise
