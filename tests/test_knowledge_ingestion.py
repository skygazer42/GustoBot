"""Explicit imports publish durable receipts without implicit model extraction."""

import asyncio
import hashlib
import importlib
import json
import threading
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.core.database import Base
from gustobot.infrastructure.knowledge.graph_store import GraphWriteResult
from gustobot.infrastructure.knowledge.knowledge_service import (
    DocumentEmbedder,
    DocumentIngestionResult,
    DocumentVectors,
    KnowledgeService,
)
from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository
from gustobot.infrastructure.persistence.db.models import (
    IngestionJob,
    KnowledgeSource,
    UploadedAsset,
)


def ingestion_api():
    return importlib.import_module("gustobot.application.services.knowledge_ingestion")


class Documents:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    async def ingest_source(self, source, *, entity_ids=None):
        self.calls.append((source, entity_ids))
        if self.failure is not None:
            raise self.failure
        return DocumentIngestionResult(
            domain_id="recipes",
            source_id=source.id,
            version=hashlib.sha256(source.text.encode()).hexdigest(),
            chunks=1,
            embedded=1,
            ids=["chunk-1"],
        )


class Facts:
    def __init__(self):
        self.graphs = []

    async def upsert(self, graph):
        self.graphs.append(graph)
        return GraphWriteResult(
            entities=len(graph.entities),
            relations=len(graph.relations),
            sources=len(graph.sources),
        )


@pytest.fixture
def storage(tmp_path, request):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    request.addfinalizer(engine.dispose)
    Base.metadata.create_all(engine)

    @contextmanager
    def transaction():
        with Session(engine, expire_on_commit=False) as session, session.begin():
            yield session

    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    yield SimpleNamespace(engine=engine, transaction=transaction, upload_root=upload_root)


def service(storage, *, documents=None, facts=None, transaction=None):
    api = ingestion_api()
    assert hasattr(api, "KnowledgeIngestionService"), "Explicit ingestion orchestration is missing"
    return api.KnowledgeIngestionService(
        get_domain_definition(),
        documents=Documents() if documents is None else documents,
        graph_store=Facts() if facts is None else facts,
        session_factory=storage.transaction if transaction is None else transaction,
        upload_root=storage.upload_root,
    )


