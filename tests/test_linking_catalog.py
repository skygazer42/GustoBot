"""Authoritative linking catalogs and graph scope migration contracts."""

import asyncio
import json
import os
from collections import Counter
from contextlib import AsyncExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from anyio import create_task_group
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncGraphDatabase
from rdflib import RDFS, Graph, Literal, Namespace
from rdflib.namespace import OWL
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.application.services.knowledge_ingestion import KnowledgeIngestionService
from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.formal_ontology import load_formal_ontology
from gustobot.domain.linking import ENTITY_CATALOG_TYPES
from gustobot.infrastructure.core.database import Base
from gustobot.infrastructure.knowledge.graph_store import Neo4jGraphStore
from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts
from gustobot.infrastructure.knowledge.semantic_runtime import (
    SemanticRuntime,
    SemanticValidationError,
)
from gustobot.interfaces.http import ontology_router

ONTOLOGY_DIR = Path(__file__).resolve().parents[1] / "gustobot/config/ontologies"
R = Namespace("https://gustobot.org/ontology/recipes#")


@pytest.fixture(scope="module")
def formal_model():
    return load_formal_ontology(ONTOLOGY_DIR / "recipes.ttl", ONTOLOGY_DIR / "recipes.shacl.ttl")


def test_ontology_records_follow_definition_edits(formal_model, tmp_path):
    original = {record.ref_id: record for record in formal_model.linking_records()}
    assert original[str(R.Dish)].label == "菜品"
    assert original[str(R.WhiteSugarIngredient)].aliases == ["白砂糖", "砂糖", "绵白糖"]
    assert original["property:ingredientQuantity"].label == "食材用量"
    assert "RecipeVariant" in original["property:ingredientQuantity"].description
    assert "Ingredient" in original["property:ingredientQuantity"].description
    assert all(
        record.kind == "concept" and record.graph_revision is None for record in original.values()
    )
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGY_DIR / name).read_bytes())
    ontology = Graph().parse(tmp_path / "recipes.ttl", format="turtle")
    ontology.set((R.Dish, RDFS.label, Literal("已确认菜品")))
    ontology.serialize(tmp_path / "recipes.ttl", format="turtle")
    changed = load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
    records = {record.ref_id: record for record in changed.linking_records()}
    assert records[str(R.Dish)].label == "已确认菜品"
    assert records[str(R.Dish)].text_hash != original[str(R.Dish)].text_hash
    assert records[str(R.Dish)].ontology_fingerprint == changed.fingerprint
    assert len(records) == len(original)


class EmptyReadResult:
    async def data(self):
        return []


class EmptyReadSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute_read(self, operation, *args):
        return await operation(self, *args)

    async def run(self, query, parameters=None):
        return EmptyReadResult()


class EmptyReadDriver:
    def session(self, *, database):
        return EmptyReadSession()


@pytest.mark.asyncio
async def test_missing_scope_is_uninitialized_and_export_refuses_empty_success(
    formal_model,
):
    store = Neo4jGraphStore(
        formal_model.domain_definition(),
        uri="bolt://unused.invalid",
        user="test",
        password="test",
        driver=cast(AsyncDriver, EmptyReadDriver()),
    )
    revision = await store.graph_revision()
    assert revision.state == "uninitialized"
    assert revision.revision is None
    with pytest.raises(RuntimeError, match="uninitialized"):
        await store.export_linking_records(after_id=None, limit=10)


