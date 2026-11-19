"""Document ingestion preserves provenance and pays only for new embeddings."""

import json
import os
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from gustobot.domain.knowledge import DomainDefinition, SourceDocument


class MemoryVectors:
    def __init__(self):
        self.rows = {}
        self.searches = []

    def existing_ids(self, ids):
        return set(ids) & self.rows.keys()

    def read_chunk(self, chunk_id, **scope):
        stored = self.rows.get(chunk_id)
        if stored is None:
            return None
        chunk, _ = stored
        return (
            chunk if all(getattr(chunk, field) == value for field, value in scope.items()) else None
        )

    def upsert(self, chunks, embeddings):
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self.rows[chunk.id] = (chunk, embedding)

    def refresh_entity_links(self, chunks, *, replace_entity_ids=True):
        for chunk in chunks:
            existing, embedding = self.rows[chunk.id]
            if existing.model_dump(exclude={"entity_ids"}) != chunk.model_dump(
                exclude={"entity_ids"}
            ):
                raise ValueError("Existing chunk identity or URI cannot change")
            if replace_entity_ids:
                self.rows[chunk.id] = (chunk, embedding)

    def search(self, embedding, **scope):
        self.searches.append(scope)
        hits = []
        for chunk, _ in self.rows.values():
            if chunk.domain_id != scope["domain_id"]:
                continue
            if chunk.ontology_version != scope["ontology_version"]:
                continue
            versions = scope.get("source_versions")
            if versions is not None and versions.get(chunk.source_id) != chunk.source_version:
                continue
            if scope.get("entity_ids") and not set(chunk.entity_ids).intersection(
                scope["entity_ids"]
            ):
                continue
            hits.append({"chunk": chunk, "score": 0.9})
        return hits[: scope["top_k"]]

    def close(self):
        pass


class Embeddings:
    def __init__(self):
        self.documents = []
        self.queries = []

    def embed_documents(self, texts):
        self.documents.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        self.queries.append(text)
        return [1.0, 0.0]

    def close(self):
        pass


def document_domain(domain_id: str = "recipes") -> DomainDefinition:
    return DomainDefinition(
        id=domain_id,
        version="1",
        name="Document tests",
        description="Standalone document ingestion and retrieval tests",
        entity_types={},
        relation_types={},
        document_scope="Test documents",
    )


def service(vectors=None, embeddings=None, versions=None):
    from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService

    return KnowledgeService(
        domain=document_domain(),
        vector_store=MemoryVectors() if vectors is None else vectors,
        embedder=Embeddings() if embeddings is None else embeddings,
        embedding_model="test-embedding",
        reranker=False,
        chunk_size=48,
        chunk_overlap=8,
        source_versions=versions,
    )


@pytest.mark.asyncio
async def test_source_is_chunked_once_and_repeat_import_reuses_existing_embeddings():
    vectors, embeddings = MemoryVectors(), Embeddings()
    knowledge = service(vectors, embeddings)
    source = SourceDocument(id="manual", text="先炒鸡蛋，再炒番茄。" * 15, uri="manual.txt")
    first = await knowledge.ingest_source(source, entity_ids=["recipe-1"])
    second = await knowledge.ingest_source(source, entity_ids=["recipe-1"])
    assert first.chunks > 1
    assert first.version == second.version
    assert second.embedded == 0
    assert len(embeddings.documents) == 1
    assert len(vectors.rows) == first.chunks
    for chunk, _ in vectors.rows.values():
        assert chunk.domain_id == "recipes"
        assert chunk.source_id == "manual"
        assert chunk.source_version == first.version
        assert chunk.uri == "manual.txt"
        assert chunk.entity_ids == ["recipe-1"]
        assert chunk.content in source.text


