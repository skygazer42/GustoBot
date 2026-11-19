"""Typed candidate identities, immutable index scopes and deterministic catalogs."""

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = str
CandidateKind = Literal["concept", "entity"]
ReferenceKind = Literal["class", "property", "entity"]
GenerationStatus = Literal["building", "ready", "active", "retired", "failed", "superseded"]
INDEX_SCHEMA_VERSION = "semantic_candidates_v2"
ENTITY_CATALOG_TYPES = (
    "RecipeVariant",
    "Ingredient",
    "CuisineStyle",
    "CookingMethod",
    "DishType",
    "Flavor",
)
QUALIFIER_FIELDS = {"cook_time", "cuisine", "method"}


def normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def embedding_fingerprint(
    *,
    provider: str,
    base_url: str | None,
    model: str,
    revision: str,
    dimension: int,
    normalization: str = "none",
    serialization_version: str = INDEX_SCHEMA_VERSION,
) -> str:
    if (
        not all(value.strip() for value in (provider, model, revision, serialization_version))
        or dimension <= 0
        or normalization not in {"none", "l2"}
    ):
        raise ValueError(
            "Embedding space requires provider, model, revision, dimension and normalization"
        )
    endpoint = urlsplit("https://api.openai.com/v1" if base_url is None else base_url)
    if endpoint.scheme not in {"http", "https"} or endpoint.hostname is None:
        raise ValueError("Embedding endpoint must be an HTTP URL")
    return digest(
        {
            "provider": provider.strip().lower(),
            "endpoint": [
                endpoint.scheme,
                endpoint.hostname.lower(),
                endpoint.port,
                endpoint.path.rstrip("/"),
            ],
            "model": model.strip(),
            "revision": revision.strip(),
            "dimension": dimension,
            "normalization": normalization,
            "serialization_version": serialization_version,
        }
    )


