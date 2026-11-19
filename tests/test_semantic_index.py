"""Candidate vectors enforce immutable generations, strict scope, and actual readback."""

import asyncio
import copy
import json
import math
import os
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymilvus import CollectionSchema, DataType, FieldSchema

from gustobot.domain.linking import (
    INDEX_SCHEMA_VERSION,
    CatalogRecord,
    IndexScope,
    catalog_checksum,
)

FINGERPRINT = "e" * 64
MODEL_FINGERPRINT = "a" * 64


def record(ref_id="recipe-1", *, kind="entity", **changes):
    values = {
        "domain_id": "recipes",
        "ontology_version": "2026-11-16.3",
        "ontology_fingerprint": MODEL_FINGERPRINT,
        "kind": kind,
        "ref_kind": "entity" if kind == "entity" else "class",
        "ref_id": ref_id,
        "object_type": "RecipeVariant" if kind == "entity" else "Class",
        "label": "番茄炒鸡蛋",
        "graph_revision": 2 if kind == "entity" else None,
    }
    values.update(changes)
    return CatalogRecord.create(**values)


def scope_for(candidate=None, **changes):
    candidate = record() if candidate is None else candidate
    values = {
        name: getattr(candidate, name)
        for name in (
            "domain_id",
            "ontology_version",
            "ontology_fingerprint",
            "kind",
            "index_schema_version",
        )
    }
    return IndexScope(**({"embedding_fingerprint": FINGERPRINT} | values | changes))


def candidate_schema(
    *, dimension=2, embedding_model="fixture", fingerprint=FINGERPRINT, dynamic=False
):
    lengths = {
        "id": 64,
        "generation_id": 64,
        "record_id": 64,
        "domain_id": 256,
        "kind": 16,
        "ref_kind": 16,
        "object_type": 512,
        "ref_id": 8192,
        "ontology_version": 256,
        "ontology_fingerprint": 64,
        "embedding_model": 256,
        "embedding_fingerprint": 64,
        "index_schema_version": 128,
        "text_hash": 64,
        "record_hash": 64,
        "text": 8192,
        "metadata": 65535,
    }
    return CollectionSchema(
        [
            FieldSchema(name, DataType.VARCHAR, max_length=size, is_primary=name == "id")
            for name, size in lengths.items()
        ]
        + [
            FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=dimension),
            FieldSchema("graph_revision", DataType.INT64),
        ],
        description=json.dumps(
            {
                "schema_version": INDEX_SCHEMA_VERSION,
                "embedding_model": embedding_model,
                "embedding_fingerprint": fingerprint,
            },
            sort_keys=True,
        ),
        auto_id=False,
        enable_dynamic_field=dynamic,
    )


def matches(row, expression):
    clauses = re.findall(r'(\w+)\s*(==|in)\s*("(?:\\.|[^"\\])*"|\[[^\]]*\])', expression)
    assert clauses, expression
    return all(
        row[name] == json.loads(value) if operator == "==" else row[name] in json.loads(value)
        for name, operator, value in clauses
    )


class RowIterator:
    def __init__(self, rows, batch_size):
        self.rows, self.batch_size, self.closed = iter(rows), min(batch_size, 2), False

    def next(self):
        result = []
        for _ in range(self.batch_size):
            value = next(self.rows, None)
            if value is None:
                break
            result.append(value)
        return result

    def close(self):
        self.closed = True


