"""Managed assets and exact source versions shared by graph and document ingestion."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.mysql import DATETIME, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from gustobot.infrastructure.core.database import Base


def _utc_now() -> datetime:
    """MySQL DATETIME stores naive values; application timestamps are always UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UploadedAsset(Base):
    """Metadata for an uploaded file managed by the application."""

    __tablename__ = "uploaded_assets"
    __table_args__ = (
        CheckConstraint("size >= 0", name="ck_uploaded_assets_nonnegative_size"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_bin"},
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        nullable=False,
        default=_utc_now,
    )


class KnowledgeSource(Base):
    """Immutable text version and publication metadata for one domain source."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        Index("ix_knowledge_sources_domain_status", "domain_id", "status"),
        Index("ix_knowledge_sources_domain_ontology", "domain_id", "ontology_version"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_bin"},
    )

    domain_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
    ontology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        nullable=False,
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )


class IngestionJob(Base):
    """Current status, progress, and failure details for one source ingestion."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["domain_id", "source_id", "source_version"],
            [
                "knowledge_sources.domain_id",
                "knowledge_sources.source_id",
                "knowledge_sources.version",
            ],
            name="fk_ingestion_jobs_source_version",
            ondelete="RESTRICT",
        ),
        Index("ix_ingestion_jobs_domain_status", "domain_id", "status"),
        Index("ix_ingestion_jobs_source", "domain_id", "source_id", "source_version"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_0900_bin"},
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        nullable=False,
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime().with_variant(DATETIME(fsp=6), "mysql"),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )
