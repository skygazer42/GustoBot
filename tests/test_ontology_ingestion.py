"""Direct fact ingestion preserves original sources and all assertion evidence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import (
    DomainDefinition,
    EvidenceReference,
    KnowledgeGraph,
    SourceDocument,
)
from gustobot.infrastructure.knowledge.graph_store import GraphWriteResult


@pytest.fixture
def domain():
    return DomainDefinition.model_validate(
        {
            "id": "equipment-ingest-test",
            "name": "Equipment",
            "description": "Equipment records",
            "document_scope": "Manuals",
            "entity_types": {
                "Equipment": {
                    "description": "Equipment",
                    "properties": {
                        "serial": {"type": "string", "required": True},
                        "enabled": {"type": "boolean"},
                        "count": {"type": "integer"},
                    },
                },
                "Component": {"description": "Component", "properties": {}},
            },
            "relation_types": {
                "HAS_COMPONENT": {
                    "description": "Contains component",
                    "source_types": ["Equipment"],
                    "target_types": ["Component"],
                }
            },
        }
    )


@pytest.fixture
def graph():
    evidence = [{"source_id": "manual", "quote": "泵包含轴承"}]
    return KnowledgeGraph.model_validate(
        {
            "entities": [
                {
                    "id": "pump",
                    "type": "Equipment",
                    "name": "泵",
                    "aliases": ["水泵"],
                    "properties": {"serial": "P1", "enabled": False, "count": 0},
                    "evidence": evidence,
                },
                {"id": "bearing", "type": "Component", "name": "轴承", "evidence": evidence},
            ],
            "relations": [
                {
                    "id": "pump-bearing",
                    "source_id": "pump",
                    "target_id": "bearing",
                    "type": "HAS_COMPONENT",
                    "evidence": evidence,
                }
            ],
            "sources": [{"id": "manual", "text": "原文：泵包含轴承。", "uri": "manual.pdf"}],
        }
    )


@pytest.fixture
def store():
    return SimpleNamespace(
        upsert=AsyncMock(return_value=GraphWriteResult(entities=2, relations=1, sources=1)),
        close=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_import_keeps_fact_identity_original_text_and_uri(domain, graph, store):
    original = graph.model_copy(deep=True)
    receipt = await OntologyService(domain, graph_store=store).insert(graph)
    written = store.upsert.await_args.args[0]
    assert written is graph
    assert written == original
    assert receipt.model_dump() == {"entities": 2, "relations": 1, "sources": 1}
    store.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_sources_preserve_every_original_and_assertion_reference(
    domain, graph, store
):
    graph.sources.append(
        SourceDocument(id="inspection", text="检查确认泵包含轴承。", uri="inspection.txt")
    )
    for item in [*graph.entities, *graph.relations]:
        item.evidence.append(EvidenceReference(source_id="inspection", quote="泵包含轴承"))
    await OntologyService(domain, graph_store=store).insert(graph)
    written = store.upsert.await_args.args[0]
    assert [source.id for source in written.sources] == ["manual", "inspection"]
    assert all(
        {reference.source_id for reference in item.evidence} == {"manual", "inspection"}
        for item in [*written.entities, *written.relations]
    )
    assert written.sources[1].text == "检查确认泵包含轴承。"


@pytest.mark.asyncio
async def test_cross_source_relation_keeps_its_own_evidence_and_both_endpoints(
    domain, graph, store
):
    graph.sources.append(
        SourceDocument(id="inspection", text="检查记录：泵包含轴承。", uri="inspection.txt")
    )
    graph.relations[0].evidence = [EvidenceReference(source_id="inspection", quote="泵包含轴承")]
    await OntologyService(domain, graph_store=store).insert(graph)
    written = store.upsert.await_args.args[0]
    assert [item.id for item in written.entities] == ["pump", "bearing"]
    assert written.relations[0].evidence[0].source_id == "inspection"
    assert written.sources == graph.sources


@pytest.mark.asyncio
async def test_source_documents_are_required_before_opening_graph_storage(domain, store):
    with pytest.raises(ValueError, match="来源文档"):
        await OntologyService(domain, graph_store=store).insert(
            KnowledgeGraph(entities=[], relations=[], sources=[])
        )
    store.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_facts_are_rejected_before_storage(domain, graph, store):
    graph.relations[0].type = "UNDECLARED"
    with pytest.raises(ValueError, match="Unknown relation"):
        await OntologyService(domain, graph_store=store).insert(graph)
    store.upsert.assert_not_awaited()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_fact_write_failure_and_cancellation_propagate_without_closing_borrowed_store(
    domain, graph, store, error_type
):
    failure = error_type("graph write failed")
    store.upsert.side_effect = failure
    with pytest.raises(error_type) as raised:
        await OntologyService(domain, graph_store=store).insert(graph)
    assert raised.value is failure
    store.close.assert_not_awaited()
