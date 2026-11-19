"""Application exposes unified knowledge APIs without reactivating retired engines."""

import importlib

import pytest


def test_application_has_no_lightrag_query_endpoints():
    main = importlib.import_module("gustobot.main")
    paths = main.application.openapi()["paths"]
    assert not any("lightrag" in path for path in paths)
    assert "/api/v1/ontology/facts" in paths
    assert "/api/v1/knowledge/documents" in paths


@pytest.mark.asyncio
async def test_startup_checks_migration_revision_instead_of_creating_tables(monkeypatch):
    main = importlib.import_module("gustobot.main")
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from gustobot.infrastructure.core.database import Base
    from migrations import migrate_database

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    try:
        migrate_database(engine)

        def forbidden(*args, **kwargs):
            raise AssertionError("Startup cannot mutate the schema")

        monkeypatch.setattr(main, "engine", engine)
        monkeypatch.setattr(Base.metadata, "create_all", forbidden)
        await main.startup_event()
    finally:
        engine.dispose()