@pytest.mark.asyncio
async def test_search_uses_published_source_version_and_returns_actual_provenance():
    vectors, embeddings = MemoryVectors(), Embeddings()
    published: dict[str, str] = {}
    knowledge = service(vectors, embeddings, lambda: dict(published))
    old = await knowledge.ingest_source(SourceDocument(id="manual", text="旧做法：先炒番茄。"))
    new = await knowledge.ingest_source(SourceDocument(id="manual", text="新做法：先炒鸡蛋。"))
    assert old.version != new.version
    published["manual"] = new.version
    result = await knowledge.search("先炒什么？", top_k=5)
    assert len(result) == 1
    assert result[0]["content"] == "新做法：先炒鸡蛋。"
    assert result[0]["metadata"]["source_id"] == "manual"
    assert result[0]["metadata"]["source_version"] == new.version
    assert vectors.searches[0]["domain_id"] == "recipes"
    assert vectors.searches[0]["source_versions"] == published


@pytest.mark.asyncio
async def test_no_published_documents_does_not_call_embedding_or_return_pending_chunks():
    vectors, embeddings = MemoryVectors(), Embeddings()
    knowledge = service(vectors, embeddings, dict)
    await knowledge.ingest_source(SourceDocument(id="pending", text="尚未发布的资料"))
    assert await knowledge.search("资料是什么？") == []
    assert embeddings.queries == []
    assert vectors.searches == []


@pytest.mark.asyncio
async def test_embedding_failure_does_not_write_or_report_success():
    class Broken(Embeddings):
        def embed_documents(self, texts):
            raise RuntimeError("embedding unavailable")

    vectors = MemoryVectors()
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await service(vectors, Broken()).ingest_source(SourceDocument(id="x", text="资料"))
    assert not vectors.rows


def test_pdf_docx_and_plain_sources_share_the_managed_parser(tmp_path):
    from docx import Document

    from gustobot.application.services.knowledge_ingestion import parse_document

    plain = tmp_path / "manual.txt"
    plain.write_text("先炒鸡蛋。", encoding="utf-8")
    assert parse_document(plain) == "先炒鸡蛋。"
    word = tmp_path / "manual.docx"
    document = Document()
    document.add_paragraph("番茄出汁后放鸡蛋。")
    document.save(word)
    assert "番茄出汁后放鸡蛋。" in parse_document(word)
    unsupported = tmp_path / "manual.exe"
    unsupported.write_bytes(b"ignored")
    with pytest.raises(ValueError, match="不支持|Unsupported"):
        parse_document(unsupported)


@pytest.mark.asyncio
async def test_search_rejects_missing_or_failed_source_version_provider():
    knowledge = service()
    with pytest.raises(ValueError, match="published|source_versions"):
        await knowledge.search("资料")
    assert knowledge.embedder.queries == []

    def unavailable():
        raise OSError("metadata database unavailable")

    knowledge = service(versions=unavailable)
    with pytest.raises(OSError, match="metadata database unavailable"):
        await knowledge.search("资料")
    assert knowledge.embedder.queries == []


@pytest.mark.asyncio
async def test_changed_chunking_or_embedding_model_cannot_overwrite_an_existing_chunk():
    from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService

    vectors, embeddings = MemoryVectors(), Embeddings()
    original = service(vectors, embeddings)
    source = SourceDocument(id="manual", text="先炒鸡蛋，再炒番茄。" * 15)
    first = await original.ingest_source(source)
    initial_rows = dict(vectors.rows)
    other = KnowledgeService(
        domain=document_domain(),
        vector_store=vectors,
        embedder=embeddings,
        embedding_model="other-model",
        reranker=False,
        chunk_size=32,
        chunk_overlap=8,
    )
    second = await other.ingest_source(source)
    assert first.version == second.version
    assert len(vectors.rows) == first.chunks + second.chunks
    assert all(vectors.rows[id] == row for id, row in initial_rows.items())


@pytest.mark.asyncio
async def test_truncated_embedding_batch_does_not_write_any_chunks():
    class Truncated(Embeddings):
        def embed_documents(self, texts):
            return []

    vectors = MemoryVectors()
    with pytest.raises(ValueError, match="count|match"):
        await service(vectors, Truncated()).ingest_source(SourceDocument(id="x", text="资料"))
    assert vectors.rows == {}