@pytest_asyncio.fixture
async def linking_graph(formal_model):
    config_path = os.environ.get("GUSTOBOT_TEST_NEO4J_CONFIG")
    if config_path is None:
        pytest.skip("Explicit isolated Neo4j test configuration is required")
    assert config_path is not None
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    driver = AsyncGraphDatabase.driver(config["uri"], auth=(config["user"], config["password"]))
    async with AsyncExitStack() as resources:
        resources.push_async_callback(driver.close)
        database = config.get("database", "neo4j")
        await driver.verify_connectivity()
        domain = formal_model.domain_definition().model_copy(
            update={"id": f"linking-test-{uuid4().hex}"}
        )
        store = Neo4jGraphStore(
            domain,
            uri=config["uri"],
            user=config["user"],
            password=config["password"],
            database=database,
            driver=driver,
        )
        resources.push_async_callback(store.close)
        quick = recipe_to_facts(
            "佛跳墙",
            {
                "id": "quick",
                "source_uri": "https://recipes.test/quick",
                "耗时": "半小时",
                "主食材": [["鸡肉", "100克"]],
                "做法": "1:加入鸡肉。",
                "菜系": "闽菜",
                "工艺": "炖",
            },
        )
        slow = recipe_to_facts(
            "佛跳墙",
            {
                "id": "slow",
                "source_uri": "https://recipes.test/slow",
                "耗时": "数天",
                "主食材": [["鲍鱼", "2只"]],
                "做法": "1:准备鲍鱼。",
            },
        )

        async def clear_scope():
            async with driver.session(database=database) as session:
                await (
                    await session.run(
                        "MATCH (node {domain_id: $domain_id}) DETACH DELETE node",
                        domain_id=domain.id,
                    )
                ).consume()

        resources.push_async_callback(clear_scope)
        yield SimpleNamespace(
            store=store,
            driver=driver,
            database=database,
            domain=domain,
            quick=quick,
            slow=slow,
        )


async def run_native(scope, statement, **parameters):
    async with scope.driver.session(database=scope.database) as session:
        return await (await session.run(statement, domain_id=scope.domain.id, **parameters)).data()


async def remove_scope_metadata(scope):
    await run_native(
        scope,
        "MATCH (node {domain_id: $domain_id}) WHERE node:GustoGraphScope DETACH DELETE node",
    )
    await run_native(scope, "MATCH (node {domain_id: $domain_id}) REMOVE node.ontology_fingerprint")
    await run_native(
        scope,
        "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() REMOVE edge.ontology_fingerprint",
    )


@pytest.mark.asyncio
async def test_export_keyset_visits_each_real_id_once(linking_graph):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await scope.store.upsert(scope.slow)
    expected = {
        entity.id
        for graph in (scope.quick, scope.slow)
        for entity in graph.entities
        if entity.type in ENTITY_CATALOG_TYPES
    }
    records, cursor = [], None
    while True:
        page = await scope.store.export_linking_records(after_id=cursor, limit=1)
        assert page.observed_revision == 2
        records.extend(page.records)
        if page.next_after_id is None:
            break
        assert page.next_after_id == page.records[-1].ref_id
        cursor = page.next_after_id
    assert [record.ref_id for record in records] == sorted(expected)
    assert all(record.object_type in ENTITY_CATALOG_TYPES for record in records)
    quick = next(
        record
        for record in records
        if record.ref_id
        == next(entity.id for entity in scope.quick.entities if entity.type == "RecipeVariant")
    )
    assert quick.qualifiers["cook_time"] == "半小时"
    assert quick.source_labels == ["https://recipes.test/quick"]
    assert scope.quick.sources[0].text not in quick.text


@pytest.mark.asyncio
async def test_graph_revision_changes_only_with_committed_write(linking_graph):
    scope = linking_graph
    assert (await scope.store.graph_revision()).revision is None
    await scope.store.upsert(scope.quick)
    assert (await scope.store.graph_revision()).revision == 1
    failed = scope.quick.model_copy(deep=True)
    failed.sources[0].text += "changed source"
    with pytest.raises(ValueError, match="immutable"):
        await scope.store.upsert(failed)
    assert (await scope.store.graph_revision()).revision == 1
    await scope.store.upsert(scope.slow)
    assert (await scope.store.graph_revision()).revision == 2
    values = await run_native(
        scope,
        "MATCH (node:GustoEntity {domain_id: $domain_id}) RETURN DISTINCT node.ontology_fingerprint AS fingerprint",
    )
    assert values == [{"fingerprint": scope.domain.semantic_model.fingerprint}]
    values = await run_native(
        scope,
        "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() RETURN DISTINCT edge.ontology_fingerprint AS fingerprint",
    )
    assert values == [{"fingerprint": scope.domain.semantic_model.fingerprint}]


