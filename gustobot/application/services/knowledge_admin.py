"""Browse a bounded source catalog and inspect or retry exact document versions."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import PureWindowsPath
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import JSON, case, delete, func, select, tuple_, type_coerce
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, aliased

from gustobot.application.services.knowledge_ingestion import (
    DocumentIngestionRequest,
    IngestionJobStatus,
    IngestionReceipt,
    KnowledgeIngestionService,
    document_revision,
)
from gustobot.domain.knowledge import DomainDefinition
from gustobot.infrastructure.core.database import session_scope
from gustobot.infrastructure.knowledge.knowledge_service import (
    DocumentIngestionResult,
    KnowledgeService,
    source_version,
)
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository
from gustobot.infrastructure.persistence.db.models.knowledge import (
    IngestionJob,
    KnowledgeSource,
)

SourceListState = Literal["all", "ready", "pending", "withdrawn", "processing", "failed"]
MAX_DOCUMENT_EDIT_CHARS = 1_000_000


class SourceListQuery(BaseModel):
    """Validated filters and pagination for the source administration list."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    q: str = Field(default="", max_length=200)
    state: SourceListState = "all"
    kind: Literal["all", "document", "recipe"] = "all"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class DomainSummary(BaseModel):
    """Identity and active version of the domain owning a source catalog."""

    id: str
    name: str
    version: str


class SourceStats(BaseModel):
    """Counts of current source versions grouped by retrieval and job state."""

    total: int
    ready: int
    pending: int
    withdrawn: int
    processing: int
    failed: int