@pytest.mark.asyncio
async def test_service_never_closes_injected_dependencies(monkeypatch):
    closed = []
    vectors, embeddings = MemoryVectors(), Embeddings()
    monkeypatch.setattr(vectors, "close", lambda: closed.append("vectors"))
    monkeypatch.setattr(embeddings, "close", lambda: closed.append("embeddings"))
    await service(vectors, embeddings).close()
    assert closed == []


@pytest.mark.asyncio
async def test_explicit_entity_link_refresh_reuses_ids_and_embeddings_without_stale_matches():
    vectors, embeddings = MemoryVectors(), Embeddings()
    published: dict[str, str] = {}
    knowledge = service(vectors, embeddings, lambda: dict(published))
    source = SourceDocument(id="linkable", text="番茄出汁后放鸡蛋。", uri="managed.txt")
    first = await knowledge.ingest_source(source, entity_ids=[])
    first_ids = set(vectors.rows)
    second = await knowledge.ingest_source(source, entity_ids=["recipe-1"])
    assert second.version == first.version and second.embedded == 0
    assert set(vectors.rows) == first_ids
    assert len(embeddings.documents) == 1
    assert all(chunk.entity_ids == ["recipe-1"] for chunk, _ in vectors.rows.values())
    published["linkable"] = first.version
    assert len(await knowledge.search("步骤", entity_ids=["recipe-1"])) == 1
    await knowledge.ingest_source(source, entity_ids=["recipe-2"])
    assert await knowledge.search("步骤", entity_ids=["recipe-1"]) == []
    assert len(await knowledge.search("步骤", entity_ids=["recipe-2"])) == 1
    await knowledge.ingest_source(source)
    assert len(await knowledge.search("步骤", entity_ids=["recipe-2"])) == 1
    await knowledge.ingest_source(source, entity_ids=[])
    assert await knowledge.search("步骤", entity_ids=["recipe-2"]) == []
    assert len(embeddings.documents) == 1


@pytest.mark.asyncio
async def test_repeat_source_cannot_change_uri_without_changing_source_identity():
    knowledge = service()
    await knowledge.ingest_source(
        SourceDocument(id="immutable-uri", text="资料", uri="original.txt")
    )
    with pytest.raises(ValueError, match="URI|identity"):
        await knowledge.ingest_source(
            SourceDocument(id="immutable-uri", text="资料", uri="other.txt")
        )


@pytest.mark.parametrize("extension", ["txt", "md", "log", "json", "csv"])
def test_plain_document_parser_preserves_original_text(tmp_path, extension):
    from gustobot.application.services.knowledge_ingestion import parse_document

    contents = {"json": '{"糖": null, "盐": 0}', "csv": "材料,用量\n糖,\n盐,0\n"}
    original = contents.get(extension, "  先炒鸡蛋。\n")
    path = tmp_path / f"manual.{extension}"
    path.write_text(original, encoding="utf-8-sig")
    assert parse_document(path) == original


def test_pdf_parser_rejects_documents_requiring_ocr(tmp_path):
    from pypdf import PdfWriter

    from gustobot.application.services.knowledge_ingestion import parse_document

    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(ValueError, match="OCR|extractable"):
        parse_document(path)


def test_docx_parser_includes_table_cells(tmp_path):
    from docx import Document

    from gustobot.application.services.knowledge_ingestion import parse_document

    path = tmp_path / "table.docx"
    document = Document()
    document.add_paragraph("材料用量")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "糖"
    table.cell(0, 1).text = "未知"
    document.save(path)
    parsed = parse_document(path)
    assert "材料用量" in parsed and "糖" in parsed and "未知" in parsed