@pytest.mark.asyncio
async def test_hydration_rejects_other_version_or_deleted_id(linking_graph):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    variant = next(entity.id for entity in scope.quick.entities if entity.type == "RecipeVariant")
    assert [
        candidate.ref_id
        for candidate in await scope.store.hydrate_candidates([variant, "deleted-id"])
    ] == [variant]
    await run_native(
        scope,
        "MATCH (node:GustoEntity {domain_id: $domain_id, id: $id}) SET node.ontology_version = 'old'",
        id=variant,
    )
    assert await scope.store.hydrate_candidates([variant]) == []
    await run_native(
        scope,
        "MATCH (node:GustoEntity {domain_id: $domain_id, id: $id}) SET node.ontology_version = $version, node.ontology_fingerprint = 'unknown'",
        id=variant,
        version=scope.domain.version,
    )
    assert await scope.store.hydrate_candidates([variant]) == []


@pytest.mark.asyncio
async def test_name_family_reports_truncation_instead_of_unique(linking_graph):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await scope.store.upsert(scope.slow)
    variant_ids = {
        entity.id
        for graph in (scope.quick, scope.slow)
        for entity in graph.entities
        if entity.type == "RecipeVariant"
    }
    result = await scope.store.lookup_name_family([min(variant_ids)], limit=1)
    assert len(result.items) == 1 and result.has_more
    result = await scope.store.lookup_name_family([min(variant_ids)], limit=10)
    assert {item.ref_id for item in result.items} == variant_ids
    assert not result.has_more


@pytest.mark.asyncio
async def test_bootstrap_audits_all_facts_before_backfilling_legacy_scope(
    linking_graph,
):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await scope.store.upsert(scope.slow)
    await remove_scope_metadata(scope)
    report = await scope.store.bootstrap_graph_scope(audit_only=True)
    assert report.existing > 0 and report.validated == report.existing
    assert report.invalid == report.unknown_version == report.backfilled == 0
    assert report.scope.state == "uninitialized"
    assert (await scope.store.graph_revision()).revision is None
    result = await scope.store.lexical_candidates("佛跳墙", expected_types=["RecipeVariant"])
    assert len(result) == 2 and all(item.record.graph_revision is None for item in result)
    with pytest.raises(RuntimeError, match="uninitialized"):
        await scope.store.export_linking_records(after_id=None, limit=10)
    report = await scope.store.bootstrap_graph_scope(audit_only=False)
    assert report.backfilled == report.existing
    assert report.scope.state == "ready" and report.scope.revision == 1


@pytest.mark.parametrize("corruption", ["quote", "identity", "version", "fingerprint"])
@pytest.mark.asyncio
async def test_bootstrap_refuses_bad_evidence_identity_and_unknown_scope(linking_graph, corruption):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await remove_scope_metadata(scope)
    if corruption == "quote":
        statement = (
            "MATCH (node:GustoEvidence {domain_id: $domain_id}) SET node.quote = 'invented quote'"
        )
    elif corruption == "identity":
        statement = "MATCH (node:GustoEntity {domain_id: $domain_id, entity_type: 'Ingredient'}) SET node.id = 'wrong-id'"
    elif corruption == "version":
        statement = "MATCH (node:GustoEntity {domain_id: $domain_id, entity_type: 'Ingredient'}) SET node.ontology_version = 'old'"
    else:
        statement = "MATCH (node:GustoEntity {domain_id: $domain_id, entity_type: 'Ingredient'}) SET node.ontology_fingerprint = 'another-model'"
    await run_native(scope, statement)
    report = await scope.store.bootstrap_graph_scope(audit_only=False)
    assert report.invalid + report.unknown_version > 0
    assert report.backfilled == 0 and report.errors
    assert report.scope.state == "uninitialized"
    assert (await scope.store.graph_revision()).revision is None


