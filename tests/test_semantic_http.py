"""Formal shape violations stay machine readable at public knowledge boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts
from gustobot.interfaces.http import knowledge_router, ontology_router


@pytest.mark.asyncio
async def test_ontology_validate_executes_quantity_shape_and_returns_violation_report():
    app = FastAPI()
    app.include_router(ontology_router.router)
    graph = recipe_to_facts("糖水", {"辅料": [["红糖", "-1 g"]]}, domain=get_domain_definition())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/ontology/validate", json=graph.model_dump(mode="json"))
    assert response.status_code == 422
    report = response.json()["detail"]["semantic_report"]
    assert not report["conforms"]
    assert report["ontology_version"] == get_domain_definition().version
    assert any(issue["path"].endswith("#value") for issue in report["issues"] if issue["path"])


@pytest.mark.asyncio
async def test_explicit_recipe_import_preserves_semantic_error_without_creating_a_job():
    from gustobot.infrastructure.knowledge.semantic_runtime import get_semantic_runtime

    domain = get_domain_definition()
    graph = recipe_to_facts("糖水", {"辅料": [["糖", "-2 g"]]}, domain=domain)
    runtime = get_semantic_runtime(domain)
    assert runtime is not None
    with pytest.raises(ValueError) as raised:
        runtime.validate_input(graph)
    service = SimpleNamespace(ingest_recipe=AsyncMock(side_effect=raised.value))
    app = FastAPI()
    app.include_router(knowledge_router.router)
    app.dependency_overrides[knowledge_router.get_ingestion_service] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/knowledge/recipes", json={"name": "糖水", "record": {"辅料": [["糖", "-2 g"]]}}
        )
    assert response.status_code == 422
    assert response.json()["detail"]["semantic_report"]["conforms"] is False
    assert "receipt" not in response.json()["detail"]