class _LinkModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class IndexScope(_LinkModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    domain_id: str = Field(min_length=1, max_length=64)
    ontology_version: str = Field(min_length=1, max_length=64)
    ontology_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: CandidateKind
    index_schema_version: str = INDEX_SCHEMA_VERSION

    @property
    def key(self) -> str:
        return digest(self.model_dump())

    def validate_record(self, record: "CatalogRecord") -> None:
        for name in (
            "domain_id",
            "ontology_version",
            "ontology_fingerprint",
            "kind",
            "index_schema_version",
        ):
            if getattr(self, name) != getattr(record, name):
                raise ValueError(f"Candidate outside index scope: {name}")


class CatalogRecord(_LinkModel):
    record_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    domain_id: str = Field(min_length=1, max_length=64)
    ontology_version: str = Field(min_length=1, max_length=64)
    ontology_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_schema_version: str = INDEX_SCHEMA_VERSION
    kind: CandidateKind
    ref_kind: ReferenceKind
    ref_id: str = Field(min_length=1, max_length=2048)
    object_type: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    source_labels: list[str] = Field(default_factory=list, max_length=3)
    source_count: int = Field(ge=0)
    source_ids_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_label_count: int = Field(ge=0)
    source_labels_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualifiers: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    text: str = Field(min_length=1, max_length=2048)
    text_truncated: bool = False
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_revision: int | None = Field(default=None, ge=0)

    @classmethod
    def create(
        cls,
        *,
        domain_id: str,
        ontology_version: str,
        ontology_fingerprint: str,
        kind: CandidateKind,
        ref_kind: ReferenceKind,
        ref_id: str,
        object_type: str,
        label: str,
        aliases: Sequence[str] = (),
        source_ids: Sequence[str] = (),
        source_labels: Sequence[str] = (),
        qualifiers: Mapping[str, str] | None = None,
        description: str = "",
        graph_revision: int | None = None,
    ) -> "CatalogRecord":
        qualifiers = {} if qualifiers is None else dict(qualifiers)
        if set(qualifiers) - QUALIFIER_FIELDS:
            raise ValueError("Candidate qualifier field is not allowed")
        unique_aliases = sorted({alias for alias in aliases if alias.strip()} - {label})
        all_sources = sorted(set(source_ids))
        all_labels = sorted(set(source_labels))
        labels = all_labels[:3]
        body = {
            "type": object_type,
            "name": normalize_name(label),
            "aliases": sorted(
                {normalize_name(alias) for alias in unique_aliases} - {normalize_name(label)}
            ),
            "sources": sorted({normalize_name(value) for value in labels}),
            "qualifiers": {key: normalize_name(value) for key, value in qualifiers.items()},
        }
        if kind == "concept":
            body["description"] = normalize_name(description)
        full_text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        text = full_text[:2048]
        values = {
            "domain_id": domain_id,
            "ontology_version": ontology_version,
            "ontology_fingerprint": ontology_fingerprint,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "kind": kind,
            "ref_kind": ref_kind,
            "ref_id": ref_id,
            "object_type": object_type,
            "label": label,
            "aliases": unique_aliases,
            "source_ids": all_sources[:8],
            "source_labels": labels,
            "source_count": len(all_sources),
            "source_ids_hash": digest(all_sources),
            "source_label_count": len(all_labels),
            "source_labels_hash": digest(all_labels),
            "qualifiers": qualifiers,
            "description": description if kind == "concept" else "",
            "text": text,
            "text_truncated": len(full_text) > 2048,
            "text_hash": hashlib.sha256(text.encode()).hexdigest(),
            "graph_revision": graph_revision,
        }
        values["record_id"] = digest([domain_id, ontology_fingerprint, kind, ref_kind, ref_id])
        values["record_hash"] = digest(values)
        return cls.model_validate(values)

    @model_validator(mode="after")
    def _validate_identity_and_hashes(self):
        if (self.kind == "entity") != (self.ref_kind == "entity"):
            raise ValueError("Candidate kind and reference kind disagree")
        if self.kind == "concept" and self.graph_revision is not None:
            raise ValueError("Concept candidates cannot depend on graph revisions")
        if not self.label.strip() or any(not alias.strip() for alias in self.aliases):
            raise ValueError("Candidate labels and aliases cannot be blank")
        if set(self.qualifiers) - QUALIFIER_FIELDS:
            raise ValueError("Candidate qualifier field is not allowed")
        for sample, count, expected_hash in (
            (self.source_ids, self.source_count, self.source_ids_hash),
            (self.source_labels, self.source_label_count, self.source_labels_hash),
        ):
            if (
                count < len(sample)
                or sample != sorted(set(sample))
                or (count == len(sample) and digest(sample) != expected_hash)
            ):
                raise ValueError("Candidate source projection count or checksum is inconsistent")
        values = self.model_dump(exclude={"record_hash"})
        if (
            self.record_id
            != digest(
                [self.domain_id, self.ontology_fingerprint, self.kind, self.ref_kind, self.ref_id]
            )
            or self.text_hash != hashlib.sha256(self.text.encode()).hexdigest()
            or self.record_hash != digest(values)
        ):
            raise ValueError("Candidate identity or content hash mismatch")
        return self


def catalog_checksum(records: Sequence[CatalogRecord]) -> str:
    if len({record.record_id for record in records}) != len(records):
        raise ValueError("Duplicate catalog record identity")
    return digest(sorted((record.record_id, record.record_hash) for record in records))


class GraphRevision(_LinkModel):
    domain_id: str
    ontology_version: str
    ontology_fingerprint: str
    state: Literal["uninitialized", "initializing", "ready"]
    revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ready_requires_revision(self):
        if (self.state == "ready") != (self.revision is not None):
            raise ValueError("Only a ready graph scope has a revision")
        return self


class CatalogPage(_LinkModel):
    records: list[CatalogRecord]
    observed_revision: int
    next_after_id: str | None = None


class CandidateHit(_LinkModel):
    record: CatalogRecord
    scope: IndexScope
    generation_id: str
    vector_score: float = Field(ge=-1.000001, le=1.000001)
    rank_score: float = 0
    retrieval_sources: list[str] = Field(default_factory=lambda: ["vector"])

    @model_validator(mode="after")
    def _check_scope(self):
        self.scope.validate_record(self.record)
        return self

    @property
    def ref_id(self):
        return self.record.ref_id


class LinkedCandidate(_LinkModel):
    record: CatalogRecord
    match_sources: list[str] = Field(default_factory=list)
    vector_score: float | None = None
    rank_score: float = 0
    generation_id: str | None = None

    @property
    def ref_id(self):
        return self.record.ref_id


class NameFamilyResult(_LinkModel):
    items: list[LinkedCandidate]
    has_more: bool = False
    seed_ids: list[str] = Field(default_factory=list)


class ScopeAuditReport(_LinkModel):
    scope: GraphRevision
    existing: int = 0
    validated: int = 0
    invalid: int = 0
    unknown_version: int = 0
    backfilled: int = 0
    errors: list[str] = Field(default_factory=list)


class IndexVerification(_LinkModel):
    valid: bool
    count: int = Field(ge=0)
    checksum: str
    schema_fingerprint: str


class BuildIndexRequest(_LinkModel):
    scope: IndexScope
    batch_size: int = Field(default=64, ge=1, le=1000)
    publish: bool = False
    expected_active_generation: str | None = None


class BuildIndexReceipt(_LinkModel):
    generation_id: str
    status: GenerationStatus
    graph_revision: int | None = None
    exported: int = 0
    embedded: int = 0
    reused: int = 0
    error: str | None = None


class IndexPublicationStatus(_LinkModel):
    scope: IndexScope
    generation_id: str | None = None
    graph_revision: int | None = None
    status: Literal["missing", "ready", "stale", "uninitialized"] = "missing"
    calibration_id: str | None = None
    policy: dict[str, Any] = Field(default_factory=dict)


class IndexGeneration(_LinkModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    generation_id: str
    scope: IndexScope
    graph_revision: int | None = None
    status: GenerationStatus = "building"
    expected_count: int = 0
    written_count: int = 0
    embedded: int = 0
    reused: int = 0
    checksum: str = ""
    error: str | None = None
    owner: str | None = None
    lease_until: datetime | None = None


class ObjectReference(_LinkModel):
    mention: str = Field(min_length=1)
    expected_type: str | None = None
    ref_id: str | None = None


class LinkingContext(_LinkModel):
    question: str
    mode: Literal["off", "shadow", "on"]
    status: str = "ready"
    concepts: list[LinkedCandidate] = Field(default_factory=list)
    entities: list[LinkedCandidate] = Field(default_factory=list)
    families: list[NameFamilyResult] = Field(default_factory=list)
    graph_revision: GraphRevision | None = None
    generations: dict[str, str] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    provider_calls: dict[str, int] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)
    selection_policies: dict[str, dict[str, float]] = Field(default_factory=dict)
    verified_ids: list[str] = Field(default_factory=list)
    reference_text: str = Field(default="", exclude=True, repr=False)
    mention_candidates: dict[str, list[str]] = Field(default_factory=dict)
    query_vectors: dict[str, list[float]] = Field(default_factory=dict, exclude=True, repr=False)


class LinkResolution(_LinkModel):
    references: list[ObjectReference]
    candidates: list[LinkedCandidate]
    status: Literal["resolved", "clarify", "unavailable", "no_candidates"]
    diagnostics: list[str] = Field(default_factory=list)