@pytest.mark.asyncio
async def test_empty_scope_bootstrap_initializes_zero_and_legacy_write_requires_audit(
    linking_graph,
):
    scope = linking_graph
    report = await scope.store.bootstrap_graph_scope(audit_only=False)
    assert report.scope.revision == 0 and report.existing == 0
    await scope.store.upsert(scope.quick)
    await remove_scope_metadata(scope)
    with pytest.raises(RuntimeError, match="bootstrap"):
        await scope.store.upsert(scope.slow)
    assert (await scope.store.graph_revision()).state == "uninitialized"


@pytest.mark.asyncio
async def test_lexical_candidates_use_real_ids_and_escape_lucene(linking_graph):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await scope.store.upsert(scope.slow)
    variants = {
        entity.id
        for graph in (scope.quick, scope.slow)
        for entity in graph.entities
        if entity.type == "RecipeVariant"
    }
    result = await scope.store.lexical_candidates(
        "佛跳墙有哪些做法？", expected_types=["RecipeVariant"]
    )
    assert {item.ref_id for item in result} == variants
    assert all("substring" in item.match_sources for item in result)
    result = await scope.store.lexical_candidates(min(variants), expected_types=["RecipeVariant"])
    assert [item.ref_id for item in result] == [min(variants)]
    assert result[0].match_sources == ["exactid"]
    assert (
        await scope.store.lexical_candidates(
            '+++ && || ! ( ) { } [ ] ^ " ~ * ? : \\ /', expected_types=["RecipeVariant"]
        )
        == []
    )


@pytest.fixture
def publication_storage():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    try:
        Base.metadata.create_all(engine)

        @contextmanager
        def transaction():
            with Session(engine, expire_on_commit=False) as session, session.begin():
                yield session

        yield transaction
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid", ["quantity", "identity"])
@pytest.mark.parametrize("initialize", ["implicit", "explicit"])
@pytest.mark.asyncio
async def test_first_native_write_attests_formal_shape_and_identity_before_ready(
    linking_graph, invalid, initialize
):
    scope = linking_graph
    if initialize == "explicit":
        await scope.store.bootstrap_graph_scope(audit_only=False)
    graph = recipe_to_facts(
        "首写审计", {"辅料": [["糖", "-1g" if invalid == "quantity" else "1g"]]}
    )
    if invalid == "identity":
        ingredient = next(entity for entity in graph.entities if entity.type == "Ingredient")
        original_id = ingredient.id
        ingredient.id = "invented-ingredient-id"
        for edge in graph.relations:
            if edge.target_id == original_id:
                edge.target_id = ingredient.id
    with pytest.raises(ValueError):
        await scope.store.upsert(graph)
    assert (await scope.store.graph_revision()).revision == (
        0 if initialize == "explicit" else None
    )
    assert await run_native(
        scope,
        "MATCH (node {domain_id: $domain_id}) WHERE NOT node:GustoGraphScope RETURN count(node) AS total",
    ) == [{"total": 0}]


@pytest.mark.asyncio
async def test_native_scope_attestation_does_not_repeat_shacl_on_routine_writes(
    linking_graph, monkeypatch
):
    calls = []
    original = SemanticRuntime.validate_input

    def validate(runtime, graph):
        calls.append(len(graph.entities))
        return original(runtime, graph)

    monkeypatch.setattr(SemanticRuntime, "validate_input", validate)
    await linking_graph.store.upsert(linking_graph.quick)
    await linking_graph.store.upsert(linking_graph.slow)
    assert calls == [len(linking_graph.quick.entities)]
    assert (await linking_graph.store.graph_revision()).revision == 2