class MilvusCollection:
    """Records actual collection-boundary arguments, without mocking document behavior."""

    def __init__(self, *, dimension=2, embedding_model="test-embedding"):
        from pymilvus import CollectionSchema, DataType, FieldSchema

        self.schema = CollectionSchema(
            fields=[
                FieldSchema("id", DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=dimension),
                FieldSchema("domain_id", DataType.VARCHAR, max_length=256),
                FieldSchema("source_id", DataType.VARCHAR, max_length=1024),
                FieldSchema("source_version", DataType.VARCHAR, max_length=64),
                FieldSchema("ontology_version", DataType.VARCHAR, max_length=256),
                FieldSchema("embedding_model", DataType.VARCHAR, max_length=256),
                FieldSchema("chunk_index", DataType.INT64),
                FieldSchema("content", DataType.VARCHAR, max_length=65535),
                FieldSchema("metadata", DataType.JSON),
            ],
            description=json.dumps(
                {"schema_version": "gustobot_documents_v1", "embedding_model": embedding_model}
            ),
            auto_id=False,
            enable_dynamic_field=False,
        )
        self.rows = []
        self.calls = []

    def upsert(self, rows, **kwargs):
        existing = {row["id"]: row for row in self.rows}
        existing.update({row["id"]: row for row in rows})
        self.rows = list(existing.values())
        self.calls.append(("upsert", kwargs))
        return SimpleNamespace(upsert_count=len(rows))

    def query(self, **kwargs):
        self.calls.append(("query", kwargs))
        return [{key: row[key] for key in kwargs["output_fields"]} for row in self.rows]

    def search(self, **kwargs):
        self.calls.append(("search", kwargs))
        return [[SimpleNamespace(entity=row, score=0.9) for row in self.rows]]


def document_chunk():
    from gustobot.infrastructure.knowledge.vector_store import DocumentChunk

    return DocumentChunk(
        id="a" * 64,
        domain_id="recipes",
        source_id="manual",
        source_version="v1",
        ontology_version="1",
        embedding_model="test-embedding",
        chunk_index=0,
        content="糖的用量未知",
        uri=None,
        entity_ids=["recipe-1"],
    )


def test_milvus_adapter_preserves_provenance_and_constrains_search_before_ranking():
    from gustobot.infrastructure.knowledge.vector_store import VectorStore

    chunk = document_chunk()
    collection = MilvusCollection()
    vectors = VectorStore(collection=collection, dimension=2, embedding_model="test-embedding")
    vectors.upsert([chunk], [[1.0, 0.0]])
    assert vectors.existing_ids([chunk.id]) == {chunk.id}
    result = vectors.search(
        [1.0, 0.0],
        domain_id="recipes",
        ontology_version="1",
        source_versions={"manual": "v1"},
        entity_ids=["recipe-1"],
        top_k=3,
    )
    assert result[0]["chunk"] == chunk
    assert result[0]["score"] == 0.9
    expression = collection.calls[-1][1]["expr"]
    assert expression == (
        'domain_id == "recipes" and ontology_version == "1" and embedding_model == "test-embedding" '
        'and ((source_id == "manual" and source_version == "v1")) '
        'and JSON_CONTAINS_ANY(metadata["entity_ids"], ["recipe-1"])'
    )
    assert collection.rows[0]["metadata"] == {"uri": None, "entity_ids": ["recipe-1"]}


