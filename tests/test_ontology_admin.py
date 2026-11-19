"""Admin graph edits are bound to stored source versions, without live services."""

import hashlib
import importlib
import importlib.util
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncGraphDatabase
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import (
    DomainDefinition,
    ExtractedKnowledge,
    KnowledgeGraph,
)
from gustobot.infrastructure.core.database import Base
from gustobot.infrastructure.knowledge.graph_store import (
    FactResult,
    GraphWriteResult,
    Neo4jGraphStore,
)
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository
from gustobot.infrastructure.persistence.db.models.knowledge import KnowledgeSource


@pytest.fixture
def domain():
    return DomainDefinition.model_validate(
        {
            "id": "admin-factory",
            "name": "设备资料",
            "description": "设备事实",
            "document_scope": "设备手册",
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
def graph():
    evidence = [{"source_id": "manual", "quote": "泵 A 包含轴承 B"}]
    return KnowledgeGraph.model_validate(
        {
            "entities": [
                {"id": "pump", "type": "Device", "name": "泵 A", "evidence": evidence},
                {"id": "bearing", "type": "Part", "name": "轴承 B", "evidence": evidence},
            ],
            "relations": [
                {
                    "id": "pump-bearing",
                    "source_id": "pump",
                    "target_id": "bearing",
                    "type": "HAS_PART",
                    "evidence": evidence,
                }
            ],
            "sources": [{"id": "manual", "text": "泵 A 包含轴承 B。", "uri": "manual.pdf"}],
        }
    )


@pytest.fixture
def storage(domain, graph):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def transaction():
        with Session(engine, expire_on_commit=False) as session, session.begin():
            yield session

    source = graph.sources[0]
    version = hashlib.sha256(source.text.encode()).hexdigest()
    with transaction() as session:
        KnowledgeRepository(session).put_source(
            domain_id=domain.id,
            source_id=source.id,
            version=version,
            text=source.text,
            uri=source.uri,
            ontology_version=domain.version,
            status="ready",
            metadata={"kind": "document", "metadata": {"title": "手册"}, "entity_ids": []},
        )
    yield SimpleNamespace(transaction=transaction, version=version, domain=domain)
    engine.dispose()


def admin_api():
    name = "gustobot.application.services.ontology_admin"
    assert importlib.util.find_spec(name) is not None, "Source-bound admin service is missing"
    return importlib.import_module(name)


@pytest.fixture
def admin_http(storage, graph):
    api = admin_api()
    from gustobot.interfaces.http import ontology_admin_router as router

    store = Mock(
        spec=Neo4jGraphStore,
        upsert=AsyncMock(return_value=GraphWriteResult(entities=2, relations=1, sources=1)),
        source_facts=AsyncMock(
            return_value=FactResult(
                **graph.model_dump(),
                total=3,
                truncated=False,
                ontology_version=storage.domain.version,
            )
        ),
    )
    model = Mock()
    call = AsyncMock(return_value=ExtractedKnowledge(**graph.model_dump(exclude={"sources"})))
    model.with_structured_output.return_value = SimpleNamespace(ainvoke=call)
    service = api.OntologyAdminService(storage.domain, session_factory=storage.transaction)
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[router.get_admin_service] = lambda: service
    app.dependency_overrides[router.get_admin_model] = lambda: model
    app.dependency_overrides[router.get_admin_store] = lambda: store
    return SimpleNamespace(app=app, store=store, model=model, call=call, service=service)


@pytest.mark.asyncio
async def test_candidate_extraction_returns_invalid_graph_but_existing_extract_stays_strict(
    domain, graph
):
    invalid = graph.model_copy(deep=True)
    invalid.entities[0].evidence[0].quote = "模型编造的句子"
    call = AsyncMock(return_value=ExtractedKnowledge(**invalid.model_dump(exclude={"sources"})))
    model = Mock()
    model.with_structured_output.return_value = SimpleNamespace(ainvoke=call)
    ontology = OntologyService(domain, model=model)
    assert hasattr(ontology, "extract_candidate"), "Admin needs an editable extraction candidate"

    assert await ontology.extract_candidate(graph.sources) == invalid
    call.assert_awaited_once()
    with pytest.raises(ValueError):
        await ontology.extract(graph.sources)


@pytest.mark.asyncio
async def test_invalid_candidate_can_be_corrected_without_reextracting(admin_http, storage, graph):
    invalid = graph.model_copy(deep=True)
    invalid.relations[0].evidence[0].quote = "不存在的引文"
    admin_http.call.return_value = ExtractedKnowledge(**invalid.model_dump(exclude={"sources"}))
    selection = {"source_id": "manual", "version": storage.version}
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        extracted = await client.post("/ontology/admin/extract", json=selection)
        assert extracted.status_code == 200
        assert extracted.json()["graph"] == invalid.model_dump(mode="json")
        assert extracted.json()["validation"]["valid"] is False
        assert extracted.json()["validation"]["errors"]
        rejected = await client.post(
            "/ontology/admin/facts", json={**selection, "graph": extracted.json()["graph"]}
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["errors"]
        admin_http.store.upsert.assert_not_awaited()
        validated = await client.post(
            "/ontology/admin/validate", json={**selection, "graph": graph.model_dump(mode="json")}
        )
        assert validated.status_code == 200
        assert validated.json()["validation"] == {"valid": True, "errors": []}
        written = await client.post(
            "/ontology/admin/facts", json={**selection, "graph": validated.json()["graph"]}
        )
    assert written.status_code == 200
    assert written.json() == {"entities": 2, "relations": 1, "sources": 1}
    admin_http.call.assert_awaited_once()
    admin_http.store.upsert.assert_awaited_once_with(graph)
    with storage.transaction() as session:
        source = session.get(KnowledgeSource, (storage.domain.id, "manual", storage.version))
        assert source.status == "ready"
        assert source.source_metadata["kind"] == "document"
        assert source.source_metadata["metadata"] == {"title": "手册"}
        assert source.source_metadata["entity_ids"] == []


@pytest.mark.parametrize("forged", ["text", "uri", "id", "extra_source", "evidence"])
@pytest.mark.parametrize("endpoint", ["validate", "facts"])
@pytest.mark.asyncio
async def test_client_cannot_replace_canonical_source(admin_http, storage, graph, forged, endpoint):
    payload = graph.model_dump(mode="json")
    if forged in {"text", "uri", "id"}:
        payload["sources"][0][forged] = "forged"
    elif forged == "extra_source":
        payload["sources"].append({"id": "other", "text": "other text", "uri": "other.pdf"})
    else:
        payload["relations"][0]["evidence"][0]["source_id"] = "other"
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/ontology/admin/{endpoint}",
            json={"source_id": "manual", "version": storage.version, "graph": payload},
        )
    assert response.status_code == 422
    admin_http.store.upsert.assert_not_awaited()
    admin_http.call.assert_not_awaited()


@pytest.mark.parametrize(
    "condition",
    ["wrong_domain", "missing_version", "old_ontology", "withdrawn", "recipe", "oversized"],
)
@pytest.mark.asyncio
async def test_extraction_checks_source_state_before_model(admin_http, storage, condition):
    version = storage.version
    with storage.transaction() as session:
        row = session.get(KnowledgeSource, (storage.domain.id, "manual", version))
        if condition == "wrong_domain":
            row.domain_id = "other-domain"
        elif condition == "missing_version":
            version = "missing"
        elif condition == "old_ontology":
            row.ontology_version = "retired"
        elif condition == "withdrawn":
            row.status = "withdrawn"
        elif condition == "recipe":
            row.source_metadata = {"kind": "recipe"}
        else:
            row.text = "长" * 40001
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/ontology/admin/extract", json={"source_id": "manual", "version": version}
        )
    expected = (
        404
        if condition in {"wrong_domain", "missing_version"}
        else 422
        if condition == "oversized"
        else 409
    )
    assert response.status_code == expected
    admin_http.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_facts_passes_only_canonical_selected_version(admin_http, storage, graph):
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/ontology/admin/source-facts",
            params={"source_id": "manual", "version": storage.version, "limit": 7},
        )
    assert response.status_code == 200
    assert response.json()["sources"] == graph.model_dump(mode="json")["sources"]
    admin_http.store.source_facts.assert_awaited_once_with(
        graph.sources[0], version=storage.version, limit=7
    )
    admin_http.call.assert_not_awaited()


