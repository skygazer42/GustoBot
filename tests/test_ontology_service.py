"""Exercise domain-independent extraction and fact extraction offline."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import (
    DomainDefinition,
    ExtractedKnowledge,
    KnowledgeGraph,
    SourceDocument,
)
from gustobot.infrastructure.knowledge.graph_store import Neo4jGraphStore


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
    structured.ainvoke.assert_awaited_once()
    model.ainvoke.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_insert_preserves_facts_and_identity_without_model_reextraction(
    equipment_domain, equipment_graph
):
    from types import SimpleNamespace

    receipt = SimpleNamespace(entities=2, relations=1, sources=1)
    store = Mock(spec=Neo4jGraphStore, upsert=AsyncMock(return_value=receipt))
    model = Mock()
    service = OntologyService(equipment_domain, model=model, graph_store=store)

    result = await service.insert(equipment_graph)

    assert result is receipt
    store.upsert.assert_awaited_once_with(equipment_graph)
    assert store.upsert.await_args.args[0] is equipment_graph
    model.with_structured_output.assert_not_called()


@pytest.mark.parametrize("invalid", ["quote", "property", "endpoint"])
@pytest.mark.asyncio
async def test_invalid_graph_is_rejected_before_graph_write(
    equipment_domain, equipment_graph, invalid
):

    store = Mock(spec=Neo4jGraphStore, upsert=AsyncMock())
    graph = equipment_graph.model_copy(deep=True)
    if invalid == "quote":
        graph.entities[0].evidence[0].quote = "不存在的原文"
    elif invalid == "property":
        graph.entities[0].properties["undeclared"] = 1
    else:
        graph.relations[0].target_id = "pump-a"
    service = OntologyService(equipment_domain, graph_store=store)

    with pytest.raises(ValueError):
        await service.insert(graph)

    store.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_literal_braces_in_source_are_passed_unchanged(equipment_domain, equipment_graph):
    from types import SimpleNamespace

    original = equipment_graph.sources[0].text + ' 数据 {"count": 0} 与 {占位符}。'
    source = SourceDocument(id="manual", text=original)
    output = ExtractedKnowledge(
        entities=equipment_graph.entities, relations=equipment_graph.relations
    )
    call = AsyncMock(return_value=output)
    model = Mock()
    model.with_structured_output.return_value = SimpleNamespace(ainvoke=call)

    result = await OntologyService(equipment_domain, model=model).extract([source])

    assert result.sources[0].text == original
    assert call.await_args is not None
    assert "{占位符}" in call.await_args.args[0][1].content
    call.assert_awaited_once()


@pytest.fixture
def formal_recipe_graph():
    from gustobot.config.domain import get_domain_definition
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    domain = get_domain_definition()
    graph = recipe_to_facts(
        "糖水",
        {"辅料": [["红糖", "1000", "mg"], ["糖", None]], "做法": ["加水煮开"]},
        domain=domain,
    )
    return domain, graph


def arbitrary_candidates(graph, prefix):
    candidate = graph.model_copy(deep=True)
    replacements = {entity.id: prefix + str(index) for index, entity in enumerate(graph.entities)}
    for entity in candidate.entities:
        entity.id = replacements[entity.id]
    for index, relation in enumerate(candidate.relations):
        relation.id = prefix + "relation:" + str(index)
        relation.source_id = replacements[relation.source_id]
        relation.target_id = replacements[relation.target_id]
    return candidate


@pytest.mark.asyncio
async def test_standard_runtime_makes_model_candidate_ids_stable_and_preserves_sources(
    formal_recipe_graph,
):
    domain, graph = formal_recipe_graph
    first = arbitrary_candidates(graph, "model-first:")
    second = arbitrary_candidates(graph, "model-second:")
    original = first.model_copy(deep=True)
    call = AsyncMock(
        side_effect=[
            first.model_dump(exclude={"sources"}),
            second.model_dump(exclude={"sources"}),
        ]
    )
    model = Mock()
    model.with_structured_output.return_value = SimpleNamespace(ainvoke=call)
    service = OntologyService(domain, model=model)

    extracted = await service.extract(first.sources)
    repeated = await service.extract(second.sources)

    assert extracted == repeated
    assert extracted.sources == original.sources
    assert {entity.id for entity in extracted.entities} == {entity.id for entity in graph.entities}
    assert first == original
    schema = model.with_structured_output.call_args.args[0]
    assert set(schema["$defs"]["KnowledgeEntity"]["properties"]["type"]["enum"]) == set(
        domain.entity_types
    )
    assert set(schema["$defs"]["KnowledgeRelation"]["properties"]["type"]["enum"]) == set(
        domain.relation_types
    )
    assert call.await_count == 2


@pytest.mark.asyncio
async def test_standard_runtime_direct_insert_matches_extraction_binding(formal_recipe_graph):
    domain, graph = formal_recipe_graph
    store = Mock(spec=Neo4jGraphStore, upsert=AsyncMock(return_value="stored"))
    candidate = arbitrary_candidates(graph, "external:")
    original = candidate.model_copy(deep=True)
    service = OntologyService(domain, graph_store=store)

    await service.insert(candidate)
    canonical = store.upsert.await_args.args[0]
    await service.insert(canonical)

    assert store.upsert.await_args.args[0] == canonical
    assert {entity.id for entity in canonical.entities} == {entity.id for entity in graph.entities}
    assert canonical.sources == graph.sources
    assert candidate == original


@pytest.mark.asyncio
async def test_standard_extraction_rejects_ambiguous_source_scoped_identity(formal_recipe_graph):
    domain, graph = formal_recipe_graph
    candidate = arbitrary_candidates(graph, "model:")
    duplicate_source = candidate.sources[0].model_copy(update={"id": "other-source"})
    variant = next(entity for entity in candidate.entities if entity.type == "RecipeVariant")
    variant.evidence.append(variant.evidence[0].model_copy(update={"source_id": "other-source"}))
    model = Mock()
    model.with_structured_output.return_value = SimpleNamespace(
        ainvoke=AsyncMock(return_value=candidate.model_dump(exclude={"sources"}))
    )

    with pytest.raises(ValueError, match="unambiguous source_id"):
        await OntologyService(domain, model=model).extract([*candidate.sources, duplicate_source])


@pytest.mark.parametrize("operation", ["extract", "insert"])
@pytest.mark.asyncio
async def test_standard_shape_report_survives_service_boundary(formal_recipe_graph, operation):
    from gustobot.infrastructure.knowledge.semantic_runtime import (
        SemanticValidationError,
    )

    domain, graph = formal_recipe_graph
    candidate = arbitrary_candidates(graph, "candidate:")
    edge = next(edge for edge in candidate.relations if edge.type == "HAS_AUX_INGREDIENT")
    edge.properties["amount_text"] = "-1mg"
    store = Mock(spec=Neo4jGraphStore, upsert=AsyncMock())
    model = Mock()
    model.with_structured_output.return_value = SimpleNamespace(
        ainvoke=AsyncMock(return_value=candidate.model_dump(exclude={"sources"}))
    )
    service = OntologyService(domain, model=model, graph_store=store)

    with pytest.raises(SemanticValidationError) as failure:
        if operation == "extract":
            await service.extract(candidate.sources)
        else:
            await service.insert(candidate)

    report = failure.value.report.model_dump(mode="json")
    assert report["conforms"] is False
    assert report["ontology_version"] == domain.version
    assert any(issue["path"].endswith("#value") for issue in report["issues"] if issue["path"])
    store.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_query_accepts_typed_graph_shape_and_rejects_retired_question_contract():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from gustobot.interfaces.http import ontology_router

    payload = {
        "entities": [],
        "relations": [],
        "sources": [],
        "total": 0,
        "truncated": False,
        "ontology_version": "1",
    }
    service = SimpleNamespace(query=AsyncMock(return_value=payload))
    app = FastAPI()
    app.include_router(ontology_router.router)
    app.dependency_overrides[ontology_router.get_fact_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/ontology/query", json={"anchor_ids": ["pump-a"], "relation_types": ["HAS_PART"]}
        )
        assert response.status_code == 200
        retired = await client.post("/ontology/query", json={"question": "有哪些部件？"})

    assert response.json() == {**payload, "numeric_coverage": [], "numeric_values": []}
    assert retired.status_code == 422
    request = service.query.await_args.args[0]
    assert request.anchor_ids == ["pump-a"]
    assert request.relation_types == ["HAS_PART"]
