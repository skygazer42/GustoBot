"""Initial application tables, including existing conversations and new ingestion metadata."""

from importlib import import_module

from sqlalchemy.engine import Connection

from gustobot.infrastructure.core.database import Base

revision = "0001_application_schema"
description = "Initialize application, chat, asset, source and ingestion tables"


def upgrade(connection: Connection) -> None:
    """Create the initial application schema and its required indexes."""
    # Existing tables and rows are preserved. MySQL DDL may commit independently,
    # so checkfirst makes a partially completed initial revision safe to rerun.
    import_module("gustobot.infrastructure.persistence.db.models")
    Base.metadata.create_all(connection, checkfirst=True)
