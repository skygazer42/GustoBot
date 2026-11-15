"""Validated facts enter the shared document pipeline, without a second graph store."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gustobot.application.services.lightrag_service import (
    LightRAGInsertResponse,
    LightRAGQueryResponse,
)
from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import (
    DomainDefinition,
    EvidenceReference,
    KnowledgeGraph,
    SourceDocument,
)


@pytest.fixture
def domain():
    path = Path(__file__).parents[1] / "gustobot/config/domains/equipment.json"
    return DomainDefinition.model_validate_json(path.read_text(encoding="utf-8"))


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
def shared():
    return SimpleNamespace(
        insert_documents=AsyncMock(
            return_value=LightRAGInsertResponse(total=1, success=1, failed=0)
        ),
        query_structured=AsyncMock(
            return_value=LightRAGQueryResponse(
                query="有哪些部件？", response="轴承 [1]", mode="mix", metadata={"data": {}}
            )
        ),
        cleanup=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_import_preserves_complete_facts_original_text_and_uri(domain, graph, shared):
    original = graph.model_copy(deep=True)
    result = await OntologyService(domain, lightrag=shared).insert(graph)
    call = shared.insert_documents.await_args
    assert call is not None
    assert call.kwargs == {"file_paths": ["manual.pdf"]}
    payload = json.loads(call.args[0][0])
    assert payload == {"domain": domain.id, "source_id": "manual", **graph.model_dump(mode="json")}
    assert graph == original
    assert result == shared.insert_documents.return_value
    shared.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_sources_keep_every_original_and_all_evidence(domain, graph, shared):
    graph.sources.append(SourceDocument(id="inspection", text="检查确认泵包含轴承。"))
    for item in [*graph.entities, *graph.relations]:
        item.evidence.append(EvidenceReference(source_id="inspection", quote="泵包含轴承"))
    shared.insert_documents.return_value = LightRAGInsertResponse(total=2, success=2, failed=0)
    await OntologyService(domain, lightrag=shared).insert(graph)
    call = shared.insert_documents.await_args
    assert call is not None
    payloads = [json.loads(document) for document in call.args[0]]
    assert call.kwargs == {"file_paths": ["manual.pdf", "inspection"]}
    for payload, source in zip(payloads, graph.sources):
        assert payload["source_id"] == source.id
        assert payload["sources"] == [item.model_dump() for item in graph.sources]
        assert payload["entities"] == [entity.model_dump() for entity in graph.entities]
        assert payload["relations"] == [relation.model_dump() for relation in graph.relations]


@pytest.mark.asyncio
async def test_cross_source_relation_keeps_both_endpoint_names_and_original_evidence(
    domain, graph, shared
):
    graph.sources.append(
        SourceDocument(id="inspection", text="检查记录：泵包含轴承。", uri="inspection.txt")
    )
    graph.relations[0].evidence = [EvidenceReference(source_id="inspection", quote="泵包含轴承")]
    shared.insert_documents.return_value = LightRAGInsertResponse(total=2, success=2, failed=0)
    await OntologyService(domain, lightrag=shared).insert(graph)
    call = shared.insert_documents.await_args
    assert call is not None
    relation_document = json.loads(call.args[0][1])
    assert relation_document["entities"] == [item.model_dump() for item in graph.entities]
    assert relation_document["relations"] == [graph.relations[0].model_dump()]
    assert relation_document["sources"] == [item.model_dump() for item in graph.sources]


@pytest.mark.asyncio
async def test_source_documents_are_required_before_initializing_index(domain, shared):
    with pytest.raises(ValueError, match="来源文档"):
        await OntologyService(domain, lightrag=shared).insert(
            KnowledgeGraph(entities=[], relations=[], sources=[])
        )
    shared.insert_documents.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_facts_are_rejected_before_shared_index(domain, graph, shared):
    graph.relations[0].type = "UNDECLARED"
    with pytest.raises(ValueError, match="Unknown relation"):
        await OntologyService(domain, lightrag=shared).insert(graph)
    shared.insert_documents.assert_not_awaited()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_import_failure_and_cancellation_propagate(domain, graph, shared, error_type):
    failure = error_type("index failed")
    shared.insert_documents.side_effect = failure
    with pytest.raises(error_type) as raised:
        await OntologyService(domain, lightrag=shared).insert(graph)
    assert raised.value is failure
    shared.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_import_is_not_a_successful_fact_write(domain, graph, shared):
    shared.insert_documents.return_value = LightRAGInsertResponse(
        total=1, success=0, failed=1, errors=["document processing failed"]
    )
    with pytest.raises(RuntimeError, match="document processing failed"):
        await OntologyService(domain, lightrag=shared).insert(graph)


@pytest.mark.asyncio
async def test_natural_language_query_reuses_answer_and_evidence_from_shared_service(
    domain, shared
):
    result = await OntologyService(domain, lightrag=shared).query(
        "有哪些部件？", mode="mix", top_k=4
    )
    assert result is shared.query_structured.return_value
    request = shared.query_structured.await_args.args[0]
    assert request.model_dump() == {
        "query": "有哪些部件？",
        "mode": "mix",
        "top_k": 4,
        "stream": False,
    }
    shared.cleanup.assert_not_awaited()
