"""Ontology HTTP contracts use the shared document runtime without database ownership."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gustobot.application.services.lightrag_service import (
    LightRAGInsertResponse,
    LightRAGQueryResponse,
    LightRAGService,
)
from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import DomainDefinition, ExtractedKnowledge, KnowledgeGraph
from gustobot.interfaces.http import ontology_router


@pytest.fixture
def domain():
    path = Path(__file__).parents[1] / "gustobot/config/domains/equipment.json"
    return DomainDefinition.model_validate_json(path.read_text(encoding="utf-8"))


@pytest.fixture
def graph():
    evidence = [{"source_id": "manual", "quote": "泵 A 包含轴承 B，轴承 B 存在磨损。"}]
    return KnowledgeGraph.model_validate(
        {
            "entities": [
                {
                    "id": "pump-a",
                    "type": "Equipment",
                    "name": "泵 A",
                    "properties": {"serial": "A", "enabled": False, "count": 0},
                    "evidence": evidence,
                },
                {"id": "bearing-b", "type": "Component", "name": "轴承 B", "evidence": evidence},
                {"id": "wear", "type": "Fault", "name": "磨损", "evidence": evidence},
            ],
            "relations": [
                {
                    "id": "pump-bearing",
                    "source_id": "pump-a",
                    "target_id": "bearing-b",
                    "type": "HAS_COMPONENT",
                    "evidence": evidence,
                },
                {
                    "id": "bearing-wear",
                    "source_id": "bearing-b",
                    "target_id": "wear",
                    "type": "HAS_FAULT",
                    "evidence": evidence,
                },
            ],
            "sources": [{"id": "manual", "text": evidence[0]["quote"], "uri": "manual.pdf"}],
        }
    )


@pytest.fixture
def http_app(monkeypatch, domain, graph):
    app = FastAPI()
    app.include_router(ontology_router.router)
    shared = Mock(
        spec=LightRAGService,
        insert_documents=AsyncMock(
            return_value=LightRAGInsertResponse(total=1, success=1, failed=0)
        ),
        query_structured=AsyncMock(
            return_value=LightRAGQueryResponse(
                query="部件？",
                response="轴承 [1]",
                mode="mix",
                metadata={
                    "data": {"references": [{"reference_id": "1", "file_path": "manual.pdf"}]}
                },
            )
        ),
        cleanup=AsyncMock(),
    )
    model = Mock()
    structured = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=ExtractedKnowledge(entities=graph.entities, relations=graph.relations)
        )
    )
    model.with_structured_output.return_value = structured
    service = OntologyService(domain, model=model, lightrag=shared)
    app.dependency_overrides[ontology_router.get_fact_model] = lambda: model
    app.dependency_overrides[ontology_router.get_fact_service] = lambda: service
    monkeypatch.setattr(ontology_router, "get_domain_definition", lambda: domain)
    return SimpleNamespace(
        app=app, shared=shared, model=model, structured=structured, service=service
    )


def test_openapi_declares_natural_language_query_and_shared_response(http_app):
    schema = http_app.app.openapi()
    operation = schema["paths"]["/ontology/query"]["post"]
    request = schema["components"]["schemas"]["GraphQueryRequest"]
    assert set(request["properties"]) == {"question", "mode", "top_k"}
    assert request["additionalProperties"] is False
    assert request["properties"]["top_k"]["anyOf"][0]["minimum"] == 1
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("/LightRAGQueryResponse")


@pytest.mark.asyncio
async def test_domain_and_validation_need_neither_index_nor_model(http_app, domain, graph):
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.get("/ontology/domain")
        assert response.json() == domain.model_dump(mode="json")
        response = await client.post("/ontology/validate", json=graph.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json() == {"entities": 3, "relations": 2, "sources": 1}
    http_app.shared.insert_documents.assert_not_awaited()
    http_app.model.with_structured_output.assert_not_called()


@pytest.mark.parametrize("invalid", ["type", "quote", "required_property", "extra"])
@pytest.mark.parametrize("endpoint", ["validate", "facts"])
@pytest.mark.asyncio
async def test_invalid_facts_return_422_before_index(http_app, graph, invalid, endpoint):
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
    http_app.shared.insert_documents.assert_not_awaited()


@pytest.mark.parametrize("invented_quote", [False, True])
@pytest.mark.asyncio
async def test_extract_checks_structured_output_and_original_quotes(
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
    http_app.shared.insert_documents.assert_not_awaited()


@pytest.mark.parametrize(
    "replacement",
    [
        {"anchor_ids": ["pump-a"]},
        {"relation_types": ["HAS_COMPONENT"]},
        {"max_hops": 1},
        {"limit": 3},
        {"question": ""},
        {"question": " "},
        {"question": "\t\n"},
        {"top_k": 0},
        {"mode": "cypher"},
        {"unknown": True},
    ],
)
@pytest.mark.asyncio
async def test_path_parameters_and_invalid_queries_are_rejected(http_app, replacement):
    payload = {"question": "部件？", "mode": "mix", "top_k": 4, **replacement}
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post("/ontology/query", json=payload)
    assert response.status_code == 422
    http_app.shared.query_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_reuses_shared_answer_and_metadata_without_fact_model(http_app):
    http_app.app.dependency_overrides[ontology_router.get_fact_model] = Mock(
        side_effect=AssertionError("query loaded extraction model")
    )
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/ontology/query", json={"question": "部件？", "mode": "mix", "top_k": 4}
        )
    assert response.status_code == 200
    assert response.json() == http_app.shared.query_structured.return_value.model_dump()
    request = http_app.shared.query_structured.await_args.args[0]
    assert (request.query, request.mode, request.top_k) == ("部件？", "mix", 4)
    http_app.shared.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_facts_report_document_import_statistics(http_app, graph):
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        response = await client.post("/ontology/facts", json=graph.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json() == {"total": 1, "success": 1, "failed": 0, "errors": []}


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_import_failure_and_cancellation_do_not_become_http_success(
    http_app, graph, error_type
):
    failure = error_type("index failed")
    http_app.shared.insert_documents.side_effect = failure
    async with AsyncClient(
        transport=ASGITransport(app=http_app.app), base_url="http://test"
    ) as client:
        with pytest.raises(error_type) as raised:
            await client.post("/ontology/facts", json=graph.model_dump(mode="json"))
    assert raised.value is failure
    http_app.shared.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_fact_dependency_borrows_shared_service(monkeypatch, domain):
    shared = SimpleNamespace(cleanup=AsyncMock())
    monkeypatch.setattr(ontology_router, "get_domain_definition", lambda: domain)
    getter = Mock(return_value=shared)
    monkeypatch.setattr(ontology_router, "get_lightrag_service", getter)
    service = await ontology_router.get_fact_service()
    assert service.lightrag is shared
    assert service.domain == domain
    getter.assert_called_once_with()
    shared.cleanup.assert_not_awaited()