class MemoryCollection:
    def __init__(self, schema=None, *, indexed=True):
        self.schema = candidate_schema() if schema is None else schema
        self.rows = {}
        self.searches, self.queries, self.iterators, self.deleted = [], [], [], []
        self.indexed = indexed
        self.index_definition = SimpleNamespace(
            field_name="embedding",
            params={"index_type": "HNSW", "metric_type": "COSINE"},
        )

    def has_index(self, **kwargs):
        return self.indexed

    def index(self, **kwargs):
        return self.index_definition

    def create_index(self, field_name, index_params, **kwargs):
        self.indexed = True
        self.index_definition = SimpleNamespace(field_name=field_name, params=index_params)

    def load(self, **kwargs):
        pass

    def upsert(self, rows, **kwargs):
        self.rows.update((row["id"], copy.deepcopy(row)) for row in rows)
        return SimpleNamespace(upsert_count=len(rows))

    def query(self, *, expr, output_fields, limit, **kwargs):
        self.queries.append((expr, output_fields))
        return [
            {name: row[name] for name in output_fields}
            for row in self.rows.values()
            if matches(row, expr)
        ][:limit]

    def query_iterator(self, *, expr, output_fields, batch_size, **kwargs):
        iterator = RowIterator(
            [
                {name: row[name] for name in output_fields}
                for row in self.rows.values()
                if matches(row, expr)
            ],
            batch_size,
        )
        self.iterators.append(iterator)
        return iterator

    def search(self, *, data, anns_field, param, limit, expr, output_fields, **kwargs):
        self.searches.append({"expr": expr, "param": param, **kwargs})
        rows = [row for row in self.rows.values() if matches(row, expr)]
        vector = data[0]
        hits = []
        for row in rows:
            score = sum(left * right for left, right in zip(row[anns_field], vector)) / (
                math.sqrt(sum(value * value for value in row[anns_field]))
                * math.sqrt(sum(value * value for value in vector))
            )
            hits.append(
                SimpleNamespace(entity={name: row[name] for name in output_fields}, score=score)
            )
        return [sorted(hits, key=lambda hit: -hit.score)[:limit]]

    def delete(self, expr, **kwargs):
        self.deleted.append(expr)
        self.rows = {key: value for key, value in self.rows.items() if not matches(value, expr)}


def make_store(collection=None, **options):
    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

    return SemanticCandidateStore(
        collection_name="semantic_fixture",
        embedding_model="fixture",
        embedding_fingerprint=FINGERPRINT,
        dimension=2,
        collection=MemoryCollection() if collection is None else collection,
        **options,
    )


def test_scope_generation_kind_and_type_filter_before_ann():
    collection = MemoryCollection()
    store = make_store(collection)
    wanted = record()
    store.upsert("active", [wanted], [[0.8, 0.6]])
    for generation, candidate in [
        ("unpublished", record("pending")),
        ("foreign", record("foreign", domain_id="other")),
        ("old-model", record("old-model", ontology_fingerprint="b" * 64)),
        ("old-version", record("old-version", ontology_version="old")),
        ("concept", record("concept", kind="concept")),
    ]:
        store.upsert(generation, [candidate], [[1.0, 0.0]])
    store.upsert("active", [record("ingredient", object_type="Ingredient")], [[1.0, 0.0]])
    hits = store.search(
        [1.0, 0.0],
        scope=scope_for(wanted),
        generation_id="active",
        expected_types=["RecipeVariant"],
        top_k=1,
    )
    assert [hit.ref_id for hit in hits] == ["recipe-1"]
    assert hits[0].scope == scope_for(wanted)
    assert hits[0].generation_id == "active" and hits[0].vector_score == pytest.approx(0.8)
    expression = collection.searches[0]["expr"]
    for field in (
        "domain_id",
        "ontology_version",
        "ontology_fingerprint",
        "embedding_model",
        "embedding_fingerprint",
        "index_schema_version",
        "generation_id",
        "kind",
        "object_type",
    ):
        assert re.search(rf"\b{field}\b", expression)