def test_chunk_read_queries_only_scoped_scalar_fields_without_embeddings():
    from gustobot.infrastructure.knowledge.vector_store import VectorStore

    chunk = document_chunk().model_copy(
        update={"source_id": 'guide"\\版本', "ontology_version": "previous-ontology"}
    )
    collection, embeddings = MilvusCollection(), Embeddings()
    vectors = VectorStore(collection=collection, dimension=2, embedding_model="test-embedding")
    vectors.upsert([chunk], [[1.0, 0.0]])
    collection.calls.clear()
    knowledge = service(vectors, embeddings)

    read = knowledge.read_chunk(
        chunk.id,
        source_id=chunk.source_id,
        source_version=chunk.source_version,
        ontology_version=chunk.ontology_version,
    )

    assert read is not None and read.content == "糖的用量未知"
    assert embeddings.documents == embeddings.queries == []
    assert [name for name, _ in collection.calls] == ["query"]
    parameters = collection.calls[0][1]
    assert parameters["limit"] == 1 and parameters["consistency_level"] == "Strong"
    assert set(parameters["output_fields"]) == {
        "id",
        "domain_id",
        "source_id",
        "source_version",
        "ontology_version",
        "embedding_model",
        "chunk_index",
        "content",
    }
    assert parameters["expr"] == (
        f'id == "{chunk.id}" and domain_id == "recipes" and '
        r'source_id == "guide\"\\版本" and source_version == "v1" and '
        'ontology_version == "previous-ontology" and embedding_model == "test-embedding"'
    )
    with pytest.raises(ValueError, match="scope"):
        knowledge.read_chunk(
            chunk.id, source_id="wrong", source_version="v1", ontology_version="previous-ontology"
        )


@pytest.mark.parametrize("dimension,model", [(3, "test-embedding"), (2, "different-model")])
def test_milvus_adapter_rejects_incompatible_existing_collections(dimension, model):
    from gustobot.infrastructure.knowledge.vector_store import VectorStore

    with pytest.raises(ValueError, match="schema|model|dimension"):
        VectorStore(
            collection=MilvusCollection(dimension=dimension, embedding_model=model),
            dimension=2,
            embedding_model="test-embedding",
        )


def test_milvus_adapter_rejects_bad_embeddings_before_writing():
    from gustobot.infrastructure.knowledge.vector_store import VectorStore

    chunk = document_chunk()
    collection = MilvusCollection()
    vectors = VectorStore(collection=collection, dimension=2, embedding_model="test-embedding")
    with pytest.raises(ValueError, match="dimension"):
        vectors.upsert([chunk], [[1.0]])
    with pytest.raises(ValueError, match="count|match"):
        vectors.upsert([chunk], [])
    assert collection.rows == []


def test_milvus_link_refresh_reuses_stored_vectors_and_preserves_uri():
    from gustobot.infrastructure.knowledge.vector_store import VectorStore

    chunk = document_chunk()
    collection = MilvusCollection()
    vectors = VectorStore(collection=collection, dimension=2, embedding_model="test-embedding")
    vectors.upsert([chunk], [[0.5, 0.25]])
    updated = chunk.model_copy(update={"entity_ids": ["recipe-2"]})
    vectors.refresh_entity_links([updated])
    assert len(collection.rows) == 1
    assert collection.rows[0]["embedding"] == [0.5, 0.25]
    assert collection.rows[0]["metadata"] == {"uri": None, "entity_ids": ["recipe-2"]}
    with pytest.raises(ValueError, match="URI|identity"):
        vectors.refresh_entity_links([updated.model_copy(update={"uri": "different.txt"})])


