"""Parse managed source files without generating or rewriting their contents."""

import asyncio
import csv
import hashlib
import io
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
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
from sqlalchemy.orm import Session

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
from gustobot.infrastructure.persistence.db.models.knowledge import (
    IngestionJob,
    KnowledgeSource,
)


def parse_document(path: Path) -> str:
    """Extract text from supported formats and reject unreadable or empty files."""
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
    """Document text or managed upload plus source identity and ingestion context."""

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
    """Client-facing receipt for one source version ingestion job."""

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
    """Persisted job state and timestamps returned by the status endpoint."""

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
    """Ingestion failure carrying its receipt and any metadata-write failure."""

    def __init__(self, receipt: IngestionReceipt, metadata_error: Exception | None = None):
        super().__init__(f"Ingestion job {receipt.job_id} failed")
        self.receipt = receipt
        self.metadata_error = metadata_error


class DocumentRevisionConflict(ValueError):
    """The source changed or is busy before an editor could register its revision."""


def document_revision(
    domain_id: str,
    source_id: str,
    version: str,
    updated_at: datetime,
    metadata: dict[str, object] | None,
) -> str:
    """Identify an actual persisted editor snapshot, including changes to its title."""
    snapshot = [domain_id, source_id, version, updated_at.isoformat(), metadata]
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        """Resolve request text or an owned upload into a versioned source record."""
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

    def _revision_source(
        self,
        session: Session,
        source_id: str,
        expected_version: str,
        expected_revision: str,
        version: str,
    ) -> KnowledgeSource:
        """Lock the whole source family before accepting an editor's version reference."""
        sources = list(
            session.scalars(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.domain_id == self.domain.id,
                    KnowledgeSource.source_id == source_id,
                )
                .order_by(KnowledgeSource.created_at.desc(), KnowledgeSource.version.desc())
                .with_for_update()
            )
        )
        if not sources or expected_version not in {source.version for source in sources}:
            raise LookupError("找不到指定的文档版本。")
        current = sources[0]
        if current.version != expected_version:
            raise DocumentRevisionConflict("文档已有新版本，请刷新后重新编辑。")
        if any(
            source.source_metadata is None or source.source_metadata.get("kind") != "document"
            for source in sources
        ):
            raise DocumentRevisionConflict("只能编辑文档原文，图谱资料请单独管理。")
        if (
            document_revision(
                current.domain_id,
                current.source_id,
                current.version,
                current.updated_at,
                current.source_metadata,
            )
            != expected_revision
        ):
            raise DocumentRevisionConflict("文档已被修改，请刷新后重新编辑，避免覆盖他人的修改。")
        active_job = session.scalar(
            select(IngestionJob.id)
            .where(
                IngestionJob.domain_id == self.domain.id,
                IngestionJob.source_id == source_id,
                IngestionJob.status.in_(("pending", "processing")),
            )
            .limit(1)
            .with_for_update()
        )
        if active_job is not None or any(
            source.status in {"pending", "processing"} for source in sources
        ):
            raise DocumentRevisionConflict("文档正在入库，请等待任务结束后再编辑。")
        if version != current.version and version in {source.version for source in sources}:
            raise DocumentRevisionConflict("正文与某个历史版本相同，暂不支持通过编辑回退历史版本。")
        if source_version(current.text) != current.version:
            raise DocumentRevisionConflict("原文与版本记录不一致，请先核对来源。")
        return current

    def _start(
        self,
        source: SourceDocument,
        kind: Literal["document", "recipe"],
        context: dict[str, Any],
        require_existing: bool = False,
        expected_version: str | None = None,
        expected_revision: str | None = None,
    ) -> IngestionReceipt:
        """Persist the immutable source and initial job state before external writes."""
        # 内容决定版本，同一内容的重试复用来源身份，但每次尝试都有独立任务记录。
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
            if expected_version is not None:
                if expected_revision is None:
                    raise DocumentRevisionConflict("缺少文档编辑快照，请刷新后重新编辑。")
                current = self._revision_source(
                    session, source.id, expected_version, expected_revision, version
                )
                assert current.source_metadata is not None
                stored_context = current.source_metadata
                metadata = cast(dict[str, Any], stored_context.get("metadata", {}))
                previous_revision = metadata.get("local_revision", {})
                context = {
                    name: value for name, value in stored_context.items() if name != "kind"
                } | {
                    "metadata": metadata
                    | {
                        "title": context["metadata"]["title"],
                        "local_revision": {
                            "previous_version": expected_version,
                            "content_version": version,
                            "edited_at": datetime.now(timezone.utc).isoformat(),
                            "graph_review_required": (
                                version != expected_version
                                or previous_revision.get("graph_review_required") is True
                            ),
                        },
                    },
                    "entity_ids": stored_context.get("entity_ids"),
                }
                source = SourceDocument(id=source.id, text=source.text, uri=current.uri)
                details["context"] = context
                if (
                    version == expected_version
                    and current.status == "ready"
                    and current.ontology_version == self.domain.version
                ):
                    document = session.scalar(
                        select(IngestionJob.details["document"])
                        .where(
                            IngestionJob.domain_id == self.domain.id,
                            IngestionJob.source_id == source.id,
                            IngestionJob.source_version == version,
                            IngestionJob.status == "ready",
                            IngestionJob.details["ontology_version"].as_string()
                            == self.domain.version,
                        )
                        .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
                        .limit(1)
                    )
                    if document is None:
                        raise DocumentRevisionConflict("文档缺少切片回执，请先重试入库后再更名。")
                    manifest = DocumentIngestionResult.model_validate(document)
                    if (manifest.domain_id, manifest.source_id, manifest.version) != (
                        self.domain.id,
                        source.id,
                        version,
                    ) or manifest.chunks != len(manifest.ids):
                        raise DocumentRevisionConflict(
                            "文档切片回执与原文版本不一致，请先重试入库。"
                        )
                    details["external_write"] = "not_needed"
                    details["document"] = manifest.model_copy(update={"embedded": 0}).model_dump()
            details["source_uri"] = source.uri
            existing = session.scalar(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.domain_id == self.domain.id,
                    KnowledgeSource.source_id == source.id,
                    KnowledgeSource.version == version,
                )
                .with_for_update()
            )
            if require_existing and existing is None:
                raise LookupError("Knowledge source version no longer exists")
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
        """Persist the job and source publication outcome for one ingestion attempt."""
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
            # 新尝试失败时，不能顺带撤销此前已经成功发布的同一来源版本。
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
        """Record a failed attempt and preserve any independent metadata-write error."""
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
        write: Callable[[IngestionReceipt], Awaitable[DocumentIngestionResult | GraphWriteResult]],
        *,
        require_existing: bool = False,
        expected_version: str | None = None,
        expected_revision: str | None = None,
    ) -> IngestionReceipt:
        """Record progress, run the external write, then publish its outcome."""
        # MySQL 元数据和外部存储无法共用事务：先登记任务，写成功后再发布来源。
        start = asyncio.create_task(
            asyncio.to_thread(
                self._start,
                source,
                kind,
                context,
                require_existing,
                expected_version,
                expected_revision,
            )
        )
        receipt = None
        completion = None
        details: dict[str, Any] = {}
        try:
            receipt = await asyncio.shield(start)
            details = dict(receipt.details)
            if details["external_write"] != "not_needed":
                details["external_write"] = "attempted"
                result = await write(receipt)
                result_key = "document" if kind == "document" else "graph"
                details.update(
                    {"external_write": "succeeded", result_key: result.model_dump(mode="json")}
                )
            details["metadata_recorded"] = True
            status = "ready" if kind == "document" else "graph_ready"
            completion = asyncio.create_task(
                asyncio.to_thread(self._outcome, receipt, status, details)
            )
            return await asyncio.shield(completion)
        except asyncio.CancelledError as cancellation:

            async def finish_metadata(task):
                """Wait for a database thread to finish despite repeated cancellation."""
                # 取消协程无法终止已运行的数据库线程，必须等结果落定再记录取消状态。
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

    async def ingest_document(
        self,
        request: DocumentIngestionRequest,
        *,
        require_existing: bool = False,
        expected_version: str | None = None,
        expected_revision: str | None = None,
    ) -> IngestionReceipt:
        """Index text or a managed upload and publish the source after success."""
        source, context = await asyncio.to_thread(self._document_source, request)

        async def write(receipt: IngestionReceipt):
            """Resolve the document service lazily and index the source chunks."""
            documents = self.documents
            if documents is None:
                raise RuntimeError("Document index is not configured")
            if callable(documents):
                documents = await asyncio.to_thread(documents)
            registered = SourceDocument(
                id=source.id, text=source.text, uri=receipt.details["source_uri"]
            )
            return await documents.ingest_source(
                registered, entity_ids=receipt.details["context"]["entity_ids"]
            )

        return await self._execute(
            source,
            "document",
            context,
            write,
            require_existing=require_existing,
            expected_version=expected_version,
            expected_revision=expected_revision,
        )

    async def ingest_recipe(self, name: str, record: dict) -> IngestionReceipt:
        """Validate a recipe graph, write it, then publish its source version."""
        # 先绑定稳定身份并校验事实，再写入图；重复菜名不代表同一份来源做法。
        graph = recipe_to_facts(name, record, domain=self.domain)
        if self.semantic_runtime is None:
            validate_graph(self.domain, graph)
        else:
            graph = self.semantic_runtime.bind_graph(graph)
            self.semantic_runtime.validate_input(graph)

        async def write(_receipt: IngestionReceipt):
            """Resolve the graph store lazily and write the validated recipe facts."""
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
        """Return the job in this domain, or None when the identifier is unknown."""
        return await asyncio.to_thread(self._get_job, job_id)

    def _withdraw_source(self, source_id: str):
        """Withdraw every version of a source from published retrieval."""
        # 撤回只改变发布可见性，保留原文和版本记录；图事实不由此操作删除。
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
        """Withdraw all document versions while retaining their stored content."""
        return await asyncio.to_thread(self._withdraw_source, source_id)