@pytest.mark.asyncio
async def test_http_reimport_preserves_omitted_entity_links_and_explicit_empty_list_clears(
    storage,
):
    from gustobot.interfaces.http import knowledge_router

    class Vectors:
        def __init__(self):
            self.rows = {}

        def existing_ids(self, identifiers):
            return set(identifiers) & self.rows.keys()

        def upsert(self, chunks, embeddings):
            self.rows.update({chunk.id: chunk for chunk in chunks})

        def refresh_entity_links(self, chunks, *, replace_entity_ids):
            if replace_entity_ids:
                self.rows.update({chunk.id: chunk for chunk in chunks})

    class Embeddings:
        def embed_documents(self, texts):
            return [[1.0, 0.0] for _ in texts]

    vectors = Vectors()
    documents = KnowledgeService(
        domain=get_domain_definition(),
        vector_store=cast(DocumentVectors, vectors),
        embedder=cast(DocumentEmbedder, Embeddings()),
        embedding_model="test-embedding",
        reranker=False,
        chunk_size=1000,
        chunk_overlap=0,
    )
    importer = service(storage, documents=documents)
    app = FastAPI()
    app.include_router(knowledge_router.router)
    app.dependency_overrides[knowledge_router.get_ingestion_service] = lambda: importer
    base = {"text": "食材与做法资料", "source_id": "manual"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/knowledge/documents", json=base | {"entity_ids": ["recipe-1"]})
        assert first.status_code == 201
        repeated = await client.post("/knowledge/documents", json=base)
        assert repeated.status_code == 201
        assert all(chunk.entity_ids == ["recipe-1"] for chunk in vectors.rows.values())
        preserved = await client.post("/knowledge/documents", json=base | {"entity_ids": None})
        assert preserved.status_code == 201
        assert all(chunk.entity_ids == ["recipe-1"] for chunk in vectors.rows.values())
        cleared = await client.post("/knowledge/documents", json=base | {"entity_ids": []})
        assert cleared.status_code == 201
        assert all(chunk.entity_ids == [] for chunk in vectors.rows.values())


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.asyncio
async def test_failed_identical_reimport_does_not_unpublish_successful_version(storage, cancelled):
    request_type = ingestion_api().DocumentIngestionRequest
    original = await service(storage).ingest_document(
        request_type(text="原文", source_id="manual", metadata={"publication": "keep"})
    )
    failure = asyncio.CancelledError() if cancelled else RuntimeError("retry unavailable")
    importer = service(storage, documents=Documents(failure))

    with pytest.raises(asyncio.CancelledError if cancelled else ingestion_api().IngestionFailed):
        await importer.ingest_document(request_type(text="原文", source_id="manual"))

    with storage.transaction() as session:
        repository = KnowledgeRepository(session)
        source = repository.get_source("recipes", "manual", original.version)
        assert source is not None
        assert source.status == "ready"
        assert source.source_metadata is not None
        assert source.source_metadata["metadata"] == {"publication": "keep"}
        assert repository.published_versions("recipes") == {"manual": original.version}
        assert set(session.scalars(select(IngestionJob.status))) == {
            "ready",
            "cancelled" if cancelled else "failed",
        }


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.asyncio
async def test_failed_recipe_reimport_preserves_graph_publication_without_publishing_documents(
    storage, cancelled
):
    class BrokenFacts(Facts):
        async def upsert(self, graph):
            if cancelled:
                raise asyncio.CancelledError()
            raise RuntimeError("graph retry unavailable")

    original = await service(storage).ingest_recipe("佛跳墙", {"耗时": "未知"})
    importer = service(storage, facts=BrokenFacts())

    with pytest.raises(asyncio.CancelledError if cancelled else ingestion_api().IngestionFailed):
        await importer.ingest_recipe("佛跳墙", {"耗时": "未知"})

    with storage.transaction() as session:
        repository = KnowledgeRepository(session)
        source = repository.get_source("recipes", original.source_id, original.version)
        assert source is not None
        assert source.status == "graph_ready"
        assert source.source_metadata is not None
        assert source.source_metadata["kind"] == "recipe"
        assert repository.published_versions("recipes") == {}
        assert set(session.scalars(select(IngestionJob.status))) == {
            "graph_ready",
            "cancelled" if cancelled else "failed",
        }


@pytest.mark.asyncio
async def test_published_version_remains_available_while_identical_reimport_is_running(
    storage,
):
    class Waiting(Documents):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def ingest_source(self, source, *, entity_ids=None):
            self.started.set()
            await self.release.wait()
            return await super().ingest_source(source, entity_ids=entity_ids)

    request = ingestion_api().DocumentIngestionRequest(text="原文", source_id="manual")
    original = await service(storage).ingest_document(request)
    waiting = Waiting()
    task = asyncio.create_task(service(storage, documents=waiting).ingest_document(request))
    try:
        await asyncio.wait_for(waiting.started.wait(), timeout=5)
        with storage.transaction() as session:
            assert KnowledgeRepository(session).published_versions("recipes") == {
                "manual": original.version
            }
    finally:
        waiting.release.set()
        await task


@pytest.mark.asyncio
async def test_failed_new_content_keeps_the_previous_ready_version(storage):
    request_type = ingestion_api().DocumentIngestionRequest
    original = await service(storage).ingest_document(
        request_type(text="旧原文", source_id="manual")
    )
    importer = service(storage, documents=Documents(RuntimeError("new index unavailable")))

    with pytest.raises(ingestion_api().IngestionFailed):
        await importer.ingest_document(request_type(text="新原文", source_id="manual"))

    with storage.transaction() as session:
        assert KnowledgeRepository(session).published_versions("recipes") == {
            "manual": original.version
        }


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.asyncio
async def test_late_failure_cannot_unpublish_concurrent_success(storage, cancelled):
    class LateFailure(Documents):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def ingest_source(self, source, *, entity_ids=None):
            self.started.set()
            await self.release.wait()
            if cancelled:
                raise asyncio.CancelledError()
            raise RuntimeError("late retry failure")

    request = ingestion_api().DocumentIngestionRequest(text="原文", source_id="manual")
    late = LateFailure()
    task = asyncio.create_task(service(storage, documents=late).ingest_document(request))
    try:
        await asyncio.wait_for(late.started.wait(), timeout=5)
        successful = await service(storage).ingest_document(request)
        late.release.set()
        with pytest.raises(
            asyncio.CancelledError if cancelled else ingestion_api().IngestionFailed
        ):
            await task
    finally:
        late.release.set()
        with suppress(asyncio.CancelledError, ingestion_api().IngestionFailed):
            await task

    with storage.transaction() as session:
        repository = KnowledgeRepository(session)
        source = repository.get_source("recipes", "manual", successful.version)
        assert source is not None
        assert source.status == "ready"
        assert repository.published_versions("recipes") == {"manual": successful.version}


@pytest.mark.parametrize("first_kind", ["document", "recipe"])
@pytest.mark.asyncio
async def test_one_source_version_cannot_be_reused_as_a_different_ingestion_kind(
    storage, first_kind
):
    graph = recipe_to_facts("佛跳墙", {"耗时": "未知"})
    source = graph.sources[0]
    documents, facts = Documents(), Facts()
    importer = service(storage, documents=documents, facts=facts)
    request = ingestion_api().DocumentIngestionRequest(text=source.text, source_id=source.id)
    if first_kind == "document":
        original = await importer.ingest_document(request)
        with pytest.raises(ValueError, match="kind|类型"):
            await importer.ingest_recipe("佛跳墙", {"耗时": "未知"})
        assert not facts.graphs
    else:
        original = await importer.ingest_recipe("佛跳墙", {"耗时": "未知"})
        with pytest.raises(ValueError, match="kind|类型"):
            await importer.ingest_document(request)
        assert not documents.calls
    with storage.transaction() as session:
        stored = KnowledgeRepository(session).get_source("recipes", source.id, original.version)
        assert stored is not None
        assert stored.status == ("ready" if first_kind == "document" else "graph_ready")
        assert stored.source_metadata is not None
        assert stored.source_metadata["kind"] == first_kind


@pytest.mark.asyncio
async def test_failed_ontology_reprocessing_preserves_previous_publication(storage):
    request = ingestion_api().DocumentIngestionRequest(text="原文", source_id="manual")
    original = await service(storage).ingest_document(request)
    next_domain = get_domain_definition().model_copy(update={"version": "next-ontology"})
    importer = ingestion_api().KnowledgeIngestionService(
        next_domain,
        documents=Documents(RuntimeError("new ontology index unavailable")),
        session_factory=storage.transaction,
        upload_root=storage.upload_root,
    )

    with pytest.raises(ingestion_api().IngestionFailed):
        await importer.ingest_document(request)

    with storage.transaction() as session:
        repository = KnowledgeRepository(session)
        stored = repository.get_source("recipes", "manual", original.version)
        assert stored is not None
        assert stored.status == "ready"
        assert stored.ontology_version == original.ontology_version
        assert repository.published_versions(
            "recipes", ontology_version=original.ontology_version
        ) == {"manual": original.version}
        assert repository.published_versions("recipes", ontology_version="next-ontology") == {}


@pytest.mark.asyncio
async def test_text_import_preserves_raw_content_and_publishes_exact_version(storage):
    documents = Documents()
    importer = service(storage, documents=documents)
    request = ingestion_api().DocumentIngestionRequest(
        text='佛跳墙的糖用量未知。\n{"原始": 0}',
        source_id="manual",
        entity_ids=["recipe-1"],
        metadata={"verified": False},
    )

    receipt = await importer.ingest_document(request)

    assert receipt.status == "ready"
    assert receipt.version == hashlib.sha256(request.text.encode()).hexdigest()
    assert documents.calls[0][0].text == request.text
    assert documents.calls[0][1] == ["recipe-1"]
    with storage.transaction() as session:
        repository = KnowledgeRepository(session)
        source = repository.get_source("recipes", "manual", receipt.version)
        assert source is not None
        assert source.text == request.text
        assert source.uri == "manual"
        assert source.status == "ready"
        assert source.source_metadata is not None
        assert source.source_metadata["metadata"] == {"verified": False}
        job = repository.get_job(receipt.job_id)
        assert job is not None
        assert job.status == "ready"
        assert repository.published_versions("recipes") == {"manual": receipt.version}


@pytest.mark.asyncio
async def test_retries_preserve_source_identity_and_revisions_do_not_overwrite_text(
    storage,
):
    importer = service(storage)
    request_type = ingestion_api().DocumentIngestionRequest

    first = await importer.ingest_document(request_type(text="糖适量", source_id="manual"))
    repeated = await importer.ingest_document(request_type(text="糖适量", source_id="manual"))
    revised = await importer.ingest_document(request_type(text="糖 20g", source_id="manual"))

    assert first.source_id == repeated.source_id == revised.source_id == "manual"
    assert first.version == repeated.version != revised.version
    assert first.job_id != repeated.job_id
    with storage.transaction() as session:
        sources = session.scalars(select(KnowledgeSource)).all()
        assert {source.text for source in sources} == {"糖适量", "糖 20g"}
        assert len(sources) == 2


@pytest.mark.asyncio
async def test_managed_asset_is_parsed_without_sending_server_path_to_index(storage):
    path = storage.upload_root / "asset.txt"
    path.write_text("原始资料\n糖适量。", encoding="utf-8")
    with storage.transaction() as session:
        KnowledgeRepository(session).register_asset(
            id="asset-1",
            original_name="配方.txt",
            path=str(path),
            file_type=".txt",
            size=path.stat().st_size,
        )
    documents = Documents()
    importer = service(storage, documents=documents)

    receipt = await importer.ingest_document(
        ingestion_api().DocumentIngestionRequest(asset_id="asset-1")
    )

    source = documents.calls[0][0]
    assert source.text == "原始资料\n糖适量。"
    assert str(storage.upload_root) not in source.model_dump_json()
    assert receipt.status == "ready"
    assert receipt.source_id == "asset:asset-1"


@pytest.mark.asyncio
async def test_registered_asset_outside_upload_root_is_rejected_before_indexing(storage, tmp_path):
    path = tmp_path / "private.txt"
    path.write_text("private", encoding="utf-8")
    with storage.transaction() as session:
        KnowledgeRepository(session).register_asset(
            id="outside",
            original_name="private.txt",
            path=str(path),
            file_type=".txt",
            size=7,
        )
    documents = Documents()
    importer = service(storage, documents=documents)

    with pytest.raises(ValueError, match="upload|上传"):
        await importer.ingest_document(ingestion_api().DocumentIngestionRequest(asset_id="outside"))

    assert not documents.calls


@pytest.mark.asyncio
async def test_vector_failure_is_durable_and_never_returns_ready(storage):
    importer = service(storage, documents=Documents(RuntimeError("vector unavailable")))

    with pytest.raises(ingestion_api().IngestionFailed) as failure:
        await importer.ingest_document(ingestion_api().DocumentIngestionRequest(text="原文"))

    receipt = failure.value.receipt
    assert receipt.status == "failed"
    with storage.transaction() as session:
        repository = KnowledgeRepository(session)
        job = repository.get_job(receipt.job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error is not None
        assert "vector unavailable" in job.error
        source = repository.get_source("recipes", receipt.source_id, receipt.version)
        assert source is not None
        assert source.status == "failed"
        assert repository.published_versions("recipes") == {}


@pytest.mark.asyncio
async def test_cancelled_import_records_cancellation_and_propagates_it(storage):
    importer = service(storage, documents=Documents(asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await importer.ingest_document(ingestion_api().DocumentIngestionRequest(text="原文"))

    with storage.transaction() as session:
        job = session.scalar(select(IngestionJob))
        assert job.status == "cancelled"
        assert session.scalar(select(KnowledgeSource)).status == "cancelled"


@pytest.mark.asyncio
async def test_cancellation_during_initial_commit_cannot_leave_a_processing_job(
    storage,
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    @contextmanager
    def initial_commit():
        with storage.transaction() as session:
            yield session
            started.set()
            assert release.wait(5)
        finished.set()

    documents = Documents()
    importer = service(storage, documents=documents, transaction=initial_commit)
    task = asyncio.create_task(
        importer.ingest_document(ingestion_api().DocumentIngestionRequest(text="资料"))
    )
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
    finally:
        release.set()
        with suppress(asyncio.CancelledError):
            await task
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(finished.wait, 5)

    with storage.transaction() as session:
        assert session.scalar(select(IngestionJob)).status == "cancelled"
    assert not documents.calls


@pytest.mark.asyncio
async def test_metadata_failure_after_index_write_returns_partial_failure_receipt(
    storage,
):
    transactions = 0

    @contextmanager
    def fail_completion():
        nonlocal transactions
        transactions += 1
        with storage.transaction() as session:
            yield session
            if transactions == 2:
                raise RuntimeError("metadata completion unavailable")

    importer = service(storage, transaction=fail_completion)

    with pytest.raises(ingestion_api().IngestionFailed) as failure:
        await importer.ingest_document(ingestion_api().DocumentIngestionRequest(text="原文"))

    receipt = failure.value.receipt
    assert receipt.status == "failed"
    assert receipt.details["external_write"] == "succeeded"
    with storage.transaction() as session:
        assert session.get(IngestionJob, receipt.job_id).status == "failed"
        assert KnowledgeRepository(session).published_versions("recipes") == {}


@pytest.mark.asyncio
async def test_recipe_import_maps_original_record_directly_and_is_not_document_publication(
    storage,
):
    facts = Facts()
    documents = Documents()
    importer = service(storage, documents=documents, facts=facts)
    original = {"主食材": [["鱼", "1条"]], "耗时": "数天", "备注": {"糖": None}}

    receipt = await importer.ingest_recipe("佛跳墙", original)

    assert receipt.status == "graph_ready"
    assert not documents.calls
    assert json.loads(facts.graphs[0].sources[0].text) == {
        "name": "佛跳墙",
        "record": original,
    }
    with storage.transaction() as session:
        repository = KnowledgeRepository(session)
        source = repository.get_source("recipes", receipt.source_id, receipt.version)
        assert source is not None
        assert source.status == "graph_ready"
        job = repository.get_job(receipt.job_id)
        assert job is not None
        assert job.status == "graph_ready"
        assert repository.published_versions("recipes") == {}


@pytest.mark.asyncio
async def test_formal_recipe_ingestion_uses_service_domain_without_global_reload(
    storage, monkeypatch
):
    from gustobot.infrastructure.knowledge import recipe_facts
    from gustobot.infrastructure.knowledge.semantic_runtime import get_semantic_runtime

    selected = get_domain_definition()
    monkeypatch.setattr(
        recipe_facts,
        "get_domain_definition",
        lambda: pytest.fail("Recipe ingestion must use its service domain"),
    )
    facts = Facts()
    importer = ingestion_api().KnowledgeIngestionService(
        selected, graph_store=facts, session_factory=storage.transaction
    )
    record = {"辅料": [["红糖", "1000", "mg"], ["糖", None], ["盐", 0, "g"]]}

    receipt = await importer.ingest_recipe("糖水", record)

    graph = facts.graphs[0]
    assert receipt.status == "graph_ready"
    assert receipt.ontology_version == selected.version
    runtime = get_semantic_runtime(selected)
    assert runtime is not None
    assert runtime.bind_graph(graph) == graph
    assert json.loads(graph.sources[0].text) == {"name": "糖水", "record": record}
    names = {entity.id: entity.name for entity in graph.entities}
    ingredients = {
        names[edge.target_id]: edge.properties
        for edge in graph.relations
        if edge.type == "HAS_AUX_INGREDIENT"
    }
    assert ingredients["红糖"]["amount_text"] == "1000mg"
    assert ingredients["盐"]["amount_text"] == "0g"
    assert "amount_text" not in ingredients["糖"]


@pytest.mark.asyncio
async def test_formal_recipe_shacl_report_precedes_storage_and_job_registration(
    storage,
):
    from gustobot.infrastructure.knowledge.semantic_runtime import (
        SemanticValidationError,
    )

    facts = Facts()
    importer = service(storage, facts=facts)

    with pytest.raises(SemanticValidationError) as failure:
        await importer.ingest_recipe("糖水", {"辅料": [["糖", "-1g"]]})

    report = failure.value.report.model_dump(mode="json")
    assert report["conforms"] is False
    assert report["ontology_version"] == importer.domain.version
    assert any(issue["path"].endswith("#value") for issue in report["issues"] if issue["path"])
    assert not facts.graphs
    with storage.transaction() as session:
        assert session.scalar(select(IngestionJob)) is None
        assert session.scalar(select(KnowledgeSource)) is None


@pytest.mark.asyncio
async def test_withdrawal_hides_all_document_versions_without_deleting_originals(
    storage,
):
    importer = service(storage)
    request_type = ingestion_api().DocumentIngestionRequest
    await importer.ingest_document(request_type(text="旧资料", source_id="manual"))
    await importer.ingest_document(request_type(text="新资料", source_id="manual"))

    outcome = await importer.withdraw_source("manual")

    assert outcome["status"] == "withdrawn"
    with storage.transaction() as session:
        assert KnowledgeRepository(session).published_versions("recipes") == {}
        sources = session.scalars(select(KnowledgeSource)).all()
        assert {source.text for source in sources} == {"旧资料", "新资料"}
        assert all(source.status == "withdrawn" for source in sources)


@pytest.mark.asyncio
async def test_withdrawal_during_indexing_prevents_late_publication(storage):
    class WaitingDocuments(Documents):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def ingest_source(self, source, *, entity_ids=None):
            self.started.set()
            await self.release.wait()
            return await super().ingest_source(source, entity_ids=entity_ids)

    documents = WaitingDocuments()
    importer = service(storage, documents=documents)
    task = asyncio.create_task(
        importer.ingest_document(
            ingestion_api().DocumentIngestionRequest(text="资料", source_id="manual")
        )
    )
    try:
        await asyncio.wait_for(documents.started.wait(), timeout=5)
        await importer.withdraw_source("manual")
        documents.release.set()
        with pytest.raises(ingestion_api().IngestionFailed):
            await task
    finally:
        documents.release.set()
        with suppress(asyncio.CancelledError, ingestion_api().IngestionFailed):
            await task

    with storage.transaction() as session:
        assert session.scalar(select(KnowledgeSource)).status == "withdrawn"
        assert KnowledgeRepository(session).published_versions("recipes") == {}


@pytest.mark.asyncio
async def test_knowledge_http_uses_explicit_document_and_raw_recipe_requests(storage):
    from gustobot.interfaces.http import knowledge_router

    importer = service(storage)
    app = FastAPI()
    app.include_router(knowledge_router.router)
    app.dependency_overrides[knowledge_router.get_ingestion_service] = lambda: importer
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        document = await client.post("/knowledge/documents", json={"text": "资料"})
        assert document.status_code == 201
        job = await client.get("/knowledge/jobs/" + document.json()["job_id"])
        assert job.json()["status"] == "ready"
        recipe = await client.post(
            "/knowledge/recipes", json={"name": "菜", "record": {"耗时": "未知"}}
        )
        assert recipe.status_code == 201
        assert recipe.json()["status"] == "graph_ready"
        arbitrary = await client.post("/knowledge/documents", json={"file_path": "C:/private.txt"})
        assert arbitrary.status_code == 422


@pytest.mark.asyncio
async def test_upload_registers_asset_and_preserves_frontend_response(storage, monkeypatch):
    from gustobot.interfaces.http.v1 import upload

    monkeypatch.setattr(upload, "UPLOAD_DIR", storage.upload_root)
    monkeypatch.setattr(upload, "session_scope", storage.transaction, raising=False)
    app = FastAPI()
    app.include_router(upload.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/file", files={"file": ("配方.txt", b"raw source", "text/plain")}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == payload["file_id"]
    assert payload["success"] is True
    assert payload["original_name"] == "配方.txt"
    assert Path(payload["file_path"]).is_absolute()
    with storage.transaction() as session:
        asset = session.get(UploadedAsset, payload["asset_id"])
        assert asset.path == payload["file_path"]
        assert Path(asset.path).read_bytes() == b"raw source"
        assert not session.scalars(select(KnowledgeSource)).all()


@pytest.mark.asyncio
async def test_upload_database_failure_removes_only_the_new_file(storage, monkeypatch):
    from gustobot.interfaces.http.v1 import upload

    existing = storage.upload_root / "old.txt"
    existing.write_text("keep", encoding="utf-8")

    @contextmanager
    def unavailable():
        raise RuntimeError("metadata unavailable")
        yield

    monkeypatch.setattr(upload, "UPLOAD_DIR", storage.upload_root)
    monkeypatch.setattr(upload, "session_scope", unavailable, raising=False)
    app = FastAPI()
    app.include_router(upload.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/file", files={"file": ("new.txt", b"new", "text/plain")})

    assert response.status_code == 503
    assert list(storage.upload_root.iterdir()) == [existing]
    assert existing.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("extension", ["xls", "xlsx", "doc"])
@pytest.mark.asyncio
async def test_upload_rejects_formats_without_a_supported_parser(storage, monkeypatch, extension):
    from gustobot.interfaces.http.v1 import upload

    monkeypatch.setattr(upload, "UPLOAD_DIR", storage.upload_root)
    app = FastAPI()
    app.include_router(upload.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/file", files={"file": ("legacy." + extension, b"binary")})

    assert response.status_code == 400
    assert not list(storage.upload_root.iterdir())


def import_cli():
    name = "scripts.import_knowledge"
    assert importlib.util.find_spec(name) is not None, "Explicit import CLI is missing"
    return importlib.import_module(name)


@pytest.mark.asyncio
async def test_recipe_cli_keeps_raw_records_and_applies_limit(storage, tmp_path, capsys):
    cli = import_cli()
    path = tmp_path / "recipes.json"
    original = {
        "【福建】佛跳墙": {"耗时": "数天", "备注": {"未知": None}},
        "佛跳墙": {"耗时": "半小时"},
    }
    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    facts = Facts()

    count = await cli.import_path("recipes", path, service(storage, facts=facts), limit=1)

    assert count == 1
    assert len(facts.graphs) == 1
    assert json.loads(facts.graphs[0].sources[0].text) == {
        "name": "【福建】佛跳墙",
        "record": original["【福建】佛跳墙"],
    }
    assert json.loads(capsys.readouterr().out)["status"] == "graph_ready"


@pytest.mark.parametrize(
    "payload",
    [
        {"佛跳墙": {"耗时": "数天"}, "unselected": "invalid record"},
        [{"name": "佛跳墙", "record": {"耗时": "数天"}}, {"unselected": True}],
    ],
)
@pytest.mark.asyncio
async def test_recipe_cli_does_not_read_entries_beyond_requested_limit(storage, tmp_path, payload):
    cli = import_cli()
    path = tmp_path / "recipes.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    facts = Facts()

    count = await cli.import_path("recipes", path, service(storage, facts=facts), limit=1)

    assert count == 1
    assert len(facts.graphs) == 1


@pytest.mark.asyncio
async def test_document_cli_keeps_file_identity_across_text_revisions(storage, tmp_path, capsys):
    cli = import_cli()
    path = tmp_path / "source.txt"
    importer = service(storage)
    path.write_text("旧资料", encoding="utf-8")
    await cli.import_path("documents", path, importer)
    path.write_text("新资料", encoding="utf-8")
    await cli.import_path("documents", path, importer)

    receipts = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert receipts[0]["source_id"] == receipts[1]["source_id"]
    assert receipts[0]["version"] != receipts[1]["version"]
    with storage.transaction() as session:
        assert {row.text for row in session.scalars(select(KnowledgeSource))} == {
            "旧资料",
            "新资料",
        }


@pytest.mark.asyncio
async def test_cli_failure_returns_nonzero_and_closes_resources(
    storage, tmp_path, monkeypatch, capsys
):
    cli = import_cli()
    path = tmp_path / "source.txt"
    path.write_text("资料", encoding="utf-8")
    importer = service(storage, documents=Documents(RuntimeError("vector unavailable")))
    closed = []

    async def close():
        closed.append(True)

    monkeypatch.setattr(cli, "create_service", lambda: importer)
    monkeypatch.setattr(cli, "close_resources", close)

    exit_code = await cli.execute(SimpleNamespace(command="documents", path=path, source_id=None))

    assert exit_code == 1
    assert closed == [True]
    receipt = json.loads(capsys.readouterr().err)
    assert receipt["status"] == "failed"
    assert receipt["details"]["external_write"] == "attempted"