@pytest.mark.asyncio
async def test_raw_fact_api_and_recipe_import_share_revision_and_keep_validation_gates(
    linking_graph, publication_storage, monkeypatch
):
    scope = linking_graph
    from gustobot.infrastructure.knowledge import recipe_facts

    mapping = recipe_facts.load_recipe_mapping().model_copy(update={"ontology_id": scope.domain.id})
    monkeypatch.setattr(recipe_facts, "load_recipe_mapping", lambda: mapping)
    service = OntologyService(scope.domain, graph_store=scope.store)
    app = FastAPI()
    app.include_router(ontology_router.router)
    app.dependency_overrides[ontology_router.get_fact_service] = lambda: service
    invalid = recipe_to_facts("拒绝负量", {"辅料": [["糖", "-1g"]]}, domain=scope.domain)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/ontology/facts", json=invalid.model_dump(mode="json"))
        assert response.status_code == 422
        assert response.json()["detail"]["semantic_report"]["conforms"] is False
        assert (await scope.store.graph_revision()).revision is None
        response = await client.post("/ontology/facts", json=scope.quick.model_dump(mode="json"))
        assert response.status_code == 200
    assert (await scope.store.graph_revision()).revision == 1
    importer = KnowledgeIngestionService(
        scope.domain, graph_store=scope.store, session_factory=publication_storage
    )
    with pytest.raises(SemanticValidationError):
        await importer.ingest_recipe("拒绝负量", {"辅料": [["糖", "-1g"]]})
    assert (await scope.store.graph_revision()).revision == 1
    receipt = await importer.ingest_recipe("坛炖", {"辅料": [["盐", "1g"]], "做法": "1:加入盐。"})
    assert receipt.status == "graph_ready"
    assert (await scope.store.graph_revision()).revision == 2
    page = await scope.store.export_linking_records(after_id=None, limit=100)
    assert {record.label for record in page.records if record.object_type == "RecipeVariant"} == {
        "佛跳墙",
        "坛炖",
    }


@pytest.mark.asyncio
async def test_shared_normalized_alias_family_includes_all_real_recipe_versions(
    linking_graph,
):
    scope = linking_graph
    quick = scope.quick.model_copy(deep=True)
    slow = recipe_to_facts("酒坛炖品", {"主食材": [["鲍鱼", "1只"]]})
    quick_variant = next(entity for entity in quick.entities if entity.type == "RecipeVariant")
    slow_variant = next(entity for entity in slow.entities if entity.type == "RecipeVariant")
    quick_variant.aliases = ["  Banquet   Pot "]
    slow_variant.aliases = ["ＢＡＮＱＵＥＴ　ＰＯＴ"]
    await scope.store.upsert(quick)
    await scope.store.upsert(slow)
    result = await scope.store.lookup_name_family([quick_variant.id], limit=10)
    assert {candidate.ref_id for candidate in result.items} == {
        quick_variant.id,
        slow_variant.id,
    }
    assert not result.has_more
    truncated = await scope.store.lookup_name_family([slow_variant.id], limit=1)
    assert len(truncated.items) == 1 and truncated.has_more


@pytest.mark.asyncio
async def test_complete_six_type_export_reports_real_counts_and_text_truncation(
    linking_graph,
):
    scope = linking_graph
    graph = recipe_to_facts(
        "全类型目录",
        {
            "主食材": [["鸡肉", "100克"]],
            "耗时": "原始耗时" * 600,
            "工艺": "炖",
            "菜系": "闽菜",
            "口味": "咸鲜",
            "类型": "荤菜",
            "做法": "1:原文步骤不参与目录。",
        },
    )
    await scope.store.upsert(graph)
    records, cursor = [], None
    while True:
        page = await scope.store.export_linking_records(after_id=cursor, limit=2)
        records.extend(page.records)
        if page.next_after_id is None:
            break
        cursor = page.next_after_id
    assert dict(Counter(record.object_type for record in records)) == {
        "RecipeVariant": 1,
        "Ingredient": 1,
        "CookingMethod": 1,
        "CuisineStyle": 1,
        "Flavor": 1,
        "DishType": 1,
    }
    assert sum(record.text_truncated for record in records) == 1
    assert all(len(record.text) <= 2048 for record in records)
    assert all("原文步骤不参与目录" not in record.text for record in records)
    assert len(records) < len(graph.entities)


