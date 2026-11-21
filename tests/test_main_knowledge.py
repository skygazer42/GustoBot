"""Application exposes unified knowledge APIs without reactivating retired engines."""

import importlib
import runpy
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


def test_application_has_no_lightrag_query_endpoints():
    main = importlib.import_module("gustobot.main")
    paths = main.application.openapi()["paths"]
    assert not any("lightrag" in path for path in paths)
    assert "/api/v1/ontology/facts" in paths
    assert "/api/v1/knowledge/documents" in paths


@pytest.mark.asyncio
@pytest.mark.parametrize("with_web", [False, True])
async def test_application_serves_packaged_web_alongside_api(tmp_path, with_web):
    main = importlib.import_module("gustobot.main")
    entrypoint = tmp_path / "gustobot" / "main.py"
    entrypoint.parent.mkdir()
    assert main.__file__ is not None
    shutil.copyfile(Path(main.__file__), entrypoint)

    if with_web:
        web_dist = tmp_path / "web_dist"
        (web_dist / "assets").mkdir(parents=True)
        (web_dist / "index.html").write_text("<title>Public recipes</title>", encoding="utf-8")
        (web_dist / "admin.html").write_text("<title>Knowledge admin</title>", encoding="utf-8")
        (web_dist / "assets" / "main.js").write_text("export {};", encoding="utf-8")

    application = runpy.run_path(str(entrypoint))["application"]
    # HTTP routing can be exercised without opening a database connection.
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        home = await client.get("/?page=workspace")
        if with_web:
            assert home.status_code == 200
            assert home.text == "<title>Public recipes</title>"
            assert (await client.get("/admin.html")).text == "<title>Knowledge admin</title>"
            assert (await client.get("/assets/main.js")).text == "export {};"
        else:
            assert home.status_code == 307
            assert home.headers["location"] == "/docs"
        assert (await client.get("/docs")).status_code == 200
        assert (await client.get("/health")).json()["status"] == "healthy"
        assert (await client.get("/api")).json()["docs"] == "/docs"


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
