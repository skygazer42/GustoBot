"""
Database configuration helpers and session utilities.
"""

from contextlib import contextmanager
from importlib import import_module
from typing import Dict, Generator, Iterator

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from gustobot.config import settings

_DEFAULT_LOG_ECHO = bool(settings.DEBUG)

_connect_args: Dict[str, bool] = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    echo=_DEFAULT_LOG_ECHO,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

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

    If `create_all` is True the metadata for all models is created.
    """
    if create_all:
        # Lazy import to avoid circular dependencies during startup.
        import_module("gustobot.infrastructure.persistence.db.models")

        Base.metadata.create_all(bind=engine)


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
        _rollback_after_failure(session)
        try:
            session.close()
        except Exception:
            logger.exception("Close failed while handling a database operation error")
        raise
    else:
        session.close()


def _rollback_after_failure(session: Session) -> None:
    """Rollback at the transaction owner without replacing its active error."""
    try:
        session.rollback()
    except Exception:
        logger.exception("Rollback failed while handling a database operation error")


def commit_session(session: Session) -> None:
    """Commit a CRUD-owned transaction and leave a failed session reusable."""
    try:
        session.commit()
    except BaseException:
        _rollback_after_failure(session)
        raise
