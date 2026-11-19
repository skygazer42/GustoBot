"""Forward-only schema migrations, invoked explicitly by the migration CLI."""

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    func,
    insert,
    inspect,
    select,
)
from sqlalchemy.engine import Engine

from migrations.versions import (
    v0001_application_schema,
    v0002_exact_knowledge_identity,
    v0003_semantic_index_publication,
)

schema_migrations = Table(
    "schema_migrations",
    MetaData(),
    Column("version", String(64), primary_key=True),
    Column("description", String(255), nullable=False),
    Column("applied_at", DateTime, nullable=False, server_default=func.now()),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
)

MIGRATIONS = (
    v0001_application_schema,
    v0002_exact_knowledge_identity,
    v0003_semantic_index_publication,
)


def check_database_schema(engine: Engine) -> None:
    """Read readiness without creating tables or recording migrations."""
    with engine.connect() as connection:
        if not inspect(connection).has_table("schema_migrations"):
            raise RuntimeError("Application schema is missing; run scripts/migrate_database.py")
        applied = set(connection.execute(select(schema_migrations.c.version)).scalars())
    if applied != {migration.revision for migration in MIGRATIONS}:
        raise RuntimeError("Application schema revisions differ; run the matching migrate release")


def migrate_database(engine: Engine) -> list[str]:
    """Record a revision only after its schema changes succeed; reruns preserve data."""
    applied_now = []
    with engine.begin() as connection:
        schema_migrations.create(connection, checkfirst=True)
        applied = set(connection.execute(select(schema_migrations.c.version)).scalars())
        known = {migration.revision for migration in MIGRATIONS}
        if applied - known:
            raise RuntimeError(
                "Database has unknown schema revisions; use a matching application release"
            )
        for migration in MIGRATIONS:
            if migration.revision in applied:
                continue
            migration.upgrade(connection)
            connection.execute(
                insert(schema_migrations).values(
                    version=migration.revision, description=migration.description
                )
            )
            applied_now.append(migration.revision)
    return applied_now