@pytest.mark.parametrize(
    "mutation", ["domain", "hash", "kind", "type", "generation", "metadata", "vector"]
)
def test_search_validates_every_returned_row_even_if_server_filter_is_bypassed(
    mutation, monkeypatch
):
    collection = MemoryCollection()
    store = make_store(collection)
    candidate = record()
    store.upsert("active", [candidate], [[1.0, 0.0]])
    row = copy.deepcopy(next(iter(collection.rows.values())))
    if mutation == "domain":
        row["domain_id"] = "other"
    elif mutation == "hash":
        row["record_hash"] = "b" * 64
    elif mutation == "kind":
        row["kind"] = "concept"
    elif mutation == "type":
        row["object_type"] = "Ingredient"
    elif mutation == "generation":
        row["generation_id"] = "pending"
    elif mutation == "metadata":
        row["metadata"] = "{broken-json"
    else:
        row["embedding"] = [float("nan"), 0.0]
    monkeypatch.setattr(
        collection,
        "search",
        lambda **kwargs: [[SimpleNamespace(entity=row, score=0.9)]],
    )
    with pytest.raises((ValueError, RuntimeError)):
        store.search(
            [1.0, 0.0],
            scope=scope_for(candidate),
            generation_id="active",
            expected_types=["RecipeVariant"],
            top_k=1,
        )


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[1.0]],
        [[float("nan"), 0.0]],
        [[float("inf"), 0.0]],
        [[True, 0.0]],
        [[1e300, 0.0]],
        [[0.0, 0.0]],
    ],
)
def test_upsert_rejects_invalid_vectors_without_partial_write(vectors):
    collection = MemoryCollection()
    store = make_store(collection)
    with pytest.raises(ValueError):
        store.upsert("generation", [record()], vectors)
    assert collection.rows == {}


def test_upsert_revalidates_nested_mutations_and_duplicate_record_identity():
    collection = MemoryCollection()
    store = make_store(collection)
    candidate = record()
    candidate.aliases.append("silently mutated")
    with pytest.raises(ValueError, match="hash"):
        store.upsert("generation", [candidate], [[1.0, 0.0]])
    candidate = record()
    with pytest.raises(ValueError, match="Duplicate|duplicate"):
        store.upsert("generation", [candidate, candidate], [[1.0, 0.0], [1.0, 0.0]])
    assert collection.rows == {}


def test_generation_scope_revision_and_record_content_cannot_change_between_batches():
    collection = MemoryCollection()
    store = make_store(collection)
    first = record()
    store.upsert("generation", [first], [[1.0, 0.0]])
    for changed in [
        record("other", domain_id="other"),
        record("other", graph_revision=3),
        record(label="changed"),
    ]:
        with pytest.raises(ValueError, match="scope|revision|identity|content"):
            store.upsert("generation", [changed], [[1.0, 0.0]])
    store.upsert("generation", [first], [[1.0, 0.0]])
    assert len(collection.rows) == 1


def test_metadata_bytes_are_validated_before_any_upsert():
    collection = MemoryCollection()
    candidate = record(source_ids=["x" * 66000])
    with pytest.raises(ValueError, match="byte limit|metadata"):
        make_store(collection).upsert("generation", [candidate], [[1.0, 0.0]])
    assert collection.rows == {}


@pytest.mark.parametrize("revision", [None, 2**63])
def test_native_entity_revision_must_fit_the_milvus_integer_contract(revision):
    collection = MemoryCollection()
    candidate = record(graph_revision=revision)
    with pytest.raises(ValueError, match="revision"):
        make_store(collection).upsert("generation", [candidate], [[1.0, 0.0]])
    assert collection.rows == {}


@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
def test_failed_generation_scan_propagates_and_closes_the_iterator(monkeypatch, failure):
    collection = MemoryCollection()
    iterator = RowIterator([], 2)

    def interrupted():
        raise failure("interrupted generation read")

    monkeypatch.setattr(iterator, "next", interrupted)
    monkeypatch.setattr(collection, "query_iterator", lambda **kwargs: iterator)
    with pytest.raises(failure):
        make_store(collection).verify_generation(
            "generation", expected_count=0, expected_checksum=catalog_checksum([])
        )
    assert iterator.closed