class LatestJob(BaseModel):
    """Most recent ingestion job associated with a source version."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class SourceSummary(BaseModel):
    """Safe list projection of one source version and its ingestion state."""

    domain_id: str
    source_id: str
    version: str
    uri: str
    title: str
    kind: Literal["document", "recipe", "unknown"]
    status: str
    ontology_version: str
    created_at: datetime
    updated_at: datetime
    chunks: int | None
    entities: int | None
    relations: int | None
    latest_job: LatestJob | None


class SourceCatalog(BaseModel):
    """Paginated source summaries, domain identity, and aggregate counts."""

    domain: DomainSummary
    items: list[SourceSummary]
    total: int
    offset: int
    limit: int
    stats: SourceStats


class SourceDetail(BaseModel):
    """Source summary, bounded text preview, and recent ingestion attempts."""

    source: SourceSummary
    text: str
    text_truncated: bool
    jobs: list[IngestionJobStatus]


class SourceChunk(BaseModel):
    """One numbered document chunk and its total position count."""

    number: int
    total: int
    content: str


class DocumentContent(BaseModel):
    """Complete original text and title used by the version-aware document editor."""

    source_id: str
    version: str
    revision: str
    title: str
    text: str


class SourceDeletion(BaseModel):
    """Receipt for permanently removed document source versions."""

    source_id: str
    versions: int = Field(ge=1)


class SourceConflict(ValueError):
    """An existing source cannot take the requested document-only operation."""


class ChunkUnavailable(RuntimeError):
    """An indexed chunk or its receipt could not be read consistently."""


class SourceDeletionUnavailable(RuntimeError):
    """Document records remain when vector cleanup cannot be confirmed."""


class DocumentTooLarge(ValueError):
    """The complete source exceeds the explicitly supported editing boundary."""


def _public_error(error: str | None) -> str | None:
    # Provider exceptions may contain credentials or server file paths.
    return None if error is None else "入库失败，请检查服务日志后重试"


def _public_details(details: dict[str, Any]) -> dict[str, Any]:
    """Remove internal metadata keys and failures before exposing job details."""
    public = {
        name: details[name]
        for name in (
            "kind",
            "ontology_version",
            "source_ontology_version",
            "external_write",
            "metadata_recorded",
        )
        if name in details
    }
    for section, names in (
        ("document", ("chunks", "embedded")),
        ("graph", ("entities", "relations", "sources")),
    ):
        if section in details:
            public[section] = {
                name: details[section][name] for name in names if name in details[section]
            }
    return public


def public_receipt(receipt: IngestionReceipt) -> IngestionReceipt:
    """Remove private ingestion details before returning a receipt to an API client."""
    return receipt.model_copy(
        update={
            "details": _public_details(receipt.details),
            "error": _public_error(receipt.error),
        }
    )


def _public_uri(uri: str) -> str:
    if uri.lower().startswith("file:"):
        return PureWindowsPath(urlsplit(uri).path).name
    path = PureWindowsPath(uri)
    return path.name if path.drive or path.root else uri


class KnowledgeAdminService:
    """Read source status and retry document versions within one domain."""

    def __init__(
        self,
        domain: DomainDefinition,
        *,
        ingestion: KnowledgeIngestionService,
        documents: Callable[[], KnowledgeService],
        session_factory=session_scope,
    ):
        self.domain = domain
        self.ingestion = ingestion
        self.documents = documents
        self.session_factory = session_factory

    def _source_columns(self):
        """Build the shared source projection used by catalog and detail queries."""
        metadata = KnowledgeSource.source_metadata
        recorded_kind = metadata["kind"].as_string()
        kind = case((recorded_kind.in_(("document", "recipe")), recorded_kind), else_="unknown")
        title = func.coalesce(
            func.nullif(metadata["metadata"]["title"].as_string(), ""),
            func.nullif(metadata["original_name"].as_string(), ""),
            case((kind == "recipe", type_coerce(KnowledgeSource.text, JSON)["name"].as_string())),
            KnowledgeSource.source_id,
        )
        state = case(
            (KnowledgeSource.status.in_(("ready", "graph_ready")), "ready"),
            (KnowledgeSource.status == "withdrawn", "withdrawn"),
            else_="pending",
        )
        return (
            KnowledgeSource.domain_id,
            KnowledgeSource.source_id,
            KnowledgeSource.version,
            KnowledgeSource.uri,
            KnowledgeSource.ontology_version,
            KnowledgeSource.status,
            KnowledgeSource.created_at,
            KnowledgeSource.updated_at,
            metadata,
            kind.label("kind"),
            title.label("title"),
            state.label("state"),
        )

    def _latest_jobs(self, session: Session, sources: list[RowMapping]):
        """Fetch the latest job for each page source without per-row queries."""
        ranked = (
            select(
                IngestionJob,
                func.row_number()
                .over(
                    partition_by=(IngestionJob.source_id, IngestionJob.source_version),
                    order_by=(IngestionJob.created_at.desc(), IngestionJob.id.desc()),
                )
                .label("position"),
            )
            .where(
                IngestionJob.domain_id == self.domain.id,
                tuple_(IngestionJob.source_id, IngestionJob.source_version).in_(
                    [(source["source_id"], source["version"]) for source in sources]
                ),
            )
            .subquery()
        )
        job_model = aliased(IngestionJob, ranked)
        jobs = session.scalars(select(job_model).where(ranked.c.position == 1))
        return {(job.source_id, job.source_version): job for job in jobs}

    def _summary(self, source: RowMapping, job: IngestionJob | None) -> SourceSummary:
        """Project a source row and optional job into safe list response fields."""
        metadata = {} if source["source_metadata"] is None else source["source_metadata"]
        document = cast(dict[str, Any], {} if job is None else job.details.get("document", {}))
        graph = cast(dict[str, Any], {} if job is None else job.details.get("graph", {}))
        graph_counts = metadata.get("graph_counts", {})
        latest_job = (
            None
            if job is None
            else LatestJob.model_validate(job).model_copy(
                update={"error": _public_error(job.error)}
            )
        )
        return SourceSummary(
            **{
                name: source[name]
                for name in (
                    "domain_id",
                    "source_id",
                    "version",
                    "kind",
                    "status",
                    "ontology_version",
                    "created_at",
                    "updated_at",
                )
            },
            uri=_public_uri(source["uri"]),
            title=_public_uri(source["title"]),
            chunks=document.get("chunks"),
            entities=graph.get("entities", graph_counts.get("entities")),
            relations=graph.get("relations", graph_counts.get("relations")),
            latest_job=latest_job,
        )

    def list_sources(self, query: SourceListQuery) -> SourceCatalog:
        """List each source's latest version with state counts and bounded pagination."""
        ranked = (
            select(
                *self._source_columns(),
                func.row_number()
                .over(
                    partition_by=KnowledgeSource.source_id,
                    order_by=(KnowledgeSource.created_at.desc(), KnowledgeSource.version.desc()),
                )
                .label("position"),
            )
            .where(KnowledgeSource.domain_id == self.domain.id)
            .subquery()
        )
        filtered = select(ranked).where(ranked.c.position == 1)
        if query.q:
            filtered = filtered.where(ranked.c.title.contains(query.q, autoescape=True))
        if query.kind != "all":
            filtered = filtered.where(ranked.c.kind == query.kind)
        sources = filtered.subquery()
        states = {
            "ready": sources.c.state == "ready",
            "pending": sources.c.state == "pending",
            "withdrawn": sources.c.state == "withdrawn",
            "processing": sources.c.status == "processing",
            "failed": sources.c.status == "failed",
        }
        counts = select(
            func.count().label("total"),
            *(
                func.coalesce(func.sum(case((matches, 1), else_=0)), 0).label(state)
                for state, matches in states.items()
            ),
        ).select_from(sources)
        page = select(sources)
        if query.state != "all":
            page = page.where(states[query.state])
        page = (
            page.order_by(sources.c.updated_at.desc(), sources.c.source_id)
            .offset(query.offset)
            .limit(query.limit)
        )
        with self.session_factory() as session:
            stats = SourceStats.model_validate(dict(session.execute(counts).mappings().one()))
            rows = list(session.execute(page).mappings())
            jobs = self._latest_jobs(session, rows) if rows else {}
            items = [
                self._summary(row, jobs.get((row["source_id"], row["version"]))) for row in rows
            ]
        return SourceCatalog(
            domain=DomainSummary(
                id=self.domain.id, name=self.domain.name, version=self.domain.version
            ),
            items=items,
            total=stats.total if query.state == "all" else getattr(stats, query.state),
            offset=query.offset,
            limit=query.limit,
            stats=stats,
        )

    def read_source(self, source_id: str, version: str | None = None) -> SourceDetail:
        """Return one source version, limiting exposed text and recent job history."""
        statement = select(
            *self._source_columns(),
            func.substr(KnowledgeSource.text, 1, 20000).label("text"),
            (func.char_length(KnowledgeSource.text) > 20000).label("text_truncated"),
        ).where(KnowledgeSource.domain_id == self.domain.id, KnowledgeSource.source_id == source_id)
        if version is not None:
            statement = statement.where(KnowledgeSource.version == version)
        statement = statement.order_by(
            KnowledgeSource.created_at.desc(), KnowledgeSource.version.desc()
        ).limit(1)
        with self.session_factory() as session:
            source = session.execute(statement).mappings().first()
            if source is None:
                raise LookupError("Knowledge source version not found")
            jobs = list(
                session.scalars(
                    select(IngestionJob)
                    .where(
                        IngestionJob.domain_id == self.domain.id,
                        IngestionJob.source_id == source_id,
                        IngestionJob.source_version == source["version"],
                    )
                    .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
                    .limit(10)
                )
            )
            return SourceDetail(
                source=self._summary(source, jobs[0] if jobs else None),
                text=source["text"],
                text_truncated=source["text_truncated"],
                jobs=[
                    IngestionJobStatus.model_validate(job).model_copy(
                        update={
                            "details": _public_details(job.details),
                            "error": _public_error(job.error),
                        }
                    )
                    for job in jobs
                ],
            )

    def read_chunk(self, source_id: str, version: str, number: int) -> SourceChunk:
        """Read a chunk only when its stored receipt matches the selected source."""
        with self.session_factory() as session:
            source = session.execute(
                select(
                    KnowledgeSource.source_metadata["kind"].as_string(),
                    KnowledgeSource.ontology_version,
                ).where(
                    KnowledgeSource.domain_id == self.domain.id,
                    KnowledgeSource.source_id == source_id,
                    KnowledgeSource.version == version,
                )
            ).one_or_none()
            if source is None:
                raise LookupError("找不到指定的来源版本。")
            kind, ontology_version = source
            if kind != "document":
                raise SourceConflict("请使用已入库的文档来源查看切片。")
            document = session.scalar(
                select(IngestionJob.details["document"])
                .where(
                    IngestionJob.domain_id == self.domain.id,
                    IngestionJob.source_id == source_id,
                    IngestionJob.source_version == version,
                    IngestionJob.status == "ready",
                    IngestionJob.details["ontology_version"].as_string() == ontology_version,
                )
                .order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc())
                .limit(1)
            )

        if document is None or (isinstance(document, dict) and "ids" not in document):
            raise SourceConflict("该版本缺少切片记录，请重试入库后再查看。")
        try:
            manifest = DocumentIngestionResult.model_validate(document)
        except ValidationError as error:
            raise ChunkUnavailable("Stored document receipt is invalid") from error
        if (manifest.domain_id, manifest.source_id, manifest.version) != (
            self.domain.id,
            source_id,
            version,
        ) or manifest.chunks != len(manifest.ids):
            raise ChunkUnavailable("Stored document receipt does not match its source or count")
        if not 1 <= number <= manifest.chunks:
            raise LookupError("找不到指定序号的切片。")

        index = number - 1
        try:
            chunk = self.documents().read_chunk(
                manifest.ids[index],
                source_id=source_id,
                source_version=version,
                ontology_version=ontology_version,
            )
        except Exception as error:
            raise ChunkUnavailable("Could not read the stored vector row") from error
        if chunk is None or chunk.chunk_index != index:
            raise ChunkUnavailable("Stored vector row does not match the receipt position")
        return SourceChunk(number=number, total=manifest.chunks, content=chunk.content)

    def read_document(self, source_id: str, version: str) -> DocumentContent:
        """Read the whole editable body or reject it; never turn a preview into input."""
        metadata = KnowledgeSource.source_metadata
        statement = select(
            KnowledgeSource.source_id,
            KnowledgeSource.version,
            KnowledgeSource.updated_at,
            KnowledgeSource.source_metadata,
            metadata["kind"].as_string().label("kind"),
            func.coalesce(
                func.nullif(metadata["metadata"]["title"].as_string(), ""),
                func.nullif(metadata["original_name"].as_string(), ""),
                KnowledgeSource.source_id,
            ).label("title"),
            case(
                (
                    func.char_length(KnowledgeSource.text) <= MAX_DOCUMENT_EDIT_CHARS,
                    KnowledgeSource.text,
                ),
                else_=None,
            ).label("text"),
        ).where(
            KnowledgeSource.domain_id == self.domain.id,
            KnowledgeSource.source_id == source_id,
            KnowledgeSource.version == version,
        )
        with self.session_factory() as session:
            source = session.execute(statement).mappings().one_or_none()
            if source is None:
                raise LookupError("找不到指定的文档版本。")
            if source["kind"] != "document":
                raise SourceConflict("只能编辑文档原文，图谱资料请单独管理。")
            if source["text"] is None:
                raise DocumentTooLarge(
                    f"文档超过 {MAX_DOCUMENT_EDIT_CHARS} 字符，暂不支持在线编辑。"
                )
            return DocumentContent(
                source_id=source["source_id"],
                version=source["version"],
                revision=document_revision(
                    self.domain.id,
                    source["source_id"],
                    source["version"],
                    source["updated_at"],
                    source["source_metadata"],
                ),
                title=_public_uri(source["title"]),
                text=source["text"],
            )

    async def update_document(
        self, source_id: str, version: str, *, revision: str, title: str, text: str
    ) -> IngestionReceipt:
        """Register a guarded revision through the existing indexing publication lifecycle."""
        return await self.ingestion.ingest_document(
            DocumentIngestionRequest(source_id=source_id, text=text, metadata={"title": title}),
            expected_version=version,
            expected_revision=revision,
        )

    def _retry_request(self, source_id: str, version: str) -> DocumentIngestionRequest:
        with self.session_factory() as session:
            source = KnowledgeRepository(session).get_source(self.domain.id, source_id, version)
            if source is None:
                raise LookupError("Knowledge source version not found")
            metadata = source.source_metadata
            if metadata is None or metadata.get("kind") != "document":
                raise SourceConflict("Only recorded document sources can be retried")
            if source_version(source.text) != version:
                raise SourceConflict("Stored content does not match this source version")
            return DocumentIngestionRequest(
                text=source.text,
                source_id=source.source_id,
                uri=source.uri,
                metadata=metadata.get("metadata", {}),
                entity_ids=metadata.get("entity_ids"),
            )

    async def retry(self, source_id: str, version: str) -> IngestionReceipt:
        """Retry ingestion from the exact persisted document version."""
        request = await asyncio.to_thread(self._retry_request, source_id, version)
        return await self.ingestion.ingest_document(request, require_existing=True)

    def _lock_deletable_sources(
        self, session: Session, source_id: str, version: str
    ) -> list[KnowledgeSource]:
        """Lock the exact source family and reject stale or active operations."""
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
        if not sources:
            raise LookupError("找不到这份文档记录。")
        if sources[0].version != version:
            raise SourceConflict("文档已有新版本，请刷新后重新确认删除。")
        if any(
            source.source_metadata is None or source.source_metadata.get("kind") != "document"
            for source in sources
        ):
            raise SourceConflict("只能删除文档记录，图谱资料请在图谱中管理。")
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
            raise SourceConflict("文档正在入库，请等待任务结束后再删除。")
        return sources

    def delete_source(self, source_id: str, version: str) -> SourceDeletion:
        """Withdraw confirmed versions before deleting vectors and their SQL records."""
        with self.session_factory() as session:
            sources = self._lock_deletable_sources(session, source_id, version)
            versions = {source.version for source in sources}
            for source in sources:
                source.status = "withdrawn"

        # SQL and Milvus cannot share a transaction. Keep failed deletions unpublished.
        with self.session_factory() as session:
            sources = self._lock_deletable_sources(session, source_id, version)
            if {source.version for source in sources} != versions or any(
                source.status != "withdrawn" for source in sources
            ):
                raise SourceConflict("文档状态已变化，请刷新后重新确认删除。")
            session.execute(
                delete(IngestionJob).where(
                    IngestionJob.domain_id == self.domain.id,
                    IngestionJob.source_id == source_id,
                    IngestionJob.source_version.in_(versions),
                )
            )
            session.execute(
                delete(KnowledgeSource).where(
                    KnowledgeSource.domain_id == self.domain.id,
                    KnowledgeSource.source_id == source_id,
                    KnowledgeSource.version.in_(versions),
                )
            )
            try:
                self.documents().delete_source(source_id, sorted(versions))
            except Exception as error:
                raise SourceDeletionUnavailable("Document vector cleanup failed") from error
        return SourceDeletion(source_id=source_id, versions=len(versions))
