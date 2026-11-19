"""Typed ontology HTTP endpoints preserve facts and borrow the application graph store."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import (
    DomainDefinition,
    ExtractedKnowledge,
    KnowledgeGraph,
)
from gustobot.infrastructure.knowledge.graph_store import (
    FactResult,
    GraphWriteResult,
    Neo4jGraphStore,
)
from gustobot.interfaces.http import ontology_router


@pytest.fixture
def domain():
    return DomainDefinition.model_validate(
        {
            "id": "equipment-http",
            "name": "设备维护",
            "description": "设备事实",
            "document_scope": "设备手册",
            "entity_types": {
                "Equipment": {
                    "description": "设备",
                    "properties": {"serial": {"type": "string", "required": True}},
                },
                "Component": {"description": "部件", "properties": {}},
            },
            "relation_types": {
                "HAS_COMPONENT": {
                    "description": "设备包含部件",
                    "source_types": ["Equipment"],
                    "target_types": ["Component"],
                }
            },
        }
    )


@pytest.fixture
def graph():
    evidence = [{"source_id": "manual", "quote": "泵 A 包含轴承 B"}]
    return KnowledgeGraph.model_validate(
        {
            "entities": [
                {
                    "id": "pump-a",
                    "type": "Equipment",
                    "name": "泵 A",
                    "properties": {"serial": "A"},
                    "evidence": evidence,
                },
                {"id": "bearing-b", "type": "Component", "name": "轴承 B", "evidence": evidence},
            ],
            "relations": [
                {
                    "id": "pump-bearing",
                    "source_id": "pump-a",
                    "target_id": "bearing-b",
                    "type": "HAS_COMPONENT",
                    "evidence": evidence,
                }
            ],
            "sources": [{"id": "manual", "text": "泵 A 包含轴承 B。", "uri": "manual.pdf"}],
        }
    )


@pytest.fixture
def http_app(monkeypatch, domain, graph):
    app = FastAPI()
    app.include_router(ontology_router.router)
    result = FactResult(
        **graph.model_dump(), total=1, truncated=False, ontology_version=domain.version
    )
    store = SimpleNamespace(
        upsert=AsyncMock(return_value=GraphWriteResult(entities=2, relations=1, sources=1)),
        query=AsyncMock(return_value=result),
        close=AsyncMock(),
    )
    model = Mock()
    structured = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=ExtractedKnowledge(entities=graph.entities, relations=graph.relations)
        )
    )
    model.with_structured_output.return_value = structured
    service = OntologyService(domain, model=model, graph_store=cast(Neo4jGraphStore, store))
    app.dependency_overrides[ontology_router.get_fact_model] = lambda: model
    app.dependency_overrides[ontology_router.get_fact_service] = lambda: service
    monkeypatch.setattr(ontology_router, "get_domain_definition", lambda: domain)
    return SimpleNamespace(
        app=app, store=store, model=model, structured=structured, service=service
    )


def test_openapi_exposes_bounded_typed_queries_and_fact_results(http_app):
    schema = http_app.app.openapi()
    request = schema["components"]["schemas"]["FactQuery"]
    assert request["additionalProperties"] is False
    assert request["properties"]["limit"]["minimum"] == 1
    assert request["properties"]["limit"]["maximum"] == 100
    assert request["properties"]["max_hops"]["maximum"] == 3
    assert request["properties"]["anchor_names"]["maxItems"] == 10
    response = schema["paths"]["/ontology/query"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response["$ref"].endswith("/FactResult")


@pytest.mark.asyncio
async def test_domain_and_validation_need_neither_graph_store_nor_model(http_app, domain, graph):
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.get("/ontology/domain")
        assert response.json() == domain.model_dump(mode="json", by_alias=True)
        response = await client.post("/ontology/validate", json=graph.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json() == {"entities": 2, "relations": 1, "sources": 1}
    http_app.store.upsert.assert_not_awaited()
    http_app.model.with_structured_output.assert_not_called()


@pytest.mark.parametrize("invalid", ["type", "quote", "required_property", "extra"])
@pytest.mark.parametrize("endpoint", ["validate", "facts"])
@pytest.mark.asyncio
async def test_invalid_facts_return_422_before_storage(http_app, graph, invalid, endpoint):
    payload = graph.model_dump(mode="json")
    if invalid == "type":
        payload["relations"][0]["type"] = "UNKNOWN"
    elif invalid == "quote":
        payload["entities"][0]["evidence"][0]["quote"] = "不存在于原文"
    elif invalid == "required_property":
        del payload["entities"][0]["properties"]["serial"]
    else:
        payload["unknown"] = True
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post(f"/ontology/{endpoint}", json=payload)
    assert response.status_code == 422
    http_app.store.upsert.assert_not_awaited()


@pytest.mark.parametrize("invented_quote", [False, True])
@pytest.mark.asyncio
async def test_extract_checks_structured_output_against_original_quotes(
    http_app, graph, invented_quote
):
    if invented_quote:
        output = http_app.structured.ainvoke.return_value.model_copy(deep=True)
        output.relations[0].evidence[0].quote = "模型编造的引文"
        http_app.structured.ainvoke.return_value = output
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/ontology/extract", json={"sources": [source.model_dump() for source in graph.sources]}
        )
    assert response.status_code == (422 if invented_quote else 200)
    if not invented_quote:
        assert KnowledgeGraph.model_validate(response.json()) == graph
    http_app.structured.ainvoke.assert_awaited_once()
    http_app.store.upsert.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "部件是什么？"},
        {"mode": "hybrid"},
        {"cypher": "MATCH (n) RETURN n"},
        {"limit": 0},
        {"limit": 101},
        {"max_hops": 4},
        {"operation": "delete"},
        {"anchor_names": [" "]},
        {"unknown": True},
    ],
)
@pytest.mark.asyncio
async def test_invalid_or_retired_query_shapes_are_rejected(http_app, payload):
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post("/ontology/query", json=payload)
    assert response.status_code == 422
    http_app.store.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_typed_query_returns_actual_fact_evidence_without_loading_extraction_model(http_app):
    http_app.app.dependency_overrides[ontology_router.get_fact_model] = Mock(
        side_effect=AssertionError("Query must not load extraction model")
    )
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/ontology/query",
            json={
                "anchor_ids": ["pump-a"],
                "relation_types": ["HAS_COMPONENT"],
                "target_names": ["轴承 B"],
            },
        )
    assert response.status_code == 200
    assert response.json() == http_app.store.query.return_value.model_dump(mode="json")
    request = http_app.store.query.await_args.args[0]
    assert request.anchor_ids == ["pump-a"]
    assert request.relation_types == ["HAS_COMPONENT"]
    assert request.target_names == ["轴承 B"]
    http_app.model.with_structured_output.assert_not_called()


@pytest.mark.asyncio
async def test_fact_write_reports_graph_counts_and_does_not_reextract(http_app, graph):
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post("/ontology/facts", json=graph.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json() == {"entities": 2, "relations": 1, "sources": 1}
    assert http_app.store.upsert.await_args.args[0] == graph
    http_app.model.with_structured_output.assert_not_called()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_write_failure_and_cancellation_do_not_become_http_success(
    http_app, graph, error_type
):
    failure = error_type("graph write failed")
    http_app.store.upsert.side_effect = failure
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        with pytest.raises(error_type) as raised:
            await client.post("/ontology/facts", json=graph.model_dump(mode="json"))
    assert raised.value is failure
    http_app.store.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_fact_dependency_borrows_the_application_graph_store(monkeypatch, domain):
    from gustobot.application.services import knowledge_runtime

    store = SimpleNamespace(close=AsyncMock())
    getter = Mock(return_value=store)
    monkeypatch.setattr(ontology_router, "get_domain_definition", lambda: domain)
    monkeypatch.setattr(knowledge_runtime, "get_graph_store", getter)
    service = await ontology_router.get_fact_service()
    assert service.graph_store is store
    assert service.domain == domain
    getter.assert_called_once_with()
    store.close.assert_not_awaited()
