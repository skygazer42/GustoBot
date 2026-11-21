"""Source administration reads exact persisted identities and reuses ingestion."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.application.services.knowledge_ingestion import KnowledgeIngestionService
from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.core.database import Base
from gustobot.infrastructure.knowledge.knowledge_service import (
    DocumentIngestionResult,
    KnowledgeService,
    source_version,
)
from gustobot.infrastructure.knowledge.vector_store import DocumentChunk
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository
from gustobot.infrastructure.persistence.db.models.knowledge import (
    IngestionJob,
    KnowledgeSource,
    UploadedAsset,
)


class Documents:
    def __init__(self, failure=None, *, chunk=None):
        self.calls = []
        self.chunk_reads = []
        self.deletions = []
        self.failure = failure
        self.chunk = chunk

    def delete_source(self, source_id, versions):
        self.deletions.append((source_id, tuple(versions)))
        if self.failure is not None:
            raise self.failure

    def read_chunk(self, chunk_id, *, source_id, source_version, ontology_version):
        self.chunk_reads.append((chunk_id, source_id, source_version, ontology_version))
        if self.failure is not None:
            raise self.failure
        return self.chunk

    async def ingest_source(self, source, *, entity_ids=None):
        self.calls.append((source, entity_ids))
        if self.failure is not None:
            raise self.failure
        return DocumentIngestionResult(
            domain_id="recipes",
            source_id=source.id,
            version=source_version(source.text),
            chunks=1,
            embedded=0,
            ids=[],
        )


@pytest.fixture
def storage(request):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    request.addfinalizer(engine.dispose)
    Base.metadata.create_all(engine)

    @contextmanager
    def transaction():
        with Session(engine, expire_on_commit=False) as session, session.begin():
            yield session

    return SimpleNamespace(engine=engine, transaction=transaction)


def add_source(
    storage,
    identifier,
    *,
    text="原文",
    domain="recipes",
    metadata=None,
    status="ready",
    age=0,
    uri=None,
    ontology_version="1",
):
    version = source_version(text)
    timestamp = datetime(2026, 11, 18) + timedelta(seconds=age)
    with storage.transaction() as session:
        source = KnowledgeRepository(session).put_source(
            domain_id=domain,
            source_id=identifier,
            version=version,
            uri=identifier if uri is None else uri,
            text=text,
            ontology_version=ontology_version,
            status=status,
            metadata=metadata,
        )
        source.created_at = source.updated_at = timestamp
    return version


def add_job(storage, identifier, version, *, number=0, status="ready", details=None, error=None):
    timestamp = datetime(2026, 11, 18) + timedelta(minutes=number)
    with storage.transaction() as session:
        job = KnowledgeRepository(session).create_job(
            id=f"{identifier}-job-{number}",
            domain_id="recipes",
            source_id=identifier,
            source_version=version,
            status=status,
            details={} if details is None else details,
        )
        job.error = error
        job.created_at = job.updated_at = timestamp


def application(storage, *, documents=None, transaction=None):
    app = FastAPI()
    from gustobot.application.services.knowledge_admin import KnowledgeAdminService
    from gustobot.interfaces.http import knowledge_admin_router

    sessions = storage.transaction if transaction is None else transaction
    document_service = cast(KnowledgeService, Documents() if documents is None else documents)
    importer = KnowledgeIngestionService(
        get_domain_definition(),
        documents=document_service,
        session_factory=sessions,
    )
    admin = KnowledgeAdminService(
        get_domain_definition(),
        ingestion=importer,
        documents=lambda: document_service,
        session_factory=sessions,
    )
    app.include_router(knowledge_admin_router.router)
    app.dependency_overrides[knowledge_admin_router.get_admin_service] = lambda: admin
    return app


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def editor_snapshot(http, source_id, version):
    response = await http.get(
        "/knowledge/admin/document", params={"source_id": source_id, "version": version}
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_document_editor_reads_complete_text_without_using_the_preview_limit(storage):
    text = "完整原文\n" * 6000
    version = add_source(
        storage,
        "guide",
        text=text,
        metadata={"kind": "document", "metadata": {"title": "知识文章"}},
    )
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        preview = (await http.get("/knowledge/admin/source", params={"source_id": "guide"})).json()
        response = await http.get(
            "/knowledge/admin/document", params={"source_id": "guide", "version": version}
        )
    assert preview["text_truncated"] is True
    assert response.status_code == 200
    result = response.json()
    revision = result.pop("revision")
    assert len(revision) == 64 and int(revision, 16) >= 0
    assert result == {
        "source_id": "guide",
        "version": version,
        "title": "知识文章",
        "text": text,
    }
    assert documents.calls == documents.chunk_reads == []


@pytest.mark.asyncio
async def test_document_editor_rejects_oversized_text_instead_of_returning_a_partial_body(storage):
    version = add_source(storage, "large", text="文" * 1_000_001, metadata={"kind": "document"})
    async with client(application(storage)) as http:
        response = await http.get(
            "/knowledge/admin/document", params={"source_id": "large", "version": version}
        )
    assert response.status_code == 413 and "1000000" in response.json()["detail"]


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.asyncio
async def test_document_editor_is_domain_scoped_and_rejects_non_document_sources(storage, method):
    foreign = add_source(storage, "foreign", domain="equipment", metadata={"kind": "document"})
    recipe = add_source(storage, "recipe", metadata={"kind": "recipe"}, status="graph_ready")
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        for identifier, version, status in (("foreign", foreign, 404), ("recipe", recipe, 409)):
            identity = {"source_id": identifier, "version": version}
            response = (
                await http.get("/knowledge/admin/document", params=identity)
                if method == "get"
                else await http.put(
                    "/knowledge/admin/document",
                    json=identity | {"revision": "a" * 64, "title": "修订", "text": "新原文"},
                )
            )
            assert response.status_code == status
    assert documents.calls == []


@pytest.mark.asyncio
async def test_document_edit_creates_a_new_version_and_preserves_provenance_and_entity_links(
    storage,
):
    original_metadata = {
        "kind": "document",
        "asset_id": "upload-1",
        "original_name": "article.md",
        "metadata": {"title": "旧标题", "license": "CC-BY-SA-4.0", "attribution": "Actual authors"},
        "entity_ids": ["dish-1"],
    }
    previous = add_source(
        storage,
        "guide",
        text="旧文章内容",
        uri="https://example.org/articles/revision/1",
        metadata=original_metadata,
    )
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        snapshot = await editor_snapshot(http, "guide", previous)
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": previous,
                "revision": snapshot["revision"],
                "title": "修订标题",
                "text": "修订后的完整文章",
            },
        )
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["status"] == "ready" and receipt["source_id"] == "guide"
        assert receipt["version"] == source_version("修订后的完整文章") != previous
        readback = await http.get(
            "/knowledge/admin/document",
            params={
                "source_id": "guide",
                "version": receipt["version"],
            },
        )
    assert readback.json()["text"] == "修订后的完整文章"
    assert readback.json()["title"] == "修订标题"
    assert readback.json()["revision"] != snapshot["revision"]
    assert len(documents.calls) == 1
    assert documents.calls[0][0].uri == "https://example.org/articles/revision/1"
    assert documents.calls[0][1] == ["dish-1"]
    with storage.transaction() as session:
        original = session.get(KnowledgeSource, ("recipes", "guide", previous))
        current = session.get(KnowledgeSource, ("recipes", "guide", receipt["version"]))
        assert original is not None and current is not None
        assert original.text == "旧文章内容" and original.source_metadata == original_metadata
        metadata = current.source_metadata
        assert metadata["metadata"]["license"] == "CC-BY-SA-4.0"
        assert metadata["metadata"]["attribution"] == "Actual authors"
        assert metadata["metadata"]["local_revision"]["previous_version"] == previous
        assert metadata["metadata"]["local_revision"]["content_version"] == receipt["version"]
        assert metadata["metadata"]["local_revision"]["graph_review_required"] is True
        assert metadata["asset_id"] == "upload-1" and metadata["entity_ids"] == ["dish-1"]
        assert KnowledgeRepository(session).published_versions("recipes") == {
            "guide": receipt["version"]
        }


@pytest.mark.asyncio
async def test_rename_current_document_reuses_its_ready_chunk_receipt_without_vector_writes(
    storage,
):
    domain = get_domain_definition()
    version = add_source(
        storage,
        "guide",
        metadata={"kind": "document", "metadata": {"title": "原名"}},
        ontology_version=domain.version,
    )
    manifest = {
        "domain_id": domain.id,
        "source_id": "guide",
        "version": version,
        "chunks": 2,
        "embedded": 2,
        "ids": ["chunk-a", "chunk-b"],
    }
    add_job(
        storage,
        "guide",
        version,
        details={"document": manifest, "ontology_version": domain.version},
    )
    documents = Documents(RuntimeError("renaming must not use the vector provider"))
    async with client(application(storage, documents=documents)) as http:
        snapshot = await editor_snapshot(http, "guide", version)
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": version,
                "revision": snapshot["revision"],
                "title": "新名称",
                "text": "原文",
            },
        )
        assert response.status_code == 200
        receipt = response.json()
        assert receipt["status"] == "ready" and receipt["version"] == version
        assert receipt["job_id"] != "guide-job-0" and receipt["details"]["document"] == {
            "chunks": 2,
            "embedded": 0,
        }
        detail = (await http.get("/knowledge/admin/source", params={"source_id": "guide"})).json()
    assert documents.calls == []
    assert detail["source"]["title"] == "新名称" and detail["source"]["chunks"] == 2
    with storage.transaction() as session:
        job = session.get(IngestionJob, receipt["job_id"])
        assert job.details["document"]["ids"] == ["chunk-a", "chunk-b"]


@pytest.mark.parametrize("invalid_receipt", [None, "wrong_version", "wrong_count"])
@pytest.mark.asyncio
async def test_document_rename_rejects_missing_or_mismatched_chunk_receipts(
    storage, invalid_receipt
):
    domain = get_domain_definition()
    version = add_source(
        storage,
        "guide",
        metadata={"kind": "document", "metadata": {"title": "旧标题"}},
        ontology_version=domain.version,
    )
    if invalid_receipt is not None:
        manifest = {
            "domain_id": domain.id,
            "source_id": "guide",
            "version": "wrong" if invalid_receipt == "wrong_version" else version,
            "chunks": 2 if invalid_receipt == "wrong_count" else 1,
            "embedded": 0,
            "ids": ["chunk-1"],
        }
        add_job(
            storage,
            "guide",
            version,
            details={"document": manifest, "ontology_version": domain.version},
        )
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        snapshot = await editor_snapshot(http, "guide", version)
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": version,
                "revision": snapshot["revision"],
                "title": "新标题",
                "text": "原文",
            },
        )
    assert response.status_code == 409 and "切片" in response.json()["detail"]
    assert documents.calls == []
    with storage.transaction() as session:
        source = session.get(KnowledgeSource, (domain.id, "guide", version))
        assert source.source_metadata["metadata"]["title"] == "旧标题"


@pytest.mark.parametrize(
    "stale_change", [{"title": "第二个编辑器更名"}, {"text": "第二个编辑器修改正文"}]
)
@pytest.mark.asyncio
async def test_document_snapshot_blocks_stale_editors_after_rename_and_accepts_a_fresh_snapshot(
    storage, stale_change
):
    domain = get_domain_definition()
    version = add_source(
        storage,
        "guide",
        metadata={"kind": "document", "metadata": {"title": "原名"}},
        ontology_version=domain.version,
    )
    add_job(
        storage,
        "guide",
        version,
        details={
            "ontology_version": domain.version,
            "document": {
                "domain_id": domain.id,
                "source_id": "guide",
                "version": version,
                "chunks": 1,
                "embedded": 1,
                "ids": ["chunk-1"],
            },
        },
    )
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        identity = {"source_id": "guide", "version": version}
        first = (await http.get("/knowledge/admin/document", params=identity)).json()
        second = (await http.get("/knowledge/admin/document", params=identity)).json()
        renamed = await http.put(
            "/knowledge/admin/document", json=first | {"title": "第一个编辑器已更名"}
        )
        assert renamed.status_code == 200
        stale = await http.put("/knowledge/admin/document", json=second | stale_change)
        assert stale.status_code == 409
        current = (await http.get("/knowledge/admin/document", params=identity)).json()
        assert current["title"] == "第一个编辑器已更名" and current["text"] == "原文"
        assert current["version"] == version and current["revision"] != first["revision"]
        fresh = await http.put(
            "/knowledge/admin/document", json=current | {"title": "新快照再次更名"}
        )
        assert fresh.status_code == 200
    assert documents.calls == []


@pytest.mark.parametrize("change", ["stale", "active_job", "active_source", "historical_body"])
@pytest.mark.asyncio
async def test_document_edit_rejects_conflicts_before_registering_or_writing_vectors(
    storage, change
):
    older = add_source(storage, "guide", text="旧正文", metadata={"kind": "document"})
    current = add_source(storage, "guide", text="当前正文", age=1, metadata={"kind": "document"})
    if change == "active_job":
        add_job(storage, "guide", older, status="processing")
    elif change == "active_source":
        with storage.transaction() as session:
            session.get(KnowledgeSource, ("recipes", "guide", older)).status = "processing"
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        selected_version = older if change == "stale" else current
        snapshot = await editor_snapshot(http, "guide", selected_version)
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": selected_version,
                "revision": snapshot["revision"],
                "title": "修订",
                "text": "旧正文" if change == "historical_body" else "待保存正文",
            },
        )
    assert response.status_code == 409 and documents.calls == []
    if change == "historical_body":
        assert "历史" in response.json()["detail"]
    with storage.transaction() as session:
        assert (
            session.scalar(select(KnowledgeSource).where(KnowledgeSource.text == "待保存正文"))
            is None
        )
        assert session.scalar(select(IngestionJob).where(IngestionJob.id != "guide-job-0")) is None


@pytest.mark.parametrize("change", ["new_version", "deleted", "active_job", "renamed"])
@pytest.mark.asyncio
async def test_document_edit_checks_expected_version_in_the_registration_transaction(
    storage, monkeypatch, change
):
    from gustobot.interfaces.http import knowledge_admin_router

    previous = add_source(storage, "guide", metadata={"kind": "document"})
    documents = Documents()
    app = application(storage, documents=documents)
    importer = app.dependency_overrides[knowledge_admin_router.get_admin_service]().ingestion
    register = importer._start

    def changed_before_register(*args, **kwargs):
        if change == "new_version":
            add_source(
                storage, "guide", text="别人已保存的正文", age=1, metadata={"kind": "document"}
            )
        elif change == "deleted":
            with storage.transaction() as session:
                session.delete(session.get(KnowledgeSource, ("recipes", "guide", previous)))
        elif change == "renamed":
            with storage.transaction() as session:
                source = session.get(KnowledgeSource, ("recipes", "guide", previous))
                session.execute(
                    update(KnowledgeSource)
                    .where(
                        KnowledgeSource.domain_id == "recipes",
                        KnowledgeSource.source_id == "guide",
                        KnowledgeSource.version == previous,
                    )
                    .values(
                        source_metadata={
                            "kind": "document",
                            "metadata": {"title": "其他编辑器新名"},
                        },
                        updated_at=source.updated_at,
                    )
                )
        else:
            add_job(storage, "guide", previous, status="processing")
        return register(*args, **kwargs)

    monkeypatch.setattr(importer, "_start", changed_before_register)
    async with client(app) as http:
        snapshot = await editor_snapshot(http, "guide", previous)
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": previous,
                "revision": snapshot["revision"],
                "title": "修订",
                "text": "待保存正文",
            },
        )
    assert response.status_code == (404 if change == "deleted" else 409)
    assert documents.calls == []
    with storage.transaction() as session:
        assert (
            session.scalar(select(KnowledgeSource).where(KnowledgeSource.text == "待保存正文"))
            is None
        )
        if change == "renamed":
            source = session.get(KnowledgeSource, ("recipes", "guide", previous))
            assert source.source_metadata["metadata"]["title"] == "其他编辑器新名"
            assert source.updated_at == datetime(2026, 11, 18)


@pytest.mark.asyncio
async def test_failed_document_edit_keeps_previous_ready_content_and_safe_error_receipt(storage):
    previous = add_source(storage, "guide", text="旧正文", metadata={"kind": "document"})
    documents = Documents(RuntimeError("secret-provider-token"))
    async with client(application(storage, documents=documents)) as http:
        snapshot = await editor_snapshot(http, "guide", previous)
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": previous,
                "revision": snapshot["revision"],
                "title": "新标题",
                "text": "失败的新正文",
            },
        )
    assert response.status_code == 503 and "secret-provider-token" not in response.text
    assert response.json()["detail"]["receipt"]["status"] == "failed"
    with storage.transaction() as session:
        assert KnowledgeRepository(session).published_versions("recipes") == {"guide": previous}
        assert session.get(KnowledgeSource, ("recipes", "guide", previous)).text == "旧正文"
        assert (
            session.get(
                KnowledgeSource, ("recipes", "guide", source_version("失败的新正文"))
            ).status
            == "failed"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"title": " "},
        {"title": "文" * 513},
        {"text": "\n\t "},
        {"text": "文" * 1_000_001},
        {"metadata": {}},
        {"version": " "},
        {"source_id": " "},
        {"revision": None},
        {"revision": "A" * 64},
        {"revision": "invalid"},
    ],
)
@pytest.mark.asyncio
async def test_document_edit_rejects_invalid_inputs_without_touching_storage(storage, changes):
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": "a" * 64,
                "revision": "b" * 64,
                "title": "文章",
                "text": "原文",
            }
            | changes,
        )
    assert response.status_code == 422 and documents.calls == []


@pytest.mark.asyncio
async def test_document_edit_requires_a_snapshot_revision(storage):
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        response = await http.put(
            "/knowledge/admin/document",
            json={
                "source_id": "guide",
                "version": "a" * 64,
                "title": "文章",
                "text": "原文",
            },
        )
    assert response.status_code == 422 and documents.calls == []


@pytest.mark.asyncio
async def test_cancelled_document_edit_retains_previous_publication_and_records_cancelled_job(
    storage,
):
    from gustobot.interfaces.http import knowledge_admin_router

    class WaitingDocuments(Documents):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()

        async def ingest_source(self, source, *, entity_ids=None):
            self.entered.set()
            await asyncio.Event().wait()

    previous = add_source(storage, "guide", text="旧正文", metadata={"kind": "document"})
    documents = WaitingDocuments()
    app = application(storage, documents=documents)
    admin = app.dependency_overrides[knowledge_admin_router.get_admin_service]()
    revision = admin.read_document("guide", previous).revision
    task = asyncio.create_task(
        admin.update_document("guide", previous, revision=revision, title="新名", text="待入库正文")
    )
    try:
        await asyncio.wait_for(documents.entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with storage.transaction() as session:
            assert KnowledgeRepository(session).published_versions("recipes") == {"guide": previous}
            current = session.get(
                KnowledgeSource, ("recipes", "guide", source_version("待入库正文"))
            )
            assert current is not None and current.status == "cancelled"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_list_uses_latest_created_version_and_stats_ignore_only_state(storage):
    old = add_source(storage, "manual", text="旧版", metadata={"kind": "document"}, age=0)
    latest = add_source(
        storage,
        "manual",
        text="新版",
        status="failed",
        age=1,
        metadata={"kind": "document", "metadata": {"title": "资料 B"}},
    )
    with storage.transaction() as session:
        session.get(KnowledgeSource, ("recipes", "manual", old)).updated_at = datetime(2027, 1, 1)
    add_source(storage, "ready", metadata={"kind": "document", "original_name": "资料 A.txt"})
    add_source(
        storage,
        "removed",
        status="withdrawn",
        metadata={"kind": "document", "metadata": {"title": "资料 C"}},
    )
    add_source(
        storage,
        "dish",
        text='{"name":"资料 菜谱","record":{}}',
        status="graph_ready",
        metadata={"kind": "recipe"},
    )
    add_source(storage, "legacy", metadata=None)
    add_source(storage, "foreign", domain="equipment", metadata={"kind": "document"})
    async with client(application(storage)) as http:
        response = await http.get(
            "/knowledge/admin/sources",
            params={
                "q": "资料",
                "kind": "document",
                "state": "pending",
                "limit": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["domain"]["id"] == "recipes"
        assert data["total"] == 1
        assert data["stats"] == {
            "total": 3,
            "ready": 1,
            "pending": 1,
            "withdrawn": 1,
            "processing": 0,
            "failed": 1,
        }
        assert data["items"][0]["version"] == latest
        assert data["items"][0]["title"] == "资料 B"
        all_data = (await http.get("/knowledge/admin/sources")).json()
        assert all_data["total"] == 5
        legacy = next(item for item in all_data["items"] if item["source_id"] == "legacy")
        assert legacy["kind"] == "unknown"
        assert (
            legacy["chunks"],
            legacy["entities"],
            legacy["relations"],
            legacy["latest_job"],
        ) == (
            None,
            None,
            None,
            None,
        )
        recipe = (
            await http.get("/knowledge/admin/sources", params={"q": "菜谱", "kind": "recipe"})
        ).json()
        assert recipe["items"][0]["title"] == "资料 菜谱"
        assert recipe["stats"] == {
            "total": 1,
            "ready": 1,
            "pending": 0,
            "withdrawn": 0,
            "processing": 0,
            "failed": 0,
        }


@pytest.mark.asyncio
async def test_processing_and_failed_filters_use_source_status_and_keep_legacy_pending(storage):
    for status in ("pending", "processing", "failed", "cancelled", "ready", "withdrawn"):
        add_source(storage, status, status=status, metadata={"kind": "document"})
    add_source(storage, "other", domain="equipment", status="processing")
    async with client(application(storage)) as http:
        for state in ("processing", "failed"):
            page = await http.get("/knowledge/admin/sources", params={"state": state, "limit": 1})
            assert page.status_code == 200
            assert page.json()["total"] == 1
            assert [item["source_id"] for item in page.json()["items"]] == [state]
            assert page.json()["stats"] == {
                "total": 6,
                "ready": 1,
                "pending": 4,
                "withdrawn": 1,
                "processing": 1,
                "failed": 1,
            }
        pending = await http.get("/knowledge/admin/sources", params={"state": "pending"})
        assert pending.status_code == 200 and pending.json()["total"] == 4
        assert {item["source_id"] for item in pending.json()["items"]} == {
            "pending",
            "processing",
            "failed",
            "cancelled",
        }


@pytest.mark.asyncio
async def test_pages_are_stable_and_latest_job_counts_keep_zero_without_n_plus_one(storage):
    for number in range(6):
        identifier = f"manual-{number}"
        version = add_source(storage, identifier, metadata={"kind": "document"})
        add_job(storage, identifier, version, details={"document": {"chunks": 9}})
        add_job(
            storage,
            identifier,
            version,
            number=1,
            details={
                "document": {"chunks": 0},
                "graph": {"entities": 0, "relations": 0},
            },
        )
    queries = []
    projected_columns = []

    def record_query(_connection, cursor, statement, _parameters, _context, _many):
        queries.append(statement)
        projected_columns.append([column[0] for column in cursor.description])

    event.listen(storage.engine, "after_cursor_execute", record_query)
    async with client(application(storage)) as http:
        pages = []
        for offset in (0, 2, 4):
            response = await http.get(
                "/knowledge/admin/sources", params={"offset": offset, "limit": 2}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 6
            assert (data["offset"], data["limit"]) == (offset, 2)
            pages.extend(data["items"])
    event.remove(storage.engine, "after_cursor_execute", record_query)
    assert [item["source_id"] for item in pages] == [f"manual-{number}" for number in range(6)]
    assert all((item["chunks"], item["entities"], item["relations"]) == (0, 0, 0) for item in pages)
    assert len(queries) <= 9
    assert all("text" not in columns for columns in projected_columns)


@pytest.mark.asyncio
async def test_failed_latest_job_does_not_change_source_status_or_reuse_old_counts(storage):
    version = add_source(
        storage,
        "manual",
        metadata={
            "kind": "document",
            "metadata": {"title": "100% 指南"},
            "graph_counts": {"entities": 0, "relations": 1},
        },
        uri="E:\\private-uploads\\manual.txt",
    )
    add_source(storage, "another", metadata={"kind": "document", "metadata": {"title": "100 指南"}})
    add_job(storage, "manual", version, details={"document": {"chunks": 5}})
    add_job(storage, "manual", version, number=1, status="failed", error="provider-secret")
    async with client(application(storage)) as http:
        response = await http.get("/knowledge/admin/sources", params={"q": "%", "state": "ready"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["status"] == "ready" and item["latest_job"]["status"] == "failed"
        assert item["chunks"] is None
        assert (item["entities"], item["relations"]) == (0, 1)
        assert item["uri"] == "manual.txt" and "provider-secret" not in response.text
        empty = (await http.get("/knowledge/admin/sources", params={"q": "没有此资料"})).json()
        assert empty["items"] == [] and empty["total"] == 0
        assert empty["stats"] == {
            "total": 0,
            "ready": 0,
            "pending": 0,
            "withdrawn": 0,
            "processing": 0,
            "failed": 0,
        }


@pytest.mark.asyncio
async def test_detail_is_exact_scoped_truncated_and_returns_only_ten_version_jobs(storage):
    version = add_source(
        storage,
        "manual",
        text="原" * 20001,
        metadata={"kind": "document", "graph_counts": {"entities": 0, "relations": 2}},
    )
    older = add_source(storage, "manual", text="旧原文", age=-1, metadata={"kind": "document"})
    add_source(storage, "foreign", domain="equipment", text="别的领域")
    for number in range(12):
        add_job(
            storage,
            "manual",
            version,
            number=number,
            details={
                "context": {
                    "metadata": {"api_key": "do-not-send"},
                    "path": "E:\\uploads\\private.txt",
                }
            },
        )
    add_job(storage, "manual", older, number=99)
    async with client(application(storage)) as http:
        response = await http.get("/knowledge/admin/source", params={"source_id": "manual"})
        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "原" * 20000 and data["text_truncated"] is True
        assert (data["source"]["entities"], data["source"]["relations"]) == (0, 2)
        assert len(data["jobs"]) == 10
        assert [job["id"] for job in data["jobs"]] == [
            f"manual-job-{number}" for number in range(11, 1, -1)
        ]
        assert "do-not-send" not in response.text and "uploads" not in response.text
        exact = await http.get(
            "/knowledge/admin/source", params={"source_id": "manual", "version": older}
        )
        assert exact.json()["text"] == "旧原文" and exact.json()["text_truncated"] is False
        for params in ({"source_id": "foreign"}, {"source_id": "manual", "version": "missing"}):
            assert (await http.get("/knowledge/admin/source", params=params)).status_code == 404


@pytest.mark.parametrize("source_status", ["ready", "withdrawn"])
@pytest.mark.asyncio
async def test_chunk_reads_ordered_manifest_for_exact_version_despite_failed_retry(
    storage, source_status
):
    source_id = " 指南 "
    version = add_source(
        storage,
        source_id,
        ontology_version="uploaded-v1",
        status=source_status,
        metadata={"kind": "document"},
    )
    newer_version = add_source(
        storage, source_id, text="新版", metadata={"kind": "document"}, age=1
    )
    manifest = {
        "domain_id": "recipes",
        "source_id": source_id,
        "version": version,
        "chunks": 2,
        "embedded": 2,
        "ids": ["z" * 64, "b" * 64],
    }
    add_job(
        storage,
        source_id,
        version,
        details={"ontology_version": "uploaded-v1", "document": manifest},
    )
    add_job(
        storage,
        source_id,
        version,
        number=1,
        status="failed",
        details={"ontology_version": "uploaded-v1"},
    )
    add_job(
        storage,
        source_id,
        version,
        number=2,
        details={"ontology_version": "other-ontology", "document": manifest | {"ids": ["x", "y"]}},
    )
    add_job(
        storage,
        source_id,
        newer_version,
        number=3,
        details={
            "ontology_version": "uploaded-v1",
            "document": manifest | {"version": newer_version},
        },
    )
    documents = Documents(
        chunk=DocumentChunk(
            id="b" * 64,
            domain_id="recipes",
            source_id=source_id,
            source_version=version,
            ontology_version="uploaded-v1",
            embedding_model="test-embedding",
            chunk_index=1,
            content="原文在切片库中的段落",
            uri="E:\\private\\file.txt",
        )
    )
    async with client(application(storage, documents=documents)) as http:
        params = {"source_id": source_id, "version": version}
        response = await http.get("/knowledge/admin/chunk", params=params | {"number": 2})
        assert response.status_code == 200
        assert response.json() == {"number": 2, "total": 2, "content": "原文在切片库中的段落"}
        assert (
            await http.get("/knowledge/admin/chunk", params=params | {"number": 3})
        ).status_code == 404
    assert documents.chunk_reads == [("b" * 64, source_id, version, "uploaded-v1")]
    assert documents.calls == []


@pytest.mark.asyncio
async def test_chunk_query_reports_missing_source_and_legacy_manifest_without_vector_lookup(
    storage,
):
    version = add_source(storage, "foreign", domain="equipment", metadata={"kind": "document"})
    add_source(storage, "recipe", metadata={"kind": "recipe"}, status="graph_ready")
    add_source(storage, "old-doc", metadata={"kind": "document"})
    add_job(
        storage, "old-doc", version, details={"ontology_version": "1", "document": {"chunks": 1}}
    )
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        for source_id, expected in (("foreign", 404), ("recipe", 409), ("old-doc", 409)):
            response = await http.get(
                "/knowledge/admin/chunk", params={"source_id": source_id, "version": version}
            )
            assert response.status_code == expected
            if expected == 409:
                assert "请" in response.json()["detail"]
        for invalid in ({"number": 0}, {"version": " "}, {"source_id": "a" * 256}, {"extra": "x"}):
            response = await http.get(
                "/knowledge/admin/chunk",
                params={"source_id": "old-doc", "version": version} | invalid,
            )
            assert response.status_code == 422
        missing = await http.get("/knowledge/admin/chunk", params={"source_id": "old-doc"})
        assert missing.status_code == 422
    assert documents.chunk_reads == []


@pytest.mark.parametrize(
    "failure,recorded_count", [(None, 1), (RuntimeError("secret"), 1), (None, 2)]
)
@pytest.mark.asyncio
async def test_chunk_query_reports_missing_row_provider_failure_and_inconsistent_count(
    storage, failure, recorded_count
):
    version = add_source(storage, "doc", metadata={"kind": "document"})
    add_job(
        storage,
        "doc",
        version,
        details={
            "ontology_version": "1",
            "document": {
                "domain_id": "recipes",
                "source_id": "doc",
                "version": version,
                "chunks": recorded_count,
                "embedded": 1,
                "ids": ["a" * 64],
            },
        },
    )
    documents = Documents(failure)
    async with client(application(storage, documents=documents)) as http:
        response = await http.get(
            "/knowledge/admin/chunk", params={"source_id": "doc", "version": version}
        )
        assert response.status_code == 503
        assert "secret" not in response.text
    assert len(documents.chunk_reads) == (1 if recorded_count == 1 else 0)


@pytest.mark.parametrize("status", ["failed", "withdrawn"])
@pytest.mark.asyncio
async def test_retry_preserves_full_text_uri_metadata_entity_ids_and_restores_withdrawn(
    storage, status
):
    text = "原文" * 12000
    metadata = {
        "kind": "document",
        "asset_id": "asset-1",
        "original_name": "原资料.txt",
        "metadata": {"nested": {"verified": False}, "count": 0},
        "entity_ids": ["dish-1"],
        "graph_counts": {"entities": 2, "relations": 0},
    }
    version = add_source(
        storage,
        "asset:asset-1",
        text=text,
        metadata=metadata,
        status=status,
        uri="asset:asset-1/原资料.txt",
    )
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        response = await http.post(
            "/knowledge/admin/retry", json={"source_id": "asset:asset-1", "version": version}
        )
    assert response.status_code == 201
    source, entity_ids = documents.calls[0]
    assert source.text == text and source.uri == "asset:asset-1/原资料.txt"
    assert entity_ids == ["dish-1"]
    with storage.transaction() as session:
        stored = session.get(KnowledgeSource, ("recipes", "asset:asset-1", version))
        assert stored.source_metadata == metadata
        assert stored.status == "ready"
        assert list(session.scalars(select(KnowledgeSource.version))) == [version]


@pytest.mark.asyncio
async def test_admin_preserves_nonblank_source_identity_whitespace(storage):
    add_source(storage, "manual", text="另一个来源", metadata={"kind": "document"})
    version = add_source(storage, " manual ", text="精确来源", metadata={"kind": "document"})
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        detail = await http.get("/knowledge/admin/source", params={"source_id": " manual "})
        assert detail.status_code == 200
        assert detail.json()["source"]["source_id"] == " manual "
        assert detail.json()["text"] == "精确来源"
        retry = await http.post(
            "/knowledge/admin/retry", json={"source_id": " manual ", "version": version}
        )
        assert retry.status_code == 201
        assert documents.calls[0][0].id == " manual "


@pytest.mark.asyncio
async def test_retry_failure_keeps_durable_receipt_and_non_documents_are_conflicts(storage):
    version = add_source(storage, "manual", metadata={"kind": "document"}, status="failed")
    recipe = add_source(storage, "dish", metadata={"kind": "recipe"}, status="graph_ready")
    unknown = add_source(storage, "legacy")
    foreign = add_source(storage, "foreign", domain="equipment", metadata={"kind": "document"})
    corrupt = add_source(storage, "corrupt", metadata={"kind": "document"})
    with storage.transaction() as session:
        session.get(KnowledgeSource, ("recipes", "corrupt", corrupt)).version = "incorrect-version"
    async with client(
        application(storage, documents=Documents(RuntimeError("secret-provider-token")))
    ) as http:
        failed = await http.post(
            "/knowledge/admin/retry", json={"source_id": "manual", "version": version}
        )
        assert failed.status_code == 503
        receipt = failed.json()["detail"]["receipt"]
        assert receipt["status"] == "failed" and receipt["source_id"] == "manual"
        assert receipt["details"]["external_write"] == "attempted"
        assert "secret-provider-token" not in failed.text
        for identifier, content_version, expected in (
            ("dish", recipe, 409),
            ("legacy", unknown, 409),
            ("foreign", foreign, 404),
            ("manual", "missing", 404),
            ("corrupt", "incorrect-version", 409),
        ):
            response = await http.post(
                "/knowledge/admin/retry", json={"source_id": identifier, "version": content_version}
            )
            assert response.status_code == expected
    with storage.transaction() as session:
        job = session.get(IngestionJob, receipt["job_id"])
        assert job.status == "failed" and job.error == "secret-provider-token"


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"kind": "unknown"},
        {"state": "cancelled"},
        {"domain_id": "equipment"},
    ],
)
@pytest.mark.asyncio
async def test_query_boundaries_are_http_422(storage, query):
    async with client(application(storage)) as http:
        assert (await http.get("/knowledge/admin/sources", params=query)).status_code == 422


@pytest.mark.asyncio
async def test_bad_identity_and_backend_failure_are_distinct_http_errors(storage):
    async with client(application(storage)) as http:
        assert (
            await http.get("/knowledge/admin/source", params={"source_id": " "})
        ).status_code == 422
        assert (
            await http.post("/knowledge/admin/retry", json={"source_id": "manual"})
        ).status_code == 422

    @contextmanager
    def unavailable():
        raise OperationalError("SELECT secret", {}, RuntimeError("password"))
        yield

    async with client(application(storage, transaction=unavailable)) as http:
        response = await http.get("/knowledge/admin/sources")
        assert response.status_code == 503
        assert "password" not in response.text and "secret" not in response.text
        assert (
            await http.get("/knowledge/admin/source", params={"source_id": "manual"})
        ).status_code == 503
        chunk = await http.get(
            "/knowledge/admin/chunk", params={"source_id": "manual", "version": "v1"}
        )
        assert chunk.status_code == 503
        assert "password" not in chunk.text and "secret" not in chunk.text
        assert (
            await http.post("/knowledge/admin/retry", json={"source_id": "manual", "version": "v1"})
        ).status_code == 503


@pytest.mark.asyncio
async def test_delete_removes_all_document_versions_and_jobs_but_keeps_other_sources_and_asset(
    storage, tmp_path
):
    with storage.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    identifier = " asset:guide/a "
    original = tmp_path / "guide.txt"
    original.write_text("独立上传原件", encoding="utf-8")
    with storage.transaction() as session:
        KnowledgeRepository(session).register_asset(
            id="guide",
            original_name="guide.txt",
            path=str(original),
            file_type="text/plain",
            size=18,
        )
    for number, status in enumerate(("ready", "withdrawn", "failed")):
        version = add_source(
            storage,
            identifier,
            text=f"版本{number}",
            status=status,
            metadata={"kind": "document", "asset_id": "guide"},
            age=number,
        )
        add_job(storage, identifier, version, number=number, status=status)
    foreign = add_source(storage, identifier, domain="equipment", metadata={"kind": "document"})
    other = add_source(storage, "other", metadata={"kind": "document"})
    add_job(storage, "other", other)
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        params = {"source_id": identifier, "version": version}
        response = await http.delete("/knowledge/admin/source", params=params)
        assert response.status_code == 200
        assert response.json() == {"source_id": identifier, "versions": 3}
        assert (
            await http.get("/knowledge/admin/source", params={"source_id": identifier})
        ).status_code == 404
        assert (await http.get("/knowledge/admin/sources")).json()["total"] == 1
        assert (await http.delete("/knowledge/admin/source", params=params)).status_code == 404
    assert len(documents.deletions) == 1 and documents.deletions[0][0] == identifier
    assert set(documents.deletions[0][1]) == {
        source_version(f"版本{number}") for number in range(3)
    }
    with storage.transaction() as session:
        assert session.get(KnowledgeSource, ("equipment", identifier, foreign)) is not None
        assert session.get(KnowledgeSource, ("recipes", "other", other)) is not None
        assert list(session.scalars(select(IngestionJob.id))) == ["other-job-0"]
        assert session.get(UploadedAsset, "guide") is not None
    assert original.read_text(encoding="utf-8") == "独立上传原件"


@pytest.mark.parametrize("kind", ["recipe", None])
@pytest.mark.asyncio
async def test_delete_rejects_non_document_versions_before_changing_anything(storage, kind):
    add_source(storage, "mixed", text="document", metadata={"kind": "document"})
    version = add_source(
        storage, "mixed", text="other", age=1, metadata=None if kind is None else {"kind": kind}
    )
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        response = await http.delete(
            "/knowledge/admin/source", params={"source_id": "mixed", "version": version}
        )
    assert response.status_code == 409
    assert documents.deletions == []
    with storage.transaction() as session:
        assert list(session.scalars(select(KnowledgeSource.status))) == ["ready", "ready"]


@pytest.mark.parametrize(
    "source_status,job_status",
    [("pending", None), ("processing", None), ("ready", "pending"), ("withdrawn", "processing")],
)
@pytest.mark.asyncio
async def test_delete_rejects_active_ingestion_in_any_version(storage, source_status, job_status):
    version = add_source(storage, "busy", status=source_status, metadata={"kind": "document"})
    if job_status is not None:
        add_job(storage, "busy", version, status=job_status)
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        response = await http.delete(
            "/knowledge/admin/source", params={"source_id": "busy", "version": version}
        )
    assert response.status_code == 409
    assert documents.deletions == []
    with storage.transaction() as session:
        assert session.get(KnowledgeSource, ("recipes", "busy", version)).status == source_status


@pytest.mark.asyncio
async def test_failed_vector_delete_keeps_withdrawn_records_for_retry_and_hides_provider_error(
    storage,
):
    version = add_source(storage, "guide", metadata={"kind": "document"})
    add_job(storage, "guide", version)
    documents = Documents(RuntimeError("secret-provider-token"))
    async with client(application(storage, documents=documents)) as http:
        params = {"source_id": "guide", "version": version}
        response = await http.delete("/knowledge/admin/source", params=params)
        assert response.status_code == 503
        assert "secret-provider-token" not in response.text
        assert response.json()["detail"] == "未能确认删除结果，可能已停用检索，请刷新核对后重试。"
        detail = (await http.get("/knowledge/admin/source", params={"source_id": "guide"})).json()
        assert detail["source"]["status"] == "withdrawn" and len(detail["jobs"]) == 1
        documents.failure = None
        retried = await http.delete("/knowledge/admin/source", params=params)
        assert retried.status_code == 200 and retried.json()["versions"] == 1
    assert documents.deletions == [("guide", (version,)), ("guide", (version,))]


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"source_id": " ", "version": "v1"},
        {"source_id": "a" * 256, "version": "v1"},
        {"source_id": "guide"},
        {"source_id": "guide", "version": " "},
        {"source_id": "guide", "version": "v1", "other": "x"},
    ],
)
@pytest.mark.asyncio
async def test_delete_requires_confirmed_source_version_and_rejects_unknown_fields(storage, query):
    async with client(application(storage)) as http:
        assert (await http.delete("/knowledge/admin/source", params=query)).status_code == 422


@pytest.mark.asyncio
async def test_delete_is_domain_scoped_and_reports_database_unavailability(storage):
    version = add_source(storage, "foreign", domain="equipment", metadata={"kind": "document"})
    async with client(application(storage)) as http:
        assert (
            await http.delete(
                "/knowledge/admin/source", params={"source_id": "foreign", "version": version}
            )
        ).status_code == 404

    @contextmanager
    def unavailable():
        raise OperationalError("SELECT secret", {}, RuntimeError("password"))
        yield

    async with client(application(storage, transaction=unavailable)) as http:
        response = await http.delete(
            "/knowledge/admin/source", params={"source_id": "guide", "version": "v1"}
        )
        assert response.status_code == 503
        assert "password" not in response.text and "secret" not in response.text


@pytest.mark.asyncio
async def test_delete_rejects_outdated_confirmation_without_withdrawing_newer_version(storage):
    older = add_source(storage, "guide", text="旧版", metadata={"kind": "document"})
    newer = add_source(storage, "guide", text="新版", metadata={"kind": "document"}, age=1)
    documents = Documents()
    async with client(application(storage, documents=documents)) as http:
        response = await http.delete(
            "/knowledge/admin/source", params={"source_id": "guide", "version": older}
        )
    assert response.status_code == 409 and documents.deletions == []
    with storage.transaction() as session:
        assert session.get(KnowledgeSource, ("recipes", "guide", newer)).status == "ready"


@pytest.mark.parametrize("change", ["version", "job"])
@pytest.mark.asyncio
async def test_delete_rechecks_confirmed_versions_and_active_jobs_after_withdrawal(storage, change):
    version = add_source(storage, "guide", metadata={"kind": "document"})
    transactions = 0

    @contextmanager
    def changed_between_phases():
        nonlocal transactions
        transactions += 1
        if transactions == 2:
            if change == "version":
                add_source(storage, "guide", text="新内容", metadata={"kind": "document"}, age=1)
            else:
                add_job(storage, "guide", version, status="processing")
        with storage.transaction() as session:
            yield session

    documents = Documents()
    async with client(
        application(storage, documents=documents, transaction=changed_between_phases)
    ) as http:
        response = await http.delete(
            "/knowledge/admin/source", params={"source_id": "guide", "version": version}
        )
    assert response.status_code == 409 and documents.deletions == []
    with storage.transaction() as session:
        assert session.get(KnowledgeSource, ("recipes", "guide", version)).status == "withdrawn"
        if change == "version":
            assert (
                session.get(KnowledgeSource, ("recipes", "guide", source_version("新内容"))).status
                == "ready"
            )


@pytest.mark.asyncio
async def test_metadata_commit_failure_after_vector_delete_keeps_document_unpublished(storage):
    version = add_source(storage, "guide", metadata={"kind": "document"})
    add_job(storage, "guide", version)
    transactions = 0

    @contextmanager
    def fail_final_commit():
        nonlocal transactions
        transactions += 1
        with storage.transaction() as session:
            yield session
            if transactions == 2:
                raise OperationalError("COMMIT", {}, RuntimeError("database unavailable"))

    documents = Documents()
    async with client(
        application(storage, documents=documents, transaction=fail_final_commit)
    ) as http:
        response = await http.delete(
            "/knowledge/admin/source", params={"source_id": "guide", "version": version}
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "未能确认删除结果，可能已停用检索，请刷新核对后重试。"
    assert documents.deletions == [("guide", (version,))]
    with storage.transaction() as session:
        assert session.get(KnowledgeSource, ("recipes", "guide", version)).status == "withdrawn"
        assert session.get(IngestionJob, "guide-job-0") is not None
        assert KnowledgeRepository(session).published_versions("recipes") == {}


@pytest.mark.asyncio
async def test_retry_read_before_delete_cannot_recreate_the_deleted_source(storage, monkeypatch):
    from gustobot.interfaces.http import knowledge_admin_router

    version = add_source(storage, "guide", metadata={"kind": "document"})
    documents = Documents()
    app = application(storage, documents=documents)
    admin = app.dependency_overrides[knowledge_admin_router.get_admin_service]()
    read_request = admin._retry_request

    def delete_after_read(source_id, content_version):
        request = read_request(source_id, content_version)
        admin.delete_source(source_id, content_version)
        return request

    monkeypatch.setattr(admin, "_retry_request", delete_after_read)
    async with client(app) as http:
        response = await http.post(
            "/knowledge/admin/retry", json={"source_id": "guide", "version": version}
        )
    assert response.status_code == 404 and documents.calls == []
    with storage.transaction() as session:
        assert list(session.scalars(select(KnowledgeSource))) == []
        assert list(session.scalars(select(IngestionJob))) == []
