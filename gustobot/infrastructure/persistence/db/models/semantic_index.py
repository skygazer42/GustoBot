"""Rebuildable candidate generations and MySQL-owned publication pointers."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from gustobot.domain.linking import GenerationStatus
from gustobot.infrastructure.core.database import Base
from gustobot.infrastructure.persistence.db.models.knowledge import _utc_now

_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_bin",
}
_TIME = DateTime().with_variant(DATETIME(fsp=6), "mysql")


class SemanticIndexGeneration(Base):
    __tablename__ = "semantic_index_generations"
    __table_args__ = (
        UniqueConstraint("scope_key", "generation_id", name="uq_semantic_generation_scope_id"),
        Index("ix_semantic_generation_scope_status", "scope_key", "status"),
        CheckConstraint(
            "status IN ('building','ready','active','retired','failed','superseded')",
            name="ck_semantic_generation_status",
        ),
        CheckConstraint(
            "expected_count >= 0 AND written_count >= 0 AND embedded >= 0 AND reused >= 0",
            name="ck_semantic_generation_counts",
        ),
        _OPTIONS,
    )

    generation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    graph_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[GenerationStatus] = mapped_column(String(32), nullable=False, default="building")
    expected_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    written_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    embedded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reused: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(_TIME, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TIME, nullable=False, default=_utc_now)
    started_at: Mapped[datetime] = mapped_column(_TIME, nullable=False, default=_utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(_TIME, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        _TIME, nullable=False, default=_utc_now, onupdate=_utc_now
    )


class SemanticIndexPublication(Base):
    __tablename__ = "semantic_index_publications"
    __table_args__ = (
        UniqueConstraint(
            "domain_id",
            "kind",
            "ontology_fingerprint",
            "embedding_fingerprint",
            "index_schema_version",
            name="uq_semantic_publication_scope",
        ),
        ForeignKeyConstraint(
            ["scope_key", "active_generation_id"],
            ["semantic_index_generations.scope_key", "semantic_index_generations.generation_id"],
            name="fk_semantic_publication_generation",
            ondelete="RESTRICT",
        ),
        _OPTIONS,
    )

    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ontology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ontology_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    index_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    active_generation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    graph_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    calibration_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        _TIME, nullable=False, default=_utc_now, onupdate=_utc_now
    )


@event.listens_for(SemanticIndexGeneration, "before_update")
def _protect_generation_identity(mapper, connection, generation):
    state = inspect(generation)
    for name in ("generation_id", "scope_key", "scope_json", "graph_revision"):
        if state.attrs[name].history.has_changes():
            raise ValueError("Generation scope and revision are immutable")
