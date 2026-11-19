"""Source administration reads exact persisted identities and reuses ingestion."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, select
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
)


class Documents:
    def __init__(self, failure=None, *, chunk=None):
        self.calls = []
        self.chunk_reads = []
        self.failure = failure
        self.chunk = chunk

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
