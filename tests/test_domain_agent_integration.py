"""A non-recipe domain drives the same compiled knowledge workflow."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from gustobot.application.agents import workflow
from gustobot.application.services.knowledge_query import KnowledgeAnswer
from gustobot.domain.knowledge import DomainDefinition, KnowledgeGraph, validate_graph


@pytest.fixture
def domain():
    return DomainDefinition.model_validate(
        {
            "id": "equipment-test",
            "name": "设备维护",
            "description": '设备信息 {"source": "manual"}',
            "document_scope": "设备手册与故障信息",
            "entity_types": {"Device": {"description": "设备", "properties": {}}},
            "relation_types": {},
        }
    )


@pytest.mark.asyncio
async def test_compiled_workflow_preserves_history_answer_and_this_turn_sources(
    domain, monkeypatch
):
    answer = KnowledgeAnswer(
        message="泵包含轴承。",
        sources=[{"source": "manual.pdf", "backend": "neo4j"}],
        metadata={"domain_id": domain.id},
    )
    service = SimpleNamespace(answer=AsyncMock(return_value=answer))
    monkeypatch.setattr(
        workflow,
        "get_query_service",
        lambda: (_ for _ in ()).throw(AssertionError("An injected service must be used")),
    )
    history = [HumanMessage(content="设备型号是 A"), AIMessage(content="已记录设备型号。")]
    result = await workflow.graph.ainvoke(
        {"messages": [*history, HumanMessage(content="它有哪些部件？")]},
        config={"configurable": {"knowledge_service": service}},
    )
    service.answer.assert_awaited_once_with("它有哪些部件？", history=history)
    assert result["response"] == answer.model_dump()
    assert result["messages"][-1].content == "泵包含轴承。"


@pytest.mark.asyncio
async def test_compiled_workflow_propagates_query_failure():
    failure = RuntimeError("storage unavailable")
    service = SimpleNamespace(answer=AsyncMock(side_effect=failure))
    with pytest.raises(RuntimeError) as raised:
        await workflow.graph.ainvoke(
            {"messages": [HumanMessage(content="设备状态？")]},
            config={"configurable": {"knowledge_service": service}},
        )
    assert raised.value is failure


def test_documented_equipment_facts_satisfy_the_current_yaml_domain(monkeypatch):
    from gustobot.config import domain as configuration

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        configuration,
        "settings",
        SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(root / "gustobot/config/domains/equipment.yaml")),
    )
    graph = KnowledgeGraph.model_validate_json(
        (root / "docs/examples/equipment-facts.json").read_text(encoding="utf-8")
    )
    selected = configuration.get_domain_definition()
    validate_graph(selected, graph)
    assert {entity.type for entity in graph.entities} <= set(selected.entity_types)


@pytest.mark.asyncio
async def test_route_description_uses_the_selected_domain(domain, monkeypatch):
    from gustobot.config import domain as configuration
    from gustobot.interfaces.http.v1 import chat

    monkeypatch.setattr(configuration, "get_domain_definition", lambda: domain)
    result = await chat.get_route_info()
    assert result["domain"] == "设备维护"
    assert "knowledge-query" in result["routes"]
    assert "菜谱" not in str(result)
