"""A non-recipe profile must drive real chat entrypoints without recipe tools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from pathlib import Path
import runpy

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from gustobot.application.agents import lg_builder, lg_prompts
from gustobot.application.agents.lg_states import AgentState, Router
from gustobot.domain.knowledge import DomainDefinition, EntityTypeDefinition


@pytest.fixture
def domain(monkeypatch):
    profile = DomainDefinition(
        id="test-equipment",
        name="设备维护",
        description='设备信息 {"source": "manual"}',
        document_scope="设备手册与故障信息",
        entity_types={"Device": EntityTypeDefinition(description="设备", properties={})},
        relation_types={},
        graph_keywords=["部件"],
        sql_keywords=[],
        document_keywords=[],
    )
    monkeypatch.setattr(lg_builder, "get_domain_definition", lambda: profile)
    monkeypatch.setattr(lg_prompts, "get_domain_definition", lambda: profile)
    return profile


def test_prompt_preserves_literal_braces_and_domain(domain):
    prompt = lg_prompts.domain_prompt(lg_prompts.GENERAL_QUERY_SYSTEM_PROMPT, logic="问候")
    assert domain.description in prompt
    assert "菜谱" not in prompt


def test_heuristic_routing_uses_profile_keywords(domain):
    route = lg_builder._heuristic_router("泵包含哪些部件")
    assert route is not None and route.type == "graphrag-query"
    assert lg_builder._heuristic_router("宫保鸡丁怎么做") is None
    assert lg_builder._heuristic_router("多少设备") is None


@pytest.mark.asyncio
async def test_generic_graph_answer_does_not_load_business_extension(domain, monkeypatch):
    service = SimpleNamespace(query=AsyncMock(return_value="泵包含轴承"))
    monkeypatch.setattr(lg_builder, "get_lightrag_service", lambda: service)
    state = AgentState(
        messages=[HumanMessage(content="泵有哪些部件？")], router=Router(type="graphrag-query")
    )
    result = await lg_builder.create_research_plan(state, config={})
    assert result["messages"][0].content == "泵包含轴承"
    service.query.assert_awaited_once_with("泵有哪些部件？", stream=False)


@pytest.mark.asyncio
async def test_clarification_uses_scope_without_database(domain, monkeypatch):
    structured = SimpleNamespace(ainvoke=AsyncMock(return_value={"decision": "proceed"}))
    model = SimpleNamespace(
        with_structured_output=Mock(return_value=structured),
        ainvoke=AsyncMock(return_value=AIMessage(content="请提供设备型号")),
    )
    monkeypatch.setattr(lg_builder, "ChatOpenAI", lambda **_: model)
    state = AgentState(messages=[HumanMessage(content="怎么维护它？")])
    result = await lg_builder.get_additional_info(state, config={})
    assert "设备型号" in result["messages"][0].content
    messages = structured.ainvoke.call_args.args[0]
    assert domain.description in messages[0].content
    assert "菜谱" not in messages[0].content


@pytest.mark.asyncio
async def test_generic_document_query_uses_isolated_runtime(domain, monkeypatch):
    service = SimpleNamespace(query=AsyncMock(return_value="设备手册中的说明"))
    monkeypatch.setattr(lg_builder, "get_lightrag_service", lambda: service)
    monkeypatch.setattr(lg_builder, "KnowledgeService", Mock(side_effect=AssertionError("旧库")))
    state = AgentState(messages=[HumanMessage(content="维护手册怎么说？")])
    result = await lg_builder.create_kb_query(state, config={})
    assert result["messages"][0].content == "设备手册中的说明"
    service.query.assert_awaited_once_with("维护手册怎么说？", mode="naive", stream=False)


@pytest.mark.asyncio
async def test_generic_upload_uses_same_runtime(domain, monkeypatch, tmp_path):
    document = tmp_path / "manual.txt"
    document.write_text("泵包含轴承", encoding="utf-8")
    service = SimpleNamespace(
        insert_documents=AsyncMock(return_value=SimpleNamespace(success=1, failed=0, errors=[]))
    )
    monkeypatch.setattr(lg_builder, "get_lightrag_service", lambda: service)
    monkeypatch.setattr(lg_builder, "KnowledgeService", Mock(side_effect=AssertionError("旧库")))
    state = AgentState(messages=[HumanMessage(content="上传手册")])
    result = await lg_builder.create_file_query(
        state, config={"configurable": {"file_path": str(document)}}
    )
    assert "已加入" in result["messages"][0].content
    service.insert_documents.assert_awaited_once_with(["泵包含轴承"], file_paths=["manual.txt"])


@pytest.mark.parametrize("profile", ["equipment", "recipes"])
@pytest.mark.parametrize("legacy_api", [False, True])
def test_app_registers_only_configured_business_http_routes(monkeypatch, profile, legacy_api):
    from gustobot.config import domain as domain_config

    root = Path(__file__).resolve().parents[1]
    selected = DomainDefinition.model_validate_json(
        (root / "gustobot/config/domains" / f"{profile}.json").read_text(encoding="utf-8")
    )
    selected.http_router_modules = (
        ["gustobot.interfaces.http.knowledge_router"] if legacy_api else []
    )
    monkeypatch.setattr(domain_config, "get_domain_definition", lambda: selected)
    namespace = runpy.run_path(str(root / "gustobot/main.py"))
    paths = namespace["application"].openapi()["paths"]
    assert any(path.startswith("/api/v1/knowledge") for path in paths) is legacy_api
    assert "/api/v1/ontology/domain" in paths
    assert "/api/v1/chat/stream" in paths


def test_documented_equipment_sample_passes_actual_domain_validation():
    from gustobot.domain.knowledge import KnowledgeGraph, validate_graph

    root = Path(__file__).resolve().parents[1]
    selected = DomainDefinition.model_validate_json(
        (root / "gustobot/config/domains/equipment.json").read_text(encoding="utf-8")
    )
    graph = KnowledgeGraph.model_validate_json(
        (root / "docs/examples/equipment-facts.json").read_text(encoding="utf-8")
    )
    validate_graph(selected, graph)
    assert {entity.type for entity in graph.entities} <= set(selected.entity_types)


@pytest.mark.asyncio
async def test_route_descriptions_follow_the_selected_domain(domain, monkeypatch):
    from gustobot.interfaces.http.v1 import chat

    monkeypatch.setattr(chat, "get_domain_definition", lambda: domain)
    result = await chat.get_route_info()
    assert result["routes"]["kb-query"]["description"] == domain.document_scope
    assert "text2sql-query" not in result["routes"]
    assert "菜谱" not in str(result)