@pytest.mark.parametrize("existing_index", [False, True])
def test_milvus_initialization_repairs_missing_index_and_rejects_wrong_metric(
    monkeypatch, existing_index
):
    from gustobot.infrastructure.knowledge import vector_store as module

    class InitializingCollection(MilvusCollection):
        def __init__(self):
            super().__init__()
            self.vector_index = (
                SimpleNamespace(
                    field_name="embedding", params={"index_type": "FLAT", "metric_type": "IP"}
                )
                if existing_index
                else None
            )
            self.loaded = False

        def has_index(self, **kwargs):
            return self.vector_index is not None

        def index(self, **kwargs):
            return self.vector_index

        def create_index(self, *, field_name, index_params, **kwargs):
            self.vector_index = SimpleNamespace(field_name=field_name, params=index_params)

        def load(self, **kwargs):
            if self.vector_index is None:
                raise RuntimeError("index missing")
            self.loaded = True

    collection = InitializingCollection()
    monkeypatch.setattr(module.connections, "connect", lambda **kwargs: None)
    monkeypatch.setattr(module.connections, "disconnect", lambda alias: None)
    monkeypatch.setattr(module.utility, "has_collection", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "Collection", lambda *args, **kwargs: collection)
    if existing_index:
        with pytest.raises(ValueError, match="index|metric"):
            module.VectorStore(
                dimension=2,
                embedding_model="test-embedding",
                index_type="FLAT",
                metric_type="COSINE",
            )
        assert not collection.loaded
    else:
        store = module.VectorStore(dimension=2, embedding_model="test-embedding", index_type="FLAT")
        assert collection.loaded
        assert collection.vector_index is not None
        assert collection.vector_index.field_name == "embedding"
        assert collection.vector_index.params["metric_type"] == "IP"
        store.close()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("GUSTOBOT_TEST_MILVUS_PORT"), reason="isolated Milvus not supplied"
)
async def test_isolated_milvus_ingestion_versions_link_refresh_and_schema_compatibility():
    from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService
    from gustobot.infrastructure.knowledge.vector_store import VectorStore

    name = "gustobot_documents_test_" + uuid4().hex
    options: dict[str, Any] = {
        "collection_name": name,
        "host": os.environ.get("GUSTOBOT_TEST_MILVUS_HOST", "127.0.0.1"),
        "port": int(os.environ["GUSTOBOT_TEST_MILVUS_PORT"]),
        "dimension": 2,
        "embedding_model": "test-embedding",
        "index_type": "FLAT",
    }
    vectors = VectorStore(**options)
    try:
        embeddings = Embeddings()
        published: dict[str, str] = {}
        knowledge = service(vectors, embeddings, lambda: dict(published))
        await knowledge.ingest_source(
            SourceDocument(id="manual", text="旧做法：先炒番茄。", uri="managed.txt")
        )
        current = SourceDocument(id="manual", text="新做法：先炒鸡蛋。", uri="managed.txt")
        result = await knowledge.ingest_source(current, entity_ids=[])
        published["manual"] = result.version
        assert await knowledge.search("步骤", entity_ids=["recipe-1"]) == []
        linked = await knowledge.ingest_source(current, entity_ids=["recipe-1"])
        assert linked.ids == result.ids and linked.embedded == 0
        assert len(embeddings.documents) == 2
        hits = await knowledge.search("步骤", entity_ids=["recipe-1"])
        assert len(hits) == 1
        assert hits[0]["content"] == current.text
        assert hits[0]["metadata"]["source_version"] == result.version
        assert hits[0]["metadata"]["uri"] == "managed.txt"
        await knowledge.ingest_source(current, entity_ids=["recipe-2"])
        assert await knowledge.search("步骤", entity_ids=["recipe-1"]) == []
        assert len(await knowledge.search("步骤", entity_ids=["recipe-2"])) == 1
        other = KnowledgeService(
            domain=document_domain("equipment"),
            vector_store=vectors,
            embedder=embeddings,
            embedding_model="test-embedding",
            reranker=False,
            source_versions=lambda: dict(published),
        )
        await other.ingest_source(
            SourceDocument(id="manual", text=current.text, uri="equipment.txt")
        )
        hits = await knowledge.search("步骤")
        assert len(hits) == 1 and hits[0]["metadata"]["domain_id"] == "recipes"
        with pytest.raises(ValueError, match="schema|model"):
            VectorStore(**{**options, "embedding_model": "different-model"})
        with pytest.raises(ValueError, match="index|metric"):
            mismatch = VectorStore(**{**options, "metric_type": "COSINE"})
            mismatch.close()
        vectors.collection.release(timeout=30)
        vectors.collection.drop_index(timeout=30)
        reopened = VectorStore(**options)
        try:
            assert reopened.existing_ids(result.ids) == set(result.ids)
        finally:
            reopened.close()
    finally:
        # This exact UUID collection was created by this test in the isolated service.
        try:
            vectors.collection.drop()
        finally:
            vectors.close()