@pytest.mark.parametrize("limit", [0, 101])
@pytest.mark.asyncio
async def test_source_facts_query_limit_is_bounded(admin_http, storage, limit):
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/ontology/admin/source-facts",
            params={"source_id": "manual", "version": storage.version, "limit": limit},
        )
    assert response.status_code == 422
    admin_http.store.source_facts.assert_not_awaited()


@pytest.mark.parametrize("operation", ["read", "extract", "write"])
@pytest.mark.asyncio
async def test_dependency_failure_is_explicit_503(admin_http, storage, graph, operation):
    selection = {"source_id": "manual", "version": storage.version}
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        if operation == "read":
            admin_http.store.source_facts.side_effect = RuntimeError("Neo4j unavailable")
            response = await client.get("/ontology/admin/source-facts", params=selection)
        elif operation == "extract":
            admin_http.call.side_effect = RuntimeError("LLM unavailable")
            response = await client.post("/ontology/admin/extract", json=selection)
        else:
            admin_http.store.upsert.side_effect = RuntimeError("Neo4j unavailable")
            response = await client.post(
                "/ontology/admin/facts", json={**selection, "graph": graph.model_dump(mode="json")}
            )
    assert response.status_code == 503
    assert "Neo4j unavailable" not in response.text
    assert "LLM unavailable" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [KeyError, ValueError])