def test_vector_reuse_is_scoped_and_conflicting_vectors_are_visible():
    collection = MemoryCollection()
    store = make_store(collection)
    candidate = record()
    store.upsert("first", [candidate], [[1.0, 0.0]])
    store.upsert("second", [record("other", source_ids=["new-source"])], [[1.0, 0.0]])
    assert store.reusable_vectors(scope_for(candidate), [candidate.text_hash]) == {
        candidate.text_hash: [1.0, 0.0]
    }
    assert (
        store.reusable_vectors(scope_for(candidate, domain_id="other"), [candidate.text_hash]) == {}
    )
    assert (
        store.reusable_vectors(
            scope_for(candidate, ontology_fingerprint="b" * 64), [candidate.text_hash]
        )
        == {}
    )
    with pytest.raises(ValueError, match="embedding"):
        store.reusable_vectors(
            scope_for(candidate, embedding_fingerprint="b" * 64), [candidate.text_hash]
        )
    store.upsert("third", [record("third")], [[0.0, 1.0]])
    with pytest.raises(ValueError, match="Ambiguous|conflicting"):
        store.reusable_vectors(scope_for(candidate), [candidate.text_hash])
    assert all(iterator.closed for iterator in collection.iterators)


def test_generation_verification_reads_actual_rows_across_pages():
    collection = MemoryCollection()
    store = make_store(collection)
    candidates = [record(str(i)) for i in range(5)]
    store.upsert("generation", candidates, [[1.0, 0.0]] * 5)
    verified = store.verify_generation(
        "generation", expected_count=5, expected_checksum=catalog_checksum(candidates)
    )
    assert (
        verified.valid and verified.count == 5 and verified.checksum == catalog_checksum(candidates)
    )
    assert re.fullmatch("[0-9a-f]{64}", verified.schema_fingerprint)
    collection.rows.pop(next(iter(collection.rows)))
    incomplete = store.verify_generation(
        "generation", expected_count=5, expected_checksum=catalog_checksum(candidates)
    )
    assert not incomplete.valid and incomplete.count == 4
    assert incomplete.checksum != verified.checksum
    assert all(iterator.closed for iterator in collection.iterators)
    empty = store.verify_generation(
        "empty", expected_count=0, expected_checksum=catalog_checksum([])
    )
    assert empty.valid and empty.count == 0


def test_generation_verification_rejects_duplicate_identity_and_closes_failed_iterator():
    collection = MemoryCollection()
    store = make_store(collection)
    candidate = record()
    store.upsert("generation", [candidate], [[1.0, 0.0]])
    row = copy.deepcopy(next(iter(collection.rows.values())))
    collection.rows["injected"] = row
    with pytest.raises(ValueError, match="Duplicate|duplicate"):
        store.verify_generation("generation", expected_count=2, expected_checksum="x")
    assert collection.iterators[-1].closed


@pytest.mark.parametrize(
    "change", ["dimension", "model", "fingerprint", "dynamic", "metric", "field"]
)
def test_incompatible_schema_or_index_is_rejected_without_modification(change):
    schema_changes: dict[str, dict[str, int | str | bool]] = {
        "dimension": {"dimension": 3},
        "model": {"embedding_model": "other"},
        "fingerprint": {"fingerprint": "f" * 64},
        "dynamic": {"dynamic": True},
        "metric": {},
        "field": {},
    }
    collection = MemoryCollection(candidate_schema(**schema_changes[change]))
    if change == "metric":
        collection.index_definition.params["metric_type"] = "IP"
    if change == "field":
        collection.schema.fields.pop()
    with pytest.raises(ValueError, match="schema|embedding|metric|index"):
        make_store(collection)
    assert collection.rows == {}


def test_borrowed_collection_is_not_closed_by_adapter_and_missing_index_is_recovered(
    monkeypatch,
):
    from gustobot.infrastructure.knowledge import semantic_index

    disconnected: list[str] = []
    monkeypatch.setattr(semantic_index.connections, "disconnect", disconnected.append)
    collection = MemoryCollection(indexed=False)
    store = make_store(collection)
    assert collection.indexed and collection.index_definition.params["metric_type"] == "COSINE"
    store.close()
    store.close()
    assert disconnected == []


