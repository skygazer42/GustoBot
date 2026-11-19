"""Browse a bounded source catalog and inspect or retry exact document versions."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import PureWindowsPath
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import JSON, case, func, select, tuple_, type_coerce
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, aliased

from gustobot.application.services.knowledge_ingestion import (
    DocumentIngestionRequest,
    IngestionJobStatus,
    IngestionReceipt,
    KnowledgeIngestionService,
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


class SourceListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    q: str = Field(default="", max_length=200)
    state: SourceListState = "all"
    kind: Literal["all", "document", "recipe"] = "all"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class DomainSummary(BaseModel):
    id: str
    name: str
    version: str


class SourceStats(BaseModel):
    total: int
    ready: int
    pending: int
    withdrawn: int
    processing: int
    failed: int


class LatestJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class SourceSummary(BaseModel):
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
    domain: DomainSummary
    items: list[SourceSummary]
    total: int
    offset: int
    limit: int
    stats: SourceStats


class SourceDetail(BaseModel):
    source: SourceSummary
    text: str
    text_truncated: bool
    jobs: list[IngestionJobStatus]


class SourceChunk(BaseModel):
    number: int
    total: int
    content: str


class SourceConflict(ValueError):
    """An existing source cannot take the requested document-only operation."""


class ChunkUnavailable(RuntimeError):
    """An indexed chunk or its receipt could not be read consistently."""


def _public_error(error: str | None) -> str | None:
    # Provider exceptions may contain credentials or server file paths.
    return None if error is None else "入库失败，请检查服务日志后重试"


def _public_details(details: dict[str, Any]) -> dict[str, Any]:
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
        request = await asyncio.to_thread(self._retry_request, source_id, version)
        return await self.ingestion.ingest_document(request)
