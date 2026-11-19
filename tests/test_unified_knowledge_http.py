"""Knowledge APIs expose explicit ingestion and question contracts."""

import httpx
import pytest
from fastapi import FastAPI

from gustobot.interfaces.http import knowledge_router


@pytest.mark.asyncio
async def test_explicit_knowledge_api_does_not_expose_retired_graph_endpoints():
    application = FastAPI()
    application.include_router(knowledge_router.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        graph = await client.get("/knowledge/graph")
        answer = await client.post("/knowledge/graph/qa", json={"query": "关联是什么"})
    assert graph.status_code == answer.status_code == 404
    paths = application.openapi()["paths"]
    assert "/knowledge/documents" in paths
    assert "/knowledge/recipes" in paths
    assert "/knowledge/query" in paths
