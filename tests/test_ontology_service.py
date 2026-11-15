"""Exercise domain-independent extraction and fact extraction offline."""

from unittest.mock import AsyncMock, Mock

import pytest

from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import (
    DomainDefinition,
    ExtractedKnowledge,
    KnowledgeGraph,
    SourceDocument,
)


@pytest.fixture
def equipment_domain():
    return DomainDefinition.model_validate(
        {
            "id": "factory",
            "name": "设备知识",
            "description": "设备与部件的维护知识",
            "document_scope": "设备资料",
            "entity_types": {
                "Device": {"description": "设备", "properties": {}},
                "Part": {"description": "部件", "properties": {}},
            },
            "graph_keywords": [],
            "sql_keywords": [],
            "document_keywords": [],
            "relation_types": {
                "HAS_PART": {
                    "description": "包含部件",
                    "source_types": ["Device"],
                    "target_types": ["Part"],
                }
            },
        }
    )


@pytest.fixture
def equipment_graph():
    evidence = [{"source_id": "manual", "quote": "泵 A 包含轴承 B"}]
    return KnowledgeGraph.model_validate(
        {
            "entities": [
                {"id": "pump-a", "type": "Device", "name": "泵 A", "evidence": evidence},
                {"id": "bearing-b", "type": "Part", "name": "轴承 B", "evidence": evidence},
            ],
            "relations": [
                {
                    "id": "pump-bearing",
                    "source_id": "pump-a",
                    "target_id": "bearing-b",
                    "type": "HAS_PART",
                    "evidence": evidence,
                }
            ],
            "sources": [{"id": "manual", "text": "泵 A 包含轴承 B。", "uri": "manual.pdf"}],
        }
    )


@pytest.mark.asyncio
async def test_extraction_uses_configured_domain_and_validates_evidence(
    equipment_domain, equipment_graph
):
    extracted = ExtractedKnowledge(
        entities=equipment_graph.entities, relations=equipment_graph.relations
    )
    structured = AsyncMock()
    structured.ainvoke.return_value = extracted
    model = Mock()
    model.ainvoke = AsyncMock()
    model.with_structured_output.return_value = structured
    service = OntologyService(equipment_domain, model=model)

    result = await service.extract(equipment_graph.sources)

    assert result == equipment_graph
    messages = structured.ainvoke.call_args.args[0]
    assert "HAS_PART" in messages[0].content
    assert "菜谱" not in messages[0].content
    model.with_structured_output.assert_called_once_with(
        ExtractedKnowledge, method="function_calling"
    )


@pytest.mark.asyncio
async def test_extraction_does_not_accept_invented_quote(equipment_domain, equipment_graph):
    invalid = ExtractedKnowledge(
        entities=equipment_graph.entities, relations=equipment_graph.relations
    ).model_copy(deep=True)
    invalid.relations[0].evidence[0].quote = "模型编造的原文"
    structured = AsyncMock()
    structured.ainvoke.return_value = invalid
    model = Mock()
    model.with_structured_output.return_value = structured
    service = OntologyService(equipment_domain, model=model)

    with pytest.raises(ValueError):
        await service.extract([SourceDocument(id="manual", text="泵 A 包含轴承 B。")])