def test_owned_connection_is_closed_on_initialization_failure(monkeypatch):
    from gustobot.infrastructure.knowledge import semantic_index

    connected: list[str] = []
    disconnected: list[str] = []
    collection = MemoryCollection(candidate_schema(embedding_model="other"))
    monkeypatch.setattr(
        semantic_index.connections,
        "connect",
        lambda **kwargs: connected.append(kwargs["alias"]),
    )
    monkeypatch.setattr(semantic_index.connections, "disconnect", disconnected.append)
    monkeypatch.setattr(semantic_index.utility, "has_collection", lambda *args, **kwargs: True)
    monkeypatch.setattr(semantic_index, "Collection", lambda *args, **kwargs: collection)
    with pytest.raises(ValueError):
        semantic_index.SemanticCandidateStore(
            embedding_model="fixture", embedding_fingerprint=FINGERPRINT, dimension=2
        )
    assert disconnected == connected and len(connected) == 1


def test_initialization_budget_is_separate_from_ann_budget(monkeypatch):
    collection = MemoryCollection(indexed=False)
    load_timeouts = []
    index_timeouts = []
    monkeypatch.setattr(
        collection, "load", lambda **kwargs: load_timeouts.append(kwargs["timeout"])
    )
    create_index = collection.create_index

    def indexed(**kwargs):
        index_timeouts.append(kwargs["timeout"])
        return create_index(**kwargs)

    monkeypatch.setattr(collection, "create_index", indexed)
    store = make_store(collection, timeout=0.25, initialization_timeout=15.0)
    candidate = record()
    store.upsert("generation", [candidate], [[1.0, 0.0]])
    assert (
        store.search(
            [1.0, 0.0],
            scope=scope_for(candidate),
            generation_id="generation",
            expected_types=["RecipeVariant"],
            top_k=1,
        )[0].ref_id
        == candidate.ref_id
    )
    assert load_timeouts == index_timeouts == [15.0]
    assert collection.searches[0]["timeout"] == 0.25


def test_delete_generation_is_exact_and_cannot_accept_an_expression():
    collection = MemoryCollection()
    store = make_store(collection)
    store.upsert("keep", [record()], [[1.0, 0.0]])
    store.upsert("retire", [record()], [[1.0, 0.0]])
    with pytest.raises(ValueError, match="generation"):
        store.delete_generation('retire" or generation_id != "')
    store.delete_generation("retire")
    assert {row["generation_id"] for row in collection.rows.values()} == {"keep"}


