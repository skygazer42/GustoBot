"""The unified document path keeps domain scope and sources without a nested router."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from gustobot.application.services.knowledge_query import KnowledgeQueryService
from gustobot.domain.knowledge import DomainDefinition


def build_service(*, documents=(), plan=None, answer="设备资料"):
    domain = DomainDefinition.model_validate(
        {
            "id": "equipment-test",
            "name": "设备维护",
            "description": "设备资料",
            "entity_types": {"Equipment": {"description": "设备", "properties": {}}},
            "relation_types": {},
            "document_scope": '设备手册 {"source": "manual"}',
        }
    )
    planner = AsyncMock(return_value={"documents": True} if plan is None else plan)
    generation = AsyncMock(return_value=AIMessage(content=answer))
    model = SimpleNamespace(
        with_structured_output=lambda *args, **kwargs: SimpleNamespace(ainvoke=planner),
        ainvoke=generation,
    )
    search = AsyncMock(return_value=list(documents))
    graph = SimpleNamespace(resolve_entities=AsyncMock(), query=AsyncMock())
    service = KnowledgeQueryService(
        domain, graph_store=graph, documents=SimpleNamespace(search=search), model=model
    )
    return service, planner, generation, search, graph


def document():
    return {
        "id": "chunk-1",
        "content": "泵包含阀门。",
        "score": 0.9,
        "metadata": {"source_id": "manual", "uri": "manual.pdf", "source_version": "v1"},
    }


@pytest.mark.asyncio
async def test_domain_scope_and_original_sources_reach_the_single_document_path():
    service, planner, generation, search, graph = build_service(documents=[document()])
    result = await service.answer("泵的手册中有哪些说明？")
    assert result.message == "设备资料"
    assert result.sources[0]["source"] == "manual.pdf"
    assert result.metadata["model_calls"] == 2
    catalog = json.loads(planner.await_args.args[0][0].content.rsplit("\n", 1)[-1])
    assert catalog["ontology"]["document_scope"] == service.domain.document_scope
    assert "泵包含阀门" in generation.await_args.args[0][1].content
    assert "菜谱" not in generation.await_args.args[0][0].content
    search.assert_awaited_once()
    graph.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_clarification_returns_without_search_or_generation():
    service, planner, generation, search, graph = build_service(
        plan={"decision": "clarify", "message": "请补充设备型号。"}
    )
    result = await service.answer("应该怎么维护它？")
    assert result.route == "clarification"
    assert result.message == "请补充设备型号。"
    assert result.sources == []
    assert result.metadata["model_calls"] == 1
    planner.assert_awaited_once()
    generation.assert_not_awaited()
    search.assert_not_awaited()
    graph.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_document_retrieval_reports_no_results_without_generation():
    service, planner, generation, search, graph = build_service()
    result = await service.answer("泵的手册写了什么？")
    assert result.metadata["status"] == "no_results"
    assert result.sources == []
    assert "菜谱" not in result.message
    planner.assert_awaited_once()
    search.assert_awaited_once()
    graph.query.assert_not_awaited()
    generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_generation_stays_a_visible_failure():
    service, planner, generation, search, graph = build_service(documents=[document()], answer="")
    with pytest.raises(ValueError, match="no text"):
        await service.answer("泵的手册写了什么？")
    search.assert_awaited_once()
    generation.assert_awaited_once()
    planner.assert_awaited_once()
    graph.query.assert_not_awaited()
