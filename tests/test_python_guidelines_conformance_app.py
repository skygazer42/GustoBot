"""Application lifecycle ownership and public response contracts."""

import asyncio
from types import SimpleNamespace

import httpx
import anyio
import pytest

from gustobot import main


@pytest.mark.asyncio
async def test_shutdown_does_not_allocate_unused_services(monkeypatch):
    released = []

    async def close_lightrag():
        released.append("lightrag")

    monkeypatch.setattr(main, "cleanup_lightrag_service", close_lightrag)
    monkeypatch.setattr(
        main, "engine", SimpleNamespace(dispose=lambda: released.append("database"))
    )

    await main.shutdown_event()

    assert released == ["lightrag", "database"]


@pytest.mark.asyncio
async def test_shutdown_releases_other_owners_and_exposes_cleanup_failure(monkeypatch):
    released = []
    original = RuntimeError("index close failed")

    async def close_lightrag():
        released.append("lightrag")
        raise original

    monkeypatch.setattr(main, "cleanup_lightrag_service", close_lightrag)
    monkeypatch.setattr(
        main, "engine", SimpleNamespace(dispose=lambda: released.append("database"))
    )

    with pytest.raises(RuntimeError, match="Application resource cleanup failed") as failure:
        await main.shutdown_event()

    assert failure.value.__cause__ is original
    assert released == ["lightrag", "database"]


@pytest.mark.asyncio
async def test_health_and_api_metadata_publish_explicit_response_schemas():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.application), base_url="http://test"
    ) as client:
        health = await client.get("/health")
        metadata = await client.get("/api")

    assert health.status_code == metadata.status_code == 200
    assert health.json() == {"status": "healthy", "version": main.settings.APP_VERSION}
    assert metadata.json() == {
        "name": main.settings.APP_NAME,
        "version": main.settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
    }
    schemas = main.application.openapi()["components"]["schemas"]
    assert set(schemas["HealthResponse"]["properties"]) == {"status", "version"}
    assert set(schemas["APIInfoResponse"]["properties"]) == {"name", "version", "status", "docs"}


@pytest.mark.asyncio
async def test_shutdown_propagates_cancellation_after_releasing_other_owners(monkeypatch):
    released = []

    async def cancelled_cleanup():
        raise asyncio.CancelledError("shutdown cancelled")

    monkeypatch.setattr(main, "cleanup_lightrag_service", cancelled_cleanup)
    monkeypatch.setattr(
        main, "engine", SimpleNamespace(dispose=lambda: released.append("database"))
    )
    with pytest.raises(asyncio.CancelledError, match="shutdown cancelled"):
        await main.shutdown_event()
    assert released == ["database"]


@pytest.mark.asyncio
async def test_shutdown_reports_cooperative_cleanup_timeout_and_releases_pool(monkeypatch):
    released = []

    async def hanging_cleanup():
        await anyio.sleep_forever()

    monkeypatch.setattr(main, "cleanup_lightrag_service", hanging_cleanup)
    monkeypatch.setattr(main, "RESOURCE_CLEANUP_TIMEOUT", 0.01)
    monkeypatch.setattr(
        main, "engine", SimpleNamespace(dispose=lambda: released.append("database"))
    )
    with anyio.fail_after(0.25):
        with pytest.raises(RuntimeError, match="Application resource cleanup failed") as failure:
            await main.shutdown_event()
    assert isinstance(failure.value.__cause__, TimeoutError)
    assert released == ["database"]