@pytest.mark.asyncio
async def test_committed_concurrent_formal_writes_each_advance_one_revision(
    linking_graph,
):
    scope = linking_graph
    async with create_task_group() as tasks:
        for _ in range(5):
            tasks.start_soon(scope.store.upsert, scope.quick)
    assert (await scope.store.graph_revision()).revision == 5
    page = await scope.store.export_linking_records(after_id=None, limit=100)
    assert len({record.ref_id for record in page.records}) == len(page.records)
    assert len([record for record in page.records if record.object_type == "RecipeVariant"]) == 1


@pytest.mark.asyncio
async def test_bootstrap_serializes_native_writer_and_keeps_its_snapshot_revision(
    linking_graph, monkeypatch
):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await remove_scope_metadata(scope)
    snapshot_read, release_audit = asyncio.Event(), asyncio.Event()
    original = scope.store._scope_snapshot
    reads = 0

    async def snapshot(transaction):
        nonlocal reads
        value = await original(transaction)
        reads += 1
        if reads == 1:
            snapshot_read.set()
            await release_audit.wait()
        return value

    monkeypatch.setattr(scope.store, "_scope_snapshot", snapshot)
    bootstrap = asyncio.create_task(scope.store.bootstrap_graph_scope(audit_only=False))
    tasks = [bootstrap]
    try:
        await asyncio.wait_for(snapshot_read.wait(), timeout=10)
        writer = asyncio.create_task(scope.store.upsert(scope.slow))
        tasks.append(writer)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(writer), timeout=0.2)
        release_audit.set()
        report = await asyncio.wait_for(bootstrap, timeout=10)
        await asyncio.wait_for(writer, timeout=10)
        assert report.scope.revision == 1 and report.validated == report.existing
        assert (await scope.store.graph_revision()).revision == 2
        candidates = await scope.store.lexical_candidates(
            "佛跳墙", expected_types=["RecipeVariant"]
        )
        assert len(candidates) == 2
    finally:
        release_audit.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_bootstrap_detects_out_of_band_change_instead_of_attesting_partial_graph(
    linking_graph, monkeypatch
):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await remove_scope_metadata(scope)
    original = scope.store._scope_snapshot
    reads = 0

    async def snapshot(transaction):
        nonlocal reads
        value = await original(transaction)
        reads += 1
        if reads == 1:
            await run_native(
                scope,
                "CREATE (:GustoSource {domain_id: $domain_id, id: 'untracked-source', text: 'untracked', ontology_version: $version})",
                version=scope.domain.version,
            )
        return value

    monkeypatch.setattr(scope.store, "_scope_snapshot", snapshot)
    report = await scope.store.bootstrap_graph_scope(audit_only=False)
    assert report.scope.state == "uninitialized" and report.backfilled == 0
    assert report.errors and "changed" in report.errors[0].lower()
    assert (await scope.store.graph_revision()).revision is None


@pytest.mark.asyncio
async def test_old_ready_writer_cannot_relabel_current_fact_or_source_scope(
    linking_graph, tmp_path
):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGY_DIR / name).read_bytes())
    ontology = Graph().parse(tmp_path / "recipes.ttl", format="turtle")
    ontology.set((R.Ontology, OWL.versionInfo, Literal("older-test-model")))
    ontology.serialize(tmp_path / "recipes.ttl", format="turtle")
    model = load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
    old_domain = model.domain_definition().model_copy(update={"id": scope.domain.id})
    old_store = Neo4jGraphStore(
        old_domain,
        uri="bolt://unused.invalid",
        user="test",
        password="test",
        database=scope.database,
        driver=scope.driver,
    )
    await run_native(
        scope,
        "CREATE (:GustoGraphScope {domain_id: $domain_id, ontology_version: $version, ontology_fingerprint: $fingerprint, state: 'ready', revision: 0})",
        version=model.version,
        fingerprint=model.fingerprint,
    )
    try:
        with pytest.raises(ValueError, match="scope"):
            await old_store.upsert(scope.quick)
        source_only = scope.quick.model_copy(update={"entities": [], "relations": []}, deep=True)
        with pytest.raises(ValueError, match="scope"):
            await old_store.upsert(source_only)
        assert (await old_store.graph_revision()).revision == 0
    finally:
        await old_store.close()
    assert (await scope.store.graph_revision()).revision == 1
    assert (
        len(await scope.store.lexical_candidates("佛跳墙", expected_types=["RecipeVariant"])) == 1
    )


