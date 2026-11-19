"""Parse managed source files without generating or rewriting their contents."""

import asyncio
import csv
import io
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import anyio
from docx import Document
from docx.text.paragraph import Paragraph
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pypdf import PdfReader
from sqlalchemy import select

from gustobot.domain.knowledge import DomainDefinition, SourceDocument, validate_graph
from gustobot.infrastructure.core.database import session_scope
from gustobot.infrastructure.knowledge.graph_store import (
    GraphWriteResult,
    Neo4jGraphStore,
)
from gustobot.infrastructure.knowledge.knowledge_service import (
    DocumentIngestionResult,
    KnowledgeService,
    source_version,
)
from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts
from gustobot.infrastructure.knowledge.semantic_runtime import get_semantic_runtime
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository
from gustobot.infrastructure.persistence.db.models.knowledge import KnowledgeSource


def parse_document(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in {".txt", ".md", ".markdown", ".json", ".csv", ".log"}:
        text = path.read_text(encoding="utf-8-sig")
        if extension == ".json":
            json.loads(text)
        elif extension == ".csv":
            list(csv.reader(io.StringIO(text), strict=True))
    elif extension == ".pdf":
        with path.open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF documents are not supported")
            text = "\n\n".join(page.extract_text() for page in reader.pages)
        if not text.strip():
            raise ValueError("PDF has no extractable text; OCR is required before ingestion")
    elif extension == ".docx":
        document = Document(str(path))
        blocks = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                blocks.append(block.text)
            else:
                blocks.extend("\t".join(cell.text for cell in row.cells) for row in block.rows)
        text = "\n".join(blocks)
    else:
        raise ValueError(f"Unsupported document format: {extension}")
    if not text.strip():
        raise ValueError("Document contains no text")
    return text


PROJECT_UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "uploads"
_PUBLICATION_KINDS = {"ready": "document", "graph_ready": "recipe"}


class DocumentIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_id: str | None = Field(default=None, min_length=1, max_length=255)
    uri: str | None = None
    entity_ids: list[str] | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_one_source(self):
        if (self.text is None) == (self.asset_id is None):
            raise ValueError("Provide exactly one of text or managed asset_id")
        if self.text is not None and not self.text.strip():
            raise ValueError("Document text must not be blank")
        return self

    @field_validator("source_id", "asset_id")
    @classmethod
    def _nonblank_identity(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Source and asset IDs must not be blank")
        return value

    @field_validator("entity_ids")
    @classmethod
    def _nonblank_entities(cls, value):
        if value is not None and any(not identifier.strip() for identifier in value):
            raise ValueError("Entity IDs must not be blank")
        return value


class IngestionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    domain_id: str
    source_id: str
    version: str
    ontology_version: str
    kind: Literal["document", "recipe"]
    status: str
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class IngestionJobStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    domain_id: str
    source_id: str
    source_version: str
    status: str
    error: str | None
    details: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class IngestionFailed(RuntimeError):
    def __init__(self, receipt: IngestionReceipt, metadata_error: Exception | None = None):
        super().__init__(f"Ingestion job {receipt.job_id} failed")
        self.receipt = receipt
        self.metadata_error = metadata_error


class KnowledgeIngestionService:
    """Publish source versions only after the requested external write succeeds."""

    def __init__(
        self,
        domain: DomainDefinition,
        *,
        documents: KnowledgeService | Callable[[], KnowledgeService] | None = None,
        graph_store: Neo4jGraphStore | Callable[[], Neo4jGraphStore] | None = None,
        session_factory=session_scope,
        upload_root: Path = PROJECT_UPLOAD_ROOT,
    ):
        self.domain = domain
        self.documents = documents
        self.graph_store = graph_store
        self.semantic_runtime = get_semantic_runtime(domain)
        self.session_factory = session_factory
        self.upload_root = upload_root.resolve()

    def _document_source(
        self, request: DocumentIngestionRequest
    ) -> tuple[SourceDocument, dict[str, Any]]:
        context: dict[str, Any] = {
            "metadata": request.metadata,
            "entity_ids": request.entity_ids,
        }
        if request.text is not None:
            source_id = request.source_id or source_version(request.text)
            return SourceDocument(id=source_id, text=request.text, uri=request.uri), context
        with self.session_factory() as session:
            # The request validator guarantees asset_id when text is absent.
            asset = KnowledgeRepository(session).get_asset(cast(str, request.asset_id))
            if asset is None:
                raise LookupError("Uploaded asset not found")
            asset_id, original_name, stored_path = (
                asset.id,
                asset.original_name,
                asset.path,
            )
        path = Path(stored_path).resolve()
        if not path.is_relative_to(self.upload_root) or not path.is_file():
            raise ValueError("Document must refer to an available managed upload")
        text = parse_document(path)
        context.update({"asset_id": asset_id, "original_name": original_name})
        return (
            SourceDocument(
                id=request.source_id or f"asset:{asset_id}",
                text=text,
                uri=request.uri if request.uri is not None else f"asset:{asset_id}/{original_name}",
            ),
            context,
        )

    def _start(
        self,
        source: SourceDocument,
        kind: Literal["document", "recipe"],
        context: dict[str, Any],
    ) -> IngestionReceipt:
        version = source_version(source.text)
        job_id = str(uuid4())
        details: dict[str, Any] = {
            "kind": kind,
            "ontology_version": self.domain.version,
            "context": context,
            "external_write": "not_started",
        }
        with self.session_factory() as session:
            repository = KnowledgeRepository(session)
            existing = session.scalar(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.domain_id == self.domain.id,
                    KnowledgeSource.source_id == source.id,
                    KnowledgeSource.version == version,
                )
                .with_for_update()
            )
            if existing is not None:
                recorded_kind = (
                    None
                    if existing.source_metadata is None
                    else existing.source_metadata.get("kind")
                )
                publication_kind = _PUBLICATION_KINDS.get(existing.status)
                if (recorded_kind is not None and recorded_kind != kind) or (
                    publication_kind is not None and publication_kind != kind
                ):
                    raise ValueError("A source version cannot change its ingestion kind")
            registered = repository.put_source(
                domain_id=self.domain.id,
                source_id=source.id,
                version=version,
                uri=source.uri if source.uri is not None else source.id,
                text=source.text,
                ontology_version=self.domain.version,
                metadata={"kind": kind, **context},
            )
            details["source_ontology_version"] = registered.ontology_version
            if registered.status not in _PUBLICATION_KINDS:
                registered.ontology_version = self.domain.version
                metadata = {} if registered.source_metadata is None else registered.source_metadata
                registered.source_metadata = metadata | {"kind": kind, **context}
                registered.status = "processing"
            repository.create_job(
                id=job_id,
                domain_id=self.domain.id,
                source_id=source.id,
                source_version=version,
                status="processing",
                details=details,
            )
        return IngestionReceipt(
            job_id=job_id,
            domain_id=self.domain.id,
            source_id=source.id,
            version=version,
            ontology_version=self.domain.version,
            kind=kind,
            status="processing",
            details=details,
        )

    def _outcome(
        self,
        receipt: IngestionReceipt,
        status: str,
        details: dict[str, Any],
        error: str | None = None,
    ) -> IngestionReceipt:
        with self.session_factory() as session:
            repository = KnowledgeRepository(session)
            source = session.scalar(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.domain_id == receipt.domain_id,
                    KnowledgeSource.source_id == receipt.source_id,
                    KnowledgeSource.version == receipt.version,
                )
                .with_for_update()
            )
            if source is None:
                raise LookupError("Knowledge source version not found")
            if source.status == "withdrawn":
                if status in {"ready", "graph_ready"}:
                    raise RuntimeError("Source was withdrawn while ingestion was running")
            elif status in _PUBLICATION_KINDS:
                metadata = {} if source.source_metadata is None else dict(source.source_metadata)
                if _PUBLICATION_KINDS[status] != receipt.kind or (
                    metadata.get("kind") is not None and metadata["kind"] != receipt.kind
                ):
                    raise RuntimeError("Source ingestion kind changed while processing")
                if source.ontology_version not in {
                    receipt.ontology_version,
                    receipt.details["source_ontology_version"],
                }:
                    raise RuntimeError("Source processing moved to a different ontology version")
                context = {
                    name: value
                    for name, value in receipt.details["context"].items()
                    if name != "entity_ids" or value is not None
                }
                source.ontology_version = receipt.ontology_version
                source.source_metadata = metadata | context | {"kind": receipt.kind}
                source.status = status
            elif (
                source.status not in _PUBLICATION_KINDS
                and source.ontology_version == receipt.ontology_version
            ):
                source.status = status
            repository.update_job(receipt.job_id, status=status, error=error, details=details)
        return receipt.model_copy(update={"status": status, "error": error, "details": details})

    async def _failed(
        self,
        receipt: IngestionReceipt,
        status: str,
        details: dict[str, Any],
        error: str,
    ) -> tuple[IngestionReceipt, Exception | None]:
        try:
            outcome = await asyncio.to_thread(
                self._outcome,
                receipt,
                status,
                details | {"metadata_recorded": True},
                error,
            )
            return outcome, None
        except Exception as metadata_error:  # noqa: BLE001 - Report both failures in the receipt.
            logger.exception("Could not record the outcome of ingestion job {}", receipt.job_id)
            return (
                receipt.model_copy(
                    update={
                        "status": status,
                        "error": error,
                        "details": details | {"metadata_recorded": False},
                    }
                ),
                metadata_error,
            )

    async def _execute(
        self,
        source: SourceDocument,
        kind: Literal["document", "recipe"],
        context: dict[str, Any],
        write: Callable[[], Awaitable[DocumentIngestionResult | GraphWriteResult]],
    ) -> IngestionReceipt:
        start = asyncio.create_task(asyncio.to_thread(self._start, source, kind, context))
        receipt = None
        completion = None
        details: dict[str, Any] = {}
        try:
            receipt = await asyncio.shield(start)
            details = receipt.details | {"external_write": "attempted"}
            result = await write()
            details = details | {
                "external_write": "succeeded",
                "document" if kind == "document" else "graph": result.model_dump(mode="json"),
                "metadata_recorded": True,
            }
            status = "ready" if kind == "document" else "graph_ready"
            completion = asyncio.create_task(
                asyncio.to_thread(self._outcome, receipt, status, details)
            )
            return await asyncio.shield(completion)
        except asyncio.CancelledError as cancellation:

            async def finish_metadata(task):
                # A running DB thread cannot be stopped; retain its result through repeated cancellation.
                with anyio.CancelScope(shield=True):
                    while not task.done():
                        try:
                            await asyncio.shield(task)
                        except asyncio.CancelledError:
                            continue
                return task.result()

            if receipt is None:
                try:
                    receipt = await finish_metadata(start)
                    details = dict(receipt.details)
                except Exception as error:
                    logger.exception(
                        "Could not finish initial metadata registration after cancellation"
                    )
                    raise cancellation from error
            if completion is not None:
                try:
                    await finish_metadata(completion)
                except Exception as error:  # noqa: BLE001
                    # Preserve cancellation and expose an independently failed commit.
                    details = details | {"completion_error": str(error)}
            outcome = asyncio.create_task(
                self._failed(receipt, "cancelled", details, "Ingestion cancelled")
            )
            await finish_metadata(outcome)
            raise
        except Exception as error:
            if receipt is None:
                raise
            failed, metadata_error = await self._failed(receipt, "failed", details, str(error))
            raise IngestionFailed(failed, metadata_error) from error

    async def ingest_document(self, request: DocumentIngestionRequest) -> IngestionReceipt:
        source, context = await asyncio.to_thread(self._document_source, request)

        async def write():
            documents = self.documents
            if documents is None:
                raise RuntimeError("Document index is not configured")
            if callable(documents):
                documents = await asyncio.to_thread(documents)
            return await documents.ingest_source(source, entity_ids=request.entity_ids)

        return await self._execute(source, "document", context, write)

    async def ingest_recipe(self, name: str, record: dict) -> IngestionReceipt:
        graph = recipe_to_facts(name, record, domain=self.domain)
        if self.semantic_runtime is None:
            validate_graph(self.domain, graph)
        else:
            graph = self.semantic_runtime.bind_graph(graph)
            self.semantic_runtime.validate_input(graph)

        async def write():
            graph_store = self.graph_store
            if graph_store is None:
                raise RuntimeError("Fact graph is not configured")
            if callable(graph_store):
                graph_store = await asyncio.to_thread(graph_store)
            return await graph_store.upsert(graph)

        return await self._execute(graph.sources[0], "recipe", {}, write)

    def _get_job(self, job_id: str) -> IngestionJobStatus | None:
        with self.session_factory() as session:
            job = KnowledgeRepository(session).get_job(job_id, domain_id=self.domain.id)
            return None if job is None else IngestionJobStatus.model_validate(job)

    async def get_job(self, job_id: str) -> IngestionJobStatus | None:
        return await asyncio.to_thread(self._get_job, job_id)

    def _withdraw_source(self, source_id: str):
        with self.session_factory() as session:
            sources = session.scalars(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.domain_id == self.domain.id,
                    KnowledgeSource.source_id == source_id,
                )
                .with_for_update()
            ).all()
            if not sources:
                raise LookupError("Knowledge source not found")
            if any(
                source.source_metadata is None or source.source_metadata.get("kind") != "document"
                for source in sources
            ):
                raise ValueError(
                    "This operation withdraws document sources only; graph facts are retained"
                )
            for source in sources:
                source.status = "withdrawn"
        return {
            "domain_id": self.domain.id,
            "source_id": source_id,
            "status": "withdrawn",
            "versions": len(sources),
        }

    async def withdraw_source(self, source_id: str):
        return await asyncio.to_thread(self._withdraw_source, source_id)
