"""Observable boundary and cleanup checks for the core guideline review."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from neo4j import AsyncDriver
from rdflib import Graph, Literal
from rdflib.namespace import SH

from gustobot.config.domain import get_domain_definition
from gustobot.domain.formal_ontology import B, load_formal_ontology
from gustobot.domain.numeric import NumericSelection
from gustobot.infrastructure.knowledge import recipe_catalog, recipe_import, reranker
from gustobot.infrastructure.knowledge.graph_store import FactQuery, Neo4jGraphStore
from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService
from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore
from gustobot.infrastructure.knowledge.vector_store import VectorStore


def test_explicit_missing_ingredient_catalog_fails_while_omission_is_optional(tmp_path):
    assert recipe_catalog.load_ingredient_profiles(None, {"salt"}) == []
    with pytest.raises(FileNotFoundError):
        recipe_catalog.load_ingredient_profiles(tmp_path / "missing.json", {"salt"})


@pytest.mark.parametrize("payload", [{"broken": None}, {"broken": []}])
def test_recipe_catalog_does_not_silently_skip_invalid_records(tmp_path, payload):
    source = tmp_path / "recipes.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        recipe_catalog.load_recipe_records(source)


@pytest.mark.parametrize("raw", [{}, [], True])
def test_recipe_catalog_rejects_objects_that_are_not_recorded_text(raw):
    with pytest.raises(ValueError):
        recipe_catalog._clean_name(raw)


def test_recipe_catalog_preserves_recorded_zero_values():
    assert recipe_catalog._clean_name(0) == "0"
    assert recipe_catalog._clean_text(0) == "0"
    assert recipe_catalog._split_multi(0) == ["0"]


@pytest.mark.parametrize("value", [{"salt": "1g"}, 0, [object()]])
def test_recipe_catalog_rejects_unsupported_ingredient_shapes(value):
    with pytest.raises(ValueError):
        recipe_catalog._normalise_ingredients(value, role="main", seen=set())


def test_recipe_import_does_not_turn_arbitrary_objects_into_ingredient_names():
    with pytest.raises(ValueError):
        recipe_import.recipe_json_entry_to_recipe("fixture", {"主食材": [{"bad": "shape"}]})


def test_recipe_document_keeps_explicit_zero_time_and_empty_ingredient_list():
    document = KnowledgeService._format_recipe_document(
        {"name": "fixture", "time": 0, "ingredients": [], "ingredient_list": ["legacy"]}
    )
    assert "耗时：0" in document
    assert "legacy" not in document


@pytest.mark.parametrize("timeout", [float("inf"), float("nan")])
def test_document_store_rejects_nonfinite_timeouts_before_connecting(timeout):
    prototype = VectorStore.__new__(VectorStore)
    prototype.dimension, prototype.embedding_model = 1536, "text-embedding-3-small"
    collection = SimpleNamespace(schema=prototype._schema())
    with pytest.raises(ValueError):
        VectorStore(timeout=timeout, collection=collection)


@pytest.mark.parametrize(
    "rows",
    [
        [{"index": True, "score": 0.5}],
        [{"index": -1, "score": 0.5}],
        [{"index": 2, "score": 0.5}],
        [{"index": 0, "score": "0.5"}],
        [{"index": 0, "score": float("nan")}],
        [{"index": 0, "score": float("inf")}],
        [{"index": 0, "score": 0.5}, {"index": 0, "score": 0.7}],
    ],
)
def test_reranker_rejects_invalid_provider_rows_instead_of_partial_ranking(rows):
    service = reranker.Reranker.__new__(reranker.Reranker)
    with pytest.raises(ValueError):
        service._process_rerank_results(rows, [{"content": "first"}, {"content": "second"}], 2)


@pytest.mark.asyncio
async def test_disabled_reranker_still_rejects_negative_limits():
    service = reranker.Reranker.__new__(reranker.Reranker)
    service.enabled = False
    with pytest.raises(ValueError):
        await service.rerank("fixture", [{"content": "first"}], -1)


@pytest.mark.asyncio
async def test_rerank_failure_log_keeps_stack_without_provider_secrets(monkeypatch):
    service = reranker.Reranker.__new__(reranker.Reranker)
    service.enabled, service.provider = True, "jina"

    async def fail_provider(*args):
        raise ValueError("provider-secret")

    monkeypatch.setattr(service, "_jina_rerank", fail_provider)
    records = []
    handler = reranker.logger.add(
        lambda message: records.append(message.record), format="{message}"
    )
    try:
        documents = [{"content": "first"}]
        assert await service.rerank("fixture", documents, 1) == documents
    finally:
        reranker.logger.remove(handler)
    message = next(record["message"] for record in records if record["level"].name == "ERROR")
    assert "fail_provider" in message
    assert "provider-secret" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["custom", "jina", "voyage"])
async def test_missing_rerank_response_fields_fail_at_the_provider_boundary(monkeypatch, provider):
    for name, value in {
        "RERANK_ENABLED": True,
        "RERANK_PROVIDER": provider,
        "RERANK_BASE_URL": "https://rerank.invalid",
        "RERANK_API_KEY": "fixture",
        "RERANK_MODEL": "fixture",
    }.items():
        monkeypatch.setattr(reranker.settings, name, value)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        reranker.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})), **kwargs
        ),
    )
    service = reranker.Reranker()
    operation = {
        "custom": service._custom_rerank,
        "jina": service._jina_rerank,
        "voyage": service._voyage_rerank,
    }[provider]
    with pytest.raises((KeyError, ValueError)):
        await operation("fixture", [{"content": "first"}], 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["numeric_overflow", "numeric_values", "numeric_coverage"])
async def test_numeric_query_requires_its_declared_database_projection(missing):
    domain = get_domain_definition()
    row = {
        "total": 0,
        "path_total": 0,
        "nodes": [],
        "relations": [],
        "numeric_overflow": False,
        "numeric_values": [],
        "numeric_coverage": [],
    }
    del row[missing]

    async def run(statement, parameters):
        rows = (
            [{"state": "ready", "revision": 1}]
            if "RETURN scope.state AS state" in statement
            else [row]
        )
        return SimpleNamespace(data=AsyncMock(return_value=rows))

    async def execute_read(operation):
        return await operation(SimpleNamespace(run=run))

    @asynccontextmanager
    async def session(**kwargs):
        yield SimpleNamespace(execute_read=execute_read)

    store = Neo4jGraphStore(
        domain,
        uri="bolt://unused.invalid",
        user="fixture",
        password="fixture",
        driver=cast(AsyncDriver, SimpleNamespace(session=session)),
    )
    request = FactQuery(
        numeric_selections=[
            NumericSelection(property="reportedDuration", grain="reported_unspecified")
        ]
    )
    with pytest.raises(KeyError, match=missing):
        await store.query(request)


def test_candidate_verification_closes_cursor_when_row_validation_fails(monkeypatch):
    store = SemanticCandidateStore.__new__(SemanticCandidateStore)
    store.dimension, store.embedding_model = 2, "fixture"
    store.embedding_fingerprint = "a" * 64
    store.index_type, store.metric_type, store.timeout = "HNSW", "COSINE", 1.0
    closed = []
    iterator = SimpleNamespace(next=lambda: [{}], close=lambda: closed.append(True))
    store.collection = SimpleNamespace(
        schema=store._schema(),
        has_index=lambda **kwargs: True,
        index=lambda **kwargs: SimpleNamespace(
            field_name="embedding", params={"index_type": "HNSW", "metric_type": "COSINE"}
        ),
        query_iterator=lambda **kwargs: iterator,
    )
    rows = store._rows('generation_id == "fixture"')
    monkeypatch.setattr(store, "_rows", lambda expression: rows)
    try:
        with pytest.raises(KeyError):
            store.verify_generation("fixture", expected_count=1, expected_checksum="a" * 64)
        assert closed == [True]
    finally:
        rows.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connectivity", "cleanup"])
async def test_linking_fixture_always_closes_its_driver(monkeypatch, tmp_path, stage):
    from tests import test_linking_catalog as catalog_tests

    config = tmp_path / "neo4j.json"
    config.write_text(
        json.dumps({"uri": "bolt://unused.invalid", "user": "fixture", "password": "fixture"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GUSTOBOT_TEST_NEO4J_CONFIG", str(config))
    failure = RuntimeError("fixture boundary failed")

    @asynccontextmanager
    async def session(**kwargs):
        yield SimpleNamespace(run=AsyncMock(side_effect=failure))

    driver = SimpleNamespace(
        verify_connectivity=AsyncMock(side_effect=failure if stage == "connectivity" else None),
        close=AsyncMock(),
        session=session,
    )
    monkeypatch.setattr(catalog_tests.AsyncGraphDatabase, "driver", lambda *args, **kwargs: driver)
    fixture = catalog_tests.linking_graph.__wrapped__(get_domain_definition().semantic_model)
    if stage == "cleanup":
        await fixture.__anext__()
    with pytest.raises(RuntimeError, match="fixture boundary failed"):
        if stage == "connectivity":
            await fixture.__anext__()
        else:
            await fixture.aclose()
    driver.close.assert_awaited_once()


def test_publication_fixture_disposes_engine_when_schema_setup_fails(monkeypatch):
    from tests import test_linking_catalog as catalog_tests

    engine = SimpleNamespace(dispose=Mock())
    monkeypatch.setattr(catalog_tests, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(
        catalog_tests.Base.metadata, "create_all", Mock(side_effect=RuntimeError("schema failed"))
    )
    with pytest.raises(RuntimeError, match="schema failed"):
        next(catalog_tests.publication_storage.__wrapped__())
    engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_isolated_graph_fixture_closes_driver_when_store_setup_fails(monkeypatch, tmp_path):
    from tests import test_graph_store_integration as integration_tests

    config = tmp_path / "neo4j.json"
    config.write_text(
        json.dumps({"uri": "bolt://unused.invalid", "user": "fixture", "password": "fixture"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GUSTOBOT_TEST_NEO4J_CONFIG", str(config))
    driver = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        integration_tests.AsyncGraphDatabase, "driver", lambda *args, **kwargs: driver
    )
    monkeypatch.setattr(
        integration_tests.api(), "Neo4jGraphStore", Mock(side_effect=RuntimeError("store failed"))
    )
    fixture = integration_tests.isolated_graph.__wrapped__()
    with pytest.raises(RuntimeError, match="store failed"):
        await fixture.__anext__()
    driver.close.assert_awaited_once()


def test_formal_compiler_does_not_replace_unknown_rule_relations_with_blank_text(tmp_path):
    from tests.test_formal_ontology import ONTOLOGY_DIR, R

    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGY_DIR / name).read_bytes())
    shapes = Graph().parse(tmp_path / "recipes.shacl.ttl", format="turtle")
    constraint = next(shapes.subjects(SH.select, None))
    shapes.set((constraint, B.relation, R.UNKNOWN_RELATION))
    shapes.set(
        (
            constraint,
            SH.select,
            Literal(
                "PREFIX r: <https://gustobot.org/ontology/recipes#> "
                "SELECT $this ?order WHERE { $this r:UNKNOWN_RELATION ?left, ?right . "
                "?left r:order ?order . ?right r:order ?order . FILTER (?left != ?right) }"
            ),
        )
    )
    shapes.serialize(tmp_path / "recipes.shacl.ttl", format="turtle")
    with pytest.raises((KeyError, ValueError)):
        load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