async def test_graph_decode_failure_is_503_instead_of_source_not_found(
    admin_http, storage, error_type
):
    admin_http.store.source_facts.side_effect = error_type("invalid stored evidence")
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/ontology/admin/source-facts",
            params={"source_id": "manual", "version": storage.version},
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_semantically_invalid_validation_retains_editable_raw_graph(
    admin_http, storage, graph
):
    graph.entities[0].type = "UNDECLARED"
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/ontology/admin/validate",
            json={
                "source_id": "manual",
                "version": storage.version,
                "graph": graph.model_dump(mode="json"),
            },
        )
    assert response.status_code == 200
    assert response.json()["graph"] == graph.model_dump(mode="json")
    assert response.json()["validation"]["valid"] is False
    assert response.json()["validation"]["errors"]
    admin_http.store.upsert.assert_not_awaited()
    admin_http.call.assert_not_awaited()


@pytest.mark.asyncio
async def test_formal_validation_binds_identities_and_returns_shape_errors(storage):
    from gustobot.config.domain import get_domain_definition
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    domain = get_domain_definition()
    canonical = recipe_to_facts(
        "糖水", {"辅料": [["红糖", "1000", "mg"]], "做法": ["加水煮开"]}, domain=domain
    )
    canonical.sources[0].uri = "manual.txt"
    source = canonical.sources[0]
    version = hashlib.sha256(source.text.encode()).hexdigest()
    with storage.transaction() as session:
        KnowledgeRepository(session).put_source(
            domain_id=domain.id,
            source_id=source.id,
            version=version,
            text=source.text,
            uri=source.uri,
            ontology_version=domain.version,
            status="ready",
            metadata={"kind": "document"},
        )
    candidate = canonical.model_copy(deep=True)
    replacement = {item.id: f"model:{index}" for index, item in enumerate(candidate.entities)}
    for entity in candidate.entities:
        entity.id = replacement[entity.id]
    for edge in candidate.relations:
        edge.source_id = replacement[edge.source_id]
        edge.target_id = replacement[edge.target_id]
    service = admin_api().OntologyAdminService(domain, session_factory=storage.transaction)
    valid = await service.validate(source.id, version, candidate)
    assert valid.validation.valid is True
    assert {item.id for item in valid.graph.entities} == {item.id for item in canonical.entities}
    assert candidate.entities[0].id.startswith("model:")
    next(edge for edge in candidate.relations if edge.type == "HAS_AUX_INGREDIENT").properties[
        "amount_text"
    ] = "-1mg"
    invalid = await service.validate(source.id, version, candidate)
    assert invalid.graph == candidate
    assert invalid.validation.valid is False
    assert invalid.validation.errors


@pytest.mark.asyncio
async def test_recipe_ingestion_missing_uri_can_be_read_from_its_original_graph(storage):
    from gustobot.application.services.knowledge_ingestion import (
        KnowledgeIngestionService,
    )
    from gustobot.config.domain import get_domain_definition

    domain = get_domain_definition()
    store = SimpleNamespace(
        upsert=AsyncMock(return_value=GraphWriteResult(entities=3, relations=2, sources=1)),
        source_facts=AsyncMock(),
    )
    ingestion = KnowledgeIngestionService(
        domain, graph_store=store, session_factory=storage.transaction
    )
    receipt = await ingestion.ingest_recipe("糖水", {"辅料": [["糖", None]]})
    original = store.upsert.await_args.args[0]
    assert original.sources[0].uri is None
    with storage.transaction() as session:
        row = session.get(KnowledgeSource, (domain.id, receipt.source_id, receipt.version))
        assert row.uri == receipt.source_id
        assert row.source_metadata["kind"] == "recipe"
    store.source_facts.return_value = FactResult(
        **original.model_dump(), total=3, truncated=False, ontology_version=domain.version
    )
    admin = admin_api().OntologyAdminService(domain, session_factory=storage.transaction)
    result = await admin.source_facts(receipt.source_id, receipt.version, store, limit=50)
    store.source_facts.assert_awaited_once_with(
        original.sources[0], version=receipt.version, limit=50
    )
    assert result.sources == original.sources