@pytest.mark.asyncio
async def test_declared_version_cannot_attest_a_different_compiled_model(linking_graph):
    scope = linking_graph
    mismatched = Neo4jGraphStore(
        scope.domain.model_copy(update={"version": "uncompiled-version"}),
        uri="bolt://unused.invalid",
        user="test",
        password="test",
        database=scope.database,
        driver=scope.driver,
    )
    try:
        with pytest.raises(ValueError, match="version"):
            await mismatched.upsert(scope.quick)
    finally:
        await mismatched.close()
    assert (await scope.store.graph_revision()).state == "uninitialized"


@pytest.mark.parametrize("scope_state", ["legacy", "ready"])
@pytest.mark.parametrize("broken_keys", ["missing", "wrong"])
@pytest.mark.asyncio
async def test_bootstrap_rebuilds_normalized_lookup_keys_from_validated_raw_facts(
    linking_graph, scope_state, broken_keys
):
    scope = linking_graph
    quick, slow = scope.quick.model_copy(deep=True), scope.slow.model_copy(deep=True)
    for graph in (quick, slow):
        next(entity for entity in graph.entities if entity.type == "RecipeVariant").aliases = [
            " ＢＡＮＱＵＥＴ　ＰＯＴ "
        ]
        await scope.store.upsert(graph)
    if scope_state == "legacy":
        await remove_scope_metadata(scope)
    if broken_keys == "missing":
        await run_native(
            scope,
            "MATCH (node:GustoEntity {domain_id: $domain_id}) REMOVE node.name_key, node.alias_keys",
        )
    else:
        await run_native(
            scope,
            "MATCH (node:GustoEntity {domain_id: $domain_id}) SET node.name_key = 'wrong', node.alias_keys = ['wrong']",
        )
    raw_before = await run_native(
        scope,
        "MATCH (node:GustoEntity {domain_id: $domain_id}) RETURN node.id AS id, node.name_key AS name_key, node.alias_keys AS alias_keys ORDER BY id",
    )
    audit = await scope.store.bootstrap_graph_scope(audit_only=True)
    assert audit.validated == audit.existing and not audit.errors
    assert (
        await run_native(
            scope,
            "MATCH (node:GustoEntity {domain_id: $domain_id}) RETURN node.id AS id, node.name_key AS name_key, node.alias_keys AS alias_keys ORDER BY id",
        )
        == raw_before
    )
    applied = await scope.store.bootstrap_graph_scope(audit_only=False)
    assert applied.scope.revision == (1 if scope_state == "legacy" else 3)
    assert applied.backfilled > 0
    variants = {
        entity.id
        for graph in (quick, slow)
        for entity in graph.entities
        if entity.type == "RecipeVariant"
    }
    assert {
        item.ref_id for item in (await scope.store.lookup_name_family([min(variants)])).items
    } == variants
    assert {
        item.ref_id
        for item in await scope.store.lexical_candidates(
            "banquet pot", expected_types=["RecipeVariant"]
        )
    } == variants


