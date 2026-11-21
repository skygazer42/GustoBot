"""Align MySQL source/asset/job identity comparisons with Python and the fact graph."""

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.schema import AddConstraint, DropConstraint

from gustobot.infrastructure.persistence.db.models.knowledge import IngestionJob

revision = "0002_exact_knowledge_identity"
description = "Preserve case, accents and trailing spaces in knowledge identifiers"
_COLLATION = "utf8mb4_0900_bin"
_TABLES = ("knowledge_sources", "ingestion_jobs", "uploaded_assets")
_FOREIGN_KEY = "fk_ingestion_jobs_source_version"


def upgrade(connection: Connection) -> None:
    """Add exact domain/source/version identity to stored knowledge records."""
    if connection.dialect.name != "mysql":
        return
    inspector = inspect(connection)
    needs_conversion = {
        table
        for table in _TABLES
        if inspector.get_table_options(table).get("mysql_collate") != _COLLATION
    }
    has_foreign_key = any(
        item["name"] == _FOREIGN_KEY for item in inspector.get_foreign_keys("ingestion_jobs")
    )
    foreign_key = next(
        item
        for item in IngestionJob.metadata.tables["ingestion_jobs"].foreign_key_constraints
        if item.name == _FOREIGN_KEY
    )
    # Both sides of the foreign key must use the same collation. Only this
    # constraint is removed temporarily; no table or row is removed.
    if needs_conversion and has_foreign_key:
        connection.execute(DropConstraint(foreign_key))
        has_foreign_key = False
    for table in _TABLES:
        if table in needs_conversion:
            connection.exec_driver_sql(
                f"ALTER TABLE `{table}` CONVERT TO CHARACTER SET utf8mb4 COLLATE {_COLLATION}"
            )
    # A retry also repairs an interrupted upgrade that converted all tables
    # but stopped before restoring the exact-source constraint.
    if not has_foreign_key:
        connection.execute(AddConstraint(foreign_key))