@pytest.mark.asyncio
async def test_document_uri_fallback_still_requires_mysql_canonical_uri(admin_http, storage, graph):
    with storage.transaction() as session:
        row = session.get(KnowledgeSource, (storage.domain.id, "manual", storage.version))
        row.uri = row.source_id
    canonical = graph.model_copy(deep=True)
    canonical.sources[0].uri = canonical.sources[0].id
    selection = {"source_id": "manual", "version": storage.version}
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        accepted = await client.post(
            "/ontology/admin/validate", json={**selection, "graph": canonical.model_dump(mode="json")}
        )
        canonical.sources[0].uri = None
        rejected = await client.post(
            "/ontology/admin/validate", json={**selection, "graph": canonical.model_dump(mode="json")}
        )
        await client.get("/ontology/admin/source-facts", params=selection)
    assert accepted.status_code == 200
    assert rejected.status_code == 422
    assert admin_http.store.source_facts.await_args.args[0].uri == "manual"


@pytest.mark.asyncio
async def test_existing_immutable_graph_source_conflict_is_409(admin_http, storage, graph):
    admin_http.store.upsert.side_effect = ValueError(
        "Source identity is immutable; use a new source ID: manual"
    )
    async with AsyncClient(
        transport=ASGITransport(app=admin_http.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/ontology/admin/facts",
            json={
                "source_id": "manual",
                "version": storage.version,
                "graph": graph.model_dump(mode="json"),
            },
        )
    assert response.status_code == 409


class GraphReadSession:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def execute_read(self, read):
        return await read(self)

    async def run(self, statement, parameters):
        self.calls.append((statement, parameters))
        return SimpleNamespace(data=AsyncMock(return_value=next(self.rows)))


@pytest.mark.asyncio
async def test_source_facts_compiles_parameterized_scope_and_decodes_selected_evidence(
    domain, graph
):
    source = graph.sources[0]
    version = hashlib.sha256(source.text.encode()).hexdigest()
    properties = [
        {"id": item.id, "entity_type": item.type, "name": item.name, "aliases": []}
        for item in graph.entities
    ]
    edge = graph.relations[0]
    session = GraphReadSession(
        [
            [{"total": 4}],
            [
                {"kind": "entity", "item": properties[0], "origin": None, "target": None},
                {
                    "kind": "relation",
                    "item": {
                        "id": edge.id,
                        "source_id": edge.source_id,
                        "target_id": edge.target_id,
                        "relation_type": edge.type,
                    },
                    "origin": properties[0],
                    "target": properties[1],
                },
            ],
            [
                {
                    "owner_kind": kind,
                    "owner_id": item.id,
                    "references": [item.evidence[0].model_dump()],
                }
                for kind, collection in (("entity", graph.entities), ("relation", graph.relations))
                for item in collection
            ],
        ]
    )
    driver = Mock(session=Mock(return_value=session))
    store = Neo4jGraphStore(
        domain, uri="bolt://unused.invalid", user="test", password="unused", driver=driver
    )
    assert hasattr(store, "source_facts"), "Source-scoped graph reads are missing"
    result = await store.source_facts(source, version=version, limit=2)

    assert {item.id for item in result.entities} == {"pump", "bearing"}
    assert result.relations == graph.relations
    assert result.sources == [source]
    assert result.total == 4
    assert result.truncated is True
    assert len(session.calls) == 3
    for statement, params in session.calls:
        assert params["domain_id"] == domain.id
        assert params["ontology_version"] == domain.version
        assert params["source_id"] == source.id
        assert params["source_text"] == source.text
        assert params["source_uri"] == source.uri
        assert "$ontology_fingerprint" in statement
        assert "$source_text" in statement and "$source_uri" in statement
        assert source.text not in statement and source.uri not in statement
    assert "LIMIT $limit" in session.calls[1][0]
    assert "LIMIT 11" in session.calls[2][0]


@pytest.mark.asyncio
async def test_source_facts_refuses_version_content_mismatch_before_driver(domain, graph):
    driver = Mock()
    store = Neo4jGraphStore(
        domain, uri="bolt://unused.invalid", user="test", password="unused", driver=driver
    )
    assert hasattr(store, "source_facts"), "Source-scoped graph reads are missing"
    with pytest.raises(ValueError, match="version"):
        await store.source_facts(graph.sources[0], version="other-version")
    driver.session.assert_not_called()


@pytest.mark.asyncio
async def test_source_facts_empty_is_an_actual_successful_database_read(domain, graph):
    source = graph.sources[0]
    session = GraphReadSession([[{"total": 0}], []])
    store = Neo4jGraphStore(
        domain,
        uri="bolt://unused.invalid",
        user="test",
        password="unused",
        driver=Mock(session=Mock(return_value=session)),
    )
    result = await store.source_facts(
        source, version=hashlib.sha256(source.text.encode()).hexdigest()
    )
    assert len(session.calls) == 2
    assert result.total == 0
    assert result.truncated is False
    assert result.entities == result.relations == result.sources == []


@pytest_asyncio.fixture
async def isolated_admin_graph(domain):
    config_path = os.environ.get("GUSTOBOT_TEST_NEO4J_CONFIG")
    if config_path is None:
        pytest.skip("GUSTOBOT_TEST_NEO4J_CONFIG is required for isolated Neo4j checks")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    driver = AsyncGraphDatabase.driver(config["uri"], auth=(config["user"], config["password"]))
    database = config.get("database", "neo4j")
    scoped_domain = domain.model_copy(update={"id": f"test-admin-{uuid4().hex}"})
    other_domain = domain.model_copy(update={"id": f"test-admin-{uuid4().hex}"})
    stores = [
        Neo4jGraphStore(
            definition,
            uri=config["uri"],
            user=config["user"],
            password=config["password"],
            database=database,
            driver=driver,
        )
        for definition in (scoped_domain, other_domain)
    ]
    try:
        yield stores
    finally:
        try:
            async with driver.session(database=database) as session:
                await (
                    await session.run(
                        "MATCH (node) WHERE node.domain_id IN $ids DETACH DELETE node",
                        {"ids": [definition.id for definition in (scoped_domain, other_domain)]},
                    )
                ).consume()
        finally:
            await driver.close()


@pytest.mark.asyncio
async def test_real_source_facts_isolates_domain_content_and_evidence(isolated_admin_graph, graph):
    store, other_store = isolated_admin_graph
    await store.upsert(graph)
    await other_store.upsert(graph)
    other = graph.model_copy(deep=True)
    other.sources[0].id = "other-source"
    other.sources[0].text += "来自另一本手册。"
    for fact in [*other.entities, *other.relations]:
        for reference in fact.evidence:
            reference.source_id = "other-source"
    await store.upsert(other)
    source = graph.sources[0]
    result = await store.source_facts(
        source, version=hashlib.sha256(source.text.encode()).hexdigest()
    )
    assert result.total == 3
    assert result.sources == [source]
    assert all(
        reference.source_id == source.id
        for fact in [*result.entities, *result.relations]
        for reference in fact.evidence
    )
    limited = await store.source_facts(
        source, version=hashlib.sha256(source.text.encode()).hexdigest(), limit=1
    )
    assert limited.truncated is True
    assert len(limited.relations) == 1
    altered = source.model_copy(update={"text": "另一个内容版本"})
    miss = await store.source_facts(
        altered, version=hashlib.sha256(altered.text.encode()).hexdigest()
    )
    assert miss.total == 0
    assert miss.entities == miss.relations == miss.sources == []
    missing_uri = other.model_copy(deep=True)
    missing_uri.sources[0].id = "missing-uri"
    missing_uri.sources[0].uri = None
    for fact in [*missing_uri.entities, *missing_uri.relations]:
        for reference in fact.evidence:
            reference.source_id = "missing-uri"
    await store.upsert(missing_uri)
    null_source = missing_uri.sources[0]
    null_result = await store.source_facts(
        null_source, version=hashlib.sha256(null_source.text.encode()).hexdigest()
    )
    assert null_result.sources == [null_source]
    assert null_result.total == 3