@pytest.fixture
def actual_milvus_collection():
    from pymilvus import connections, utility

    config_path = os.getenv("GUSTOBOT_MILVUS_TEST_CONFIG")
    if config_path is None:
        pytest.skip("isolated Milvus config not provided")
    assert config_path is not None
    with open(config_path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    name = "candidate_test_" + uuid4().hex
    cleanup_alias = "cleanup_" + uuid4().hex
    try:
        connections.connect(
            alias=cleanup_alias, host=config["host"], port=config["port"], timeout=30
        )
        try:
            yield {
                "collection_name": name,
                "embedding_model": "fixture",
                "embedding_fingerprint": FINGERPRINT,
                "dimension": 2,
                "host": config["host"],
                "port": config["port"],
                "cleanup_alias": cleanup_alias,
            }
        finally:
            if utility.has_collection(name, using=cleanup_alias, timeout=30):
                utility.drop_collection(name, using=cleanup_alias, timeout=30)
    finally:
        connections.disconnect(cleanup_alias)


def actual_store_options(config):
    return {key: value for key, value in config.items() if key != "cleanup_alias"}


def test_actual_milvus_candidate_scope_verification_and_reopen(
    actual_milvus_collection,
):
    from pymilvus import Collection, connections

    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

    options = actual_store_options(actual_milvus_collection)
    store = SemanticCandidateStore(**options)
    try:
        candidates = [
            record("a", label="番茄炒鸡蛋"),
            record("b", label="青椒炒鸡蛋"),
            record("ingredient", label="番茄", object_type="Ingredient"),
        ]
        store.upsert("active", candidates, [[0.8, 0.6], [0.0, 1.0], [1.0, 0.0]])
        store.upsert("pending", [record("pending", label="待发布做法")], [[1.0, 0.0]])
        store.upsert("foreign", [record("foreign", domain_id="other")], [[1.0, 0.0]])
        store.upsert("concept", [record("concept", kind="concept")], [[1.0, 0.0]])
        result = store.search(
            [1.0, 0.0],
            scope=scope_for(),
            generation_id="active",
            expected_types=["RecipeVariant"],
            top_k=1,
        )
        assert [hit.ref_id for hit in result] == ["a"]
        assert result[0].vector_score == pytest.approx(0.8)
        assert (
            store.search(
                [1.0, 0.0],
                scope=scope_for(domain_id="other"),
                generation_id="active",
                expected_types=["RecipeVariant"],
                top_k=1,
            )
            == []
        )
        assert (
            store.search(
                [1.0, 0.0],
                scope=scope_for(kind="concept"),
                generation_id="active",
                expected_types=["Class"],
                top_k=1,
            )
            == []
        )
        assert (
            store.search(
                [1.0, 0.0],
                scope=scope_for(ontology_version="old"),
                generation_id="active",
                expected_types=["RecipeVariant"],
                top_k=1,
            )
            == []
        )
        assert store.reusable_vectors(scope_for(), [candidates[0].text_hash])[
            candidates[0].text_hash
        ] == pytest.approx([0.8, 0.6])
        assert store.verify_generation(
            "active", expected_count=3, expected_checksum=catalog_checksum(candidates)
        ).valid
        store.close()
        store.close()
        assert not connections.has_connection(store._connection_alias)
        store = SemanticCandidateStore(**options)
        assert store.verify_generation(
            "active", expected_count=3, expected_checksum=catalog_checksum(candidates)
        ).valid
        store.upsert("active", [candidates[0]], [[0.8, 0.6]])
        for changes in (
            {"dimension": 3},
            {"embedding_model": "other"},
            {"embedding_fingerprint": "b" * 64},
        ):
            with pytest.raises(ValueError, match="schema|embedding"):
                SemanticCandidateStore(**(options | changes))
        assert store.verify_generation(
            "active", expected_count=3, expected_checksum=catalog_checksum(candidates)
        ).valid
        store.delete_generation("pending")
        assert store.verify_generation(
            "pending", expected_count=0, expected_checksum=catalog_checksum([])
        ).valid
        deleted = store.collection.query(
            expr='generation_id == "active" and ref_id == "b"',
            output_fields=["id"],
            limit=1,
            consistency_level="Strong",
            timeout=10,
        )
        store.collection.delete(expr="id in " + json.dumps([deleted[0]["id"]]), timeout=10)
        remaining = store.verify_generation(
            "active", expected_count=3, expected_checksum=catalog_checksum(candidates)
        )
        assert not remaining.valid and remaining.count == 2
        assert remaining.checksum == catalog_checksum([candidates[0], candidates[2]])
        native = Collection(
            options["collection_name"],
            using=actual_milvus_collection["cleanup_alias"],
            timeout=30,
        )
        borrowed = SemanticCandidateStore(**options, collection=native)
        borrowed.close()
        assert connections.has_connection(actual_milvus_collection["cleanup_alias"])
        assert borrowed.verify_generation(
            "active", expected_count=2, expected_checksum=remaining.checksum
        ).valid
    finally:
        store.close()


def test_actual_milvus_generation_verification_reads_every_page(
    actual_milvus_collection,
):
    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

    store = SemanticCandidateStore(**actual_store_options(actual_milvus_collection), timeout=10)
    try:
        candidates = [record(f"page-{index}", label=f"目录 {index}") for index in range(517)]
        store.upsert("paged", candidates, [[1.0, 0.0]] * len(candidates))
        verification = store.verify_generation(
            "paged", expected_count=517, expected_checksum=catalog_checksum(candidates)
        )
        assert verification.valid and verification.count == 517
        assert not store.verify_generation(
            "paged", expected_count=516, expected_checksum=verification.checksum
        ).valid
    finally:
        store.close()


def test_actual_milvus_partial_index_recovery_preserves_incompatible_collection(
    actual_milvus_collection,
):
    from pymilvus import Collection

    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

    options = actual_store_options(actual_milvus_collection)
    native = Collection(
        options["collection_name"],
        schema=candidate_schema(),
        using=actual_milvus_collection["cleanup_alias"],
        consistency_level="Strong",
        timeout=30,
    )
    assert not native.has_index(timeout=30)
    store = SemanticCandidateStore(**options)
    try:
        candidate = record()
        store.upsert("keep", [candidate], [[1.0, 0.0]])
        assert native.index(timeout=30).params["metric_type"] == "COSINE"
    finally:
        store.close()
    native.release(timeout=30)
    native.drop_index(timeout=30)
    native.create_index(
        field_name="embedding",
        index_params={
            "index_type": "HNSW",
            "metric_type": "IP",
            "params": {"M": 16, "efConstruction": 128},
        },
        timeout=30,
    )
    with pytest.raises(ValueError, match="index|metric"):
        SemanticCandidateStore(**options)
    native.load(timeout=30)
    preserved = native.query(
        expr='generation_id == "keep"',
        output_fields=["ref_id"],
        limit=1,
        consistency_level="Strong",
        timeout=10,
    )
    assert [row["ref_id"] for row in preserved] == [candidate.ref_id]
    assert native.index(timeout=30).params["metric_type"] == "IP"


@pytest.mark.parametrize("scale", [1e-100, 1e-30, 1e30])
def test_actual_cosine_vectors_preserve_direction_at_finite_scales(actual_milvus_collection, scale):
    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

    store = SemanticCandidateStore(**actual_store_options(actual_milvus_collection))
    try:
        candidate = record()
        store.upsert("direction_regression", [candidate], [[scale, 0.0]])
        hits = store.search(
            [1.0, 0.0],
            scope=scope_for(candidate),
            generation_id="direction_regression",
            expected_types=[],
            top_k=1,
        )
        assert len(hits) == 1
        assert hits[0].vector_score == pytest.approx(1.0)
    finally:
        store.close()


def test_reused_float32_vector_does_not_poison_a_third_generation():
    import struct

    class Float32Collection(MemoryCollection):
        def upsert(self, rows, **kwargs):
            for row in rows:
                row["embedding"] = [
                    struct.unpack("f", struct.pack("f", value))[0] for value in row["embedding"]
                ]
            return super().upsert(rows, **kwargs)

    store = make_store(Float32Collection())
    candidate = record()
    scope = scope_for(candidate)
    store.upsert("before", [candidate], [[0.27258219476685697, 0.3971638346291191]])
    for index in range(4):
        reusable = store.reusable_vectors(scope, [candidate.text_hash])
        store.upsert(
            f"after_{index}", [record(graph_revision=index + 2)], [reusable[candidate.text_hash]]
        )
    assert candidate.text_hash in store.reusable_vectors(scope, [candidate.text_hash])


def test_actual_float32_reuse_is_idempotent_across_generations(actual_milvus_collection):
    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

    store = SemanticCandidateStore(**actual_store_options(actual_milvus_collection), timeout=10)
    try:
        candidate = record()
        scope = scope_for(candidate)
        store.upsert("first", [candidate], [[0.27258219476685697, 0.3971638346291191]])
        first = store.reusable_vectors(scope, [candidate.text_hash])[candidate.text_hash]
        for index in range(3):
            reusable = store.reusable_vectors(scope, [candidate.text_hash])[candidate.text_hash]
            assert reusable == first
            store.upsert(f"reuse_{index}", [record(graph_revision=index + 3)], [reusable])
        assert store.reusable_vectors(scope, [candidate.text_hash])[candidate.text_hash] == first
    finally:
        store.close()
