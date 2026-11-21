"""Metadata operations flush changes; the ingestion or HTTP caller owns the transaction."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from gustobot.infrastructure.persistence.db.models.knowledge import (
    IngestionJob,
    KnowledgeSource,
    UploadedAsset,
)


class KnowledgeRepository:
    """Persist source, uploaded-asset, and ingestion-job records."""

    # 仓储只 flush，不自行 commit；来源状态和任务结果由业务调用方一起提交。
    def __init__(self, session: Session):
        self.session = session

    def get_asset(self, id: str) -> UploadedAsset | None:
        """Return one uploaded-asset record by its public identifier."""
        return self.session.get(UploadedAsset, id)

    def register_asset(
        self, *, id: str, original_name: str, path: str, file_type: str, size: int
    ) -> UploadedAsset:
        """Register an upload without allowing an asset ID to be reused."""
        existing = self.get_asset(id)
        if existing is not None:
            if (existing.original_name, existing.path, existing.file_type, existing.size) != (
                original_name,
                path,
                file_type,
                size,
            ):
                raise ValueError("An asset ID cannot be reused for a different upload")
            return existing
        asset = UploadedAsset(
            id=id, original_name=original_name, path=path, file_type=file_type, size=size
        )
        self.session.add(asset)
        self.session.flush()
        return asset

    def get_source(self, domain_id: str, source_id: str, version: str) -> KnowledgeSource | None:
        """Return one exact domain, source, and version tuple when present."""
        return self.session.get(KnowledgeSource, (domain_id, source_id, version))

    def put_source(
        self,
        *,
        domain_id: str,
        source_id: str,
        version: str,
        uri: str,
        text: str,
        ontology_version: str,
        status: str = "pending",
        metadata: dict[str, object] | None = None,
    ) -> KnowledgeSource:
        """Register immutable content once; a retry preserves existing metadata and status."""
        # 同一来源版本不可改写内容；修订资料必须产生新版本，旧引用才可追溯。
        existing = self.get_source(domain_id, source_id, version)
        if existing is not None:
            if (existing.uri, existing.text) != (uri, text):
                raise ValueError(
                    "Source versions are immutable; changed content requires a new version"
                )
            return existing
        source = KnowledgeSource(
            domain_id=domain_id,
            source_id=source_id,
            version=version,
            uri=uri,
            text=text,
            ontology_version=ontology_version,
            status=status,
            source_metadata=metadata,
        )
        self.session.add(source)
        self.session.flush()
        return source

    def set_source_status(
        self, domain_id: str, source_id: str, version: str, status: str
    ) -> KnowledgeSource:
        """Update one source version's publication status in the current session."""
        source = self.get_source(domain_id, source_id, version)
        if source is None:
            raise LookupError("Knowledge source version not found")
        source.status = status
        self.session.flush()
        return source

    def published_versions(
        self, domain_id: str, *, ontology_version: str | None = None
    ) -> dict[str, str]:
        """Return each source's most recently published ready version in one domain."""
        statement = (
            select(KnowledgeSource.source_id, KnowledgeSource.version)
            .where(KnowledgeSource.domain_id == domain_id, KnowledgeSource.status == "ready")
            .order_by(
                KnowledgeSource.updated_at.desc(),
                KnowledgeSource.created_at.desc(),
                KnowledgeSource.version.desc(),
            )
        )
        if ontology_version is not None:
            statement = statement.where(KnowledgeSource.ontology_version == ontology_version)
        versions: dict[str, str] = {}
        # 按发布时间倒序为每个来源选一个 ready 版本，文档检索据此隔离历史版本。
        for source_id, version in self.session.execute(statement):
            if source_id not in versions:
                versions[source_id] = version
        return versions

    def create_job(
        self,
        *,
        id: str,
        domain_id: str,
        source_id: str,
        source_version: str,
        status: str = "pending",
        details: dict[str, object] | None = None,
    ) -> IngestionJob:
        """Create a stable job record or verify that its ID still names the same source."""
        existing = self.get_job(id)
        if existing is not None:
            if (existing.domain_id, existing.source_id, existing.source_version) != (
                domain_id,
                source_id,
                source_version,
            ):
                raise ValueError("A job ID cannot be reused for a different source version")
            return existing
        job = IngestionJob(
            id=id,
            domain_id=domain_id,
            source_id=source_id,
            source_version=source_version,
            status=status,
            details={} if details is None else details,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, id: str, *, domain_id: str | None = None) -> IngestionJob | None:
        """Find a job by ID, optionally restricting it to one domain."""
        statement = select(IngestionJob).where(IngestionJob.id == id)
        if domain_id is not None:
            statement = statement.where(IngestionJob.domain_id == domain_id)
        return self.session.scalar(statement)

    def update_job(
        self,
        id: str,
        *,
        status: str,
        error: str | None = None,
        details: dict[str, object] | None = None,
    ) -> IngestionJob:
        """Persist a job's latest status, error, and optional progress details."""
        job = self.get_job(id)
        if job is None:
            raise LookupError("Ingestion job not found")
        job.status = status
        job.error = error
        if details is not None:
            job.details = details
        self.session.flush()
        return job