@pytest.mark.asyncio
async def test_bootstrap_rejects_permuted_canonical_entity_identities(linking_graph):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await scope.store.upsert(scope.slow)
    await remove_scope_metadata(scope)
    await run_native(
        scope,
        "MATCH (left:GustoEntity {domain_id: $domain_id, entity_type: 'Ingredient', name: '鸡肉'}), (right:GustoEntity {domain_id: $domain_id, entity_type: 'Ingredient', name: '鲍鱼'}) SET left.name = '鲍鱼', right.name = '鸡肉'",
    )
    report = await scope.store.bootstrap_graph_scope(audit_only=False)
    assert report.invalid > 0 and report.backfilled == 0
    assert report.errors and "identit" in report.errors[0].lower()
    assert report.scope.state == "uninitialized"


@pytest.mark.asyncio
async def test_first_native_write_rejects_permuted_canonical_entity_identities(
    linking_graph,
):
    scope = linking_graph
    graph = recipe_to_facts("交换身份", {"主食材": [["鸡肉", "1g"], ["鲍鱼", "2g"]]})
    ingredients = [entity for entity in graph.entities if entity.type == "Ingredient"]
    ingredients[0].name, ingredients[1].name = ingredients[1].name, ingredients[0].name
    with pytest.raises(ValueError, match="identit"):
        await scope.store.upsert(graph)
    assert (await scope.store.graph_revision()).revision is None
    assert await run_native(
        scope, "MATCH (node {domain_id: $domain_id}) RETURN count(node) AS total"
    ) == [{"total": 0}]


@pytest.mark.asyncio
async def test_expected_graph_revision_rejects_changed_linking_snapshot_before_read(
    linking_graph,
):
    from gustobot.infrastructure.knowledge import graph_store

    scope = linking_graph
    await scope.store.upsert(scope.quick)
    await scope.store.upsert(scope.slow)
    with pytest.raises(graph_store.GraphRevisionConflict):
        await scope.store.query(
            graph_store.FactQuery(entity_type="RecipeVariant", expected_graph_revision=1)
        )
    result = await scope.store.query(
        graph_store.FactQuery(entity_type="RecipeVariant", expected_graph_revision=2)
    )
    assert result.total == 2


@pytest.mark.asyncio
async def test_expected_graph_revision_rechecks_after_fact_read(linking_graph, monkeypatch):
    from gustobot.infrastructure.knowledge import graph_store

    scope = linking_graph
    await scope.store.upsert(scope.quick)
    original = scope.store._read_revision
    reads = 0

    async def revision(transaction):
        nonlocal reads
        value = await original(transaction)
        reads += 1
        if reads == 1:
            await scope.store.upsert(scope.slow)
        return value

    monkeypatch.setattr(scope.store, "_read_revision", revision)
    with pytest.raises(graph_store.GraphRevisionConflict):
        await scope.store.query(
            graph_store.FactQuery(entity_type="RecipeVariant", expected_graph_revision=1)
        )
    assert reads == 2


@pytest.mark.asyncio
async def test_evidence_owner_lookup_uses_composite_index(linking_graph):
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    async with scope.driver.session(database=scope.database) as session:
        rows = await (
            await session.run(
                "SHOW INDEXES YIELD name, state, labelsOrTypes, properties WHERE name = 'gustobot_evidence_owner' RETURN state, labelsOrTypes, properties"
            )
        ).data()
        assert rows == [
            {
                "state": "ONLINE",
                "labelsOrTypes": ["GustoEvidence"],
                "properties": ["domain_id", "owner_kind", "owner_id"],
            }
        ]
        owner = next(entity.id for entity in scope.quick.entities if entity.type == "RecipeVariant")
        result = await session.run(
            "PROFILE MATCH (evidence:GustoEvidence {domain_id: $domain_id, owner_kind: 'entity', owner_id: $owner_id}) RETURN evidence.id AS id",
            domain_id=scope.domain.id,
            owner_id=owner,
        )
        assert len(await result.data()) == 1
        profile = (await result.consume()).profile

    def index_details(plan):
        return [
            str(plan.get("args", {}).get("Details", "")),
            *(detail for child in plan.get("children", []) for detail in index_details(child)),
        ]

    assert any(
        "GustoEvidence(domain_id, owner_kind, owner_id)" in detail
        for detail in index_details(profile)
    )
