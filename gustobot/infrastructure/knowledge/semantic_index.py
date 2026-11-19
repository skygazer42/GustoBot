"""Milvus candidates are scoped, rebuildable identities rather than knowledge facts."""

import json
import math
import re
import struct
from collections.abc import Generator, Mapping, Sequence
from contextlib import closing
from numbers import Real
from typing import Any
from uuid import uuid4

from loguru import logger
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusException,
    connections,
    utility,
)

from gustobot.domain.linking import (
    INDEX_SCHEMA_VERSION,
    CandidateHit,
    CatalogRecord,
    IndexScope,
    IndexVerification,
    catalog_checksum,
    digest,
)

_VARCHAR_LIMITS = {
    "id": 64,
    "generation_id": 64,
    "record_id": 64,
    "domain_id": 256,
    "kind": 16,
    "ref_kind": 16,
    "object_type": 512,
    "ref_id": 8192,
    "ontology_version": 256,
    "ontology_fingerprint": 64,
    "embedding_model": 256,
    "embedding_fingerprint": 64,
    "index_schema_version": 128,
    "text_hash": 64,
    "record_hash": 64,
    "text": 8192,
    "metadata": 65535,
}
_RECORD_SCALARS = (
    "record_id",
    "domain_id",
    "kind",
    "ref_kind",
    "object_type",
    "ref_id",
    "ontology_version",
    "ontology_fingerprint",
    "index_schema_version",
    "text_hash",
    "record_hash",
    "text",
)
_OUTPUT_FIELDS = [*_VARCHAR_LIMITS, "graph_revision", "embedding"]
_GENERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_FLOAT32 = 3.4028234663852886e38


def _literal(value: str | list[str]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _generation_id(value: str) -> str:
    if not isinstance(value, str) or _GENERATION_ID.fullmatch(value) is None:
        raise ValueError("Invalid internal generation ID")
    return value


class SemanticCandidateStore:
    def __init__(
        self,
        collection_name: str | None = None,
        host: str = "localhost",
        port: int = 19530,
        dimension: int = 1536,
        *,
        embedding_model: str,
        embedding_fingerprint: str,
        collection: Collection | None = None,
        index_type: str = "HNSW",
        metric_type: str = "COSINE",
        timeout: float = 1.0,
        initialization_timeout: float = 30.0,
    ) -> None:
        if not embedding_model.strip() or len(embedding_model.encode()) > 256:
            raise ValueError("Embedding model must fit the Milvus schema")
        if _DIGEST.fullmatch(embedding_fingerprint) is None:
            raise ValueError("Embedding fingerprint must be a SHA-256 digest")
        if dimension <= 0 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Vector dimension and timeout must be positive")
        if not math.isfinite(initialization_timeout) or initialization_timeout <= 0:
            raise ValueError("Candidate initialization timeout must be finite and positive")
        if index_type != "HNSW" or metric_type != "COSINE":
            raise ValueError("Candidate index requires HNSW and COSINE")
        if collection_name is None:
            collection_name = f"{INDEX_SCHEMA_VERSION}_{embedding_fingerprint[:24]}"
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", collection_name) is None:
            raise ValueError("Candidate collection name must be a code-safe Milvus identifier")
        self.collection_name = collection_name
        self.host, self.port = host, port
        self.dimension = dimension
        self.embedding_model = embedding_model
        self.embedding_fingerprint = embedding_fingerprint
        self.index_type, self.metric_type = index_type, metric_type
        self.timeout = timeout
        self.initialization_timeout = initialization_timeout
        self._owns_connection = collection is None
        self._connection_alias = f"candidates_{uuid4().hex}"
        self._closed = False
        self.collection: Collection
        if collection is not None:
            self.collection = collection
            self._validate_schema()
            self._ensure_index(timeout=self.initialization_timeout)
            self.collection.load(timeout=self.initialization_timeout)
        else:
            self._initialize()

    def _schema(self) -> CollectionSchema:
        return CollectionSchema(
            [
                FieldSchema(name, DataType.VARCHAR, max_length=maximum, is_primary=name == "id")
                for name, maximum in _VARCHAR_LIMITS.items()
            ]
            + [
                FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=self.dimension),
                FieldSchema("graph_revision", DataType.INT64),
            ],
            description=json.dumps(
                {
                    "schema_version": INDEX_SCHEMA_VERSION,
                    "embedding_model": self.embedding_model,
                    "embedding_fingerprint": self.embedding_fingerprint,
                },
                sort_keys=True,
            ),
            auto_id=False,
            enable_dynamic_field=False,
        )

    @property
    def schema_fingerprint(self) -> str:
        return digest(
            {
                "schema": self._schema().to_dict(),
                "index_type": self.index_type,
                "metric_type": self.metric_type,
            }
        )

    def _initialize(self) -> None:
        try:
            connections.connect(
                alias=self._connection_alias,
                host=self.host,
                port=self.port,
                timeout=self.initialization_timeout,
            )
            if utility.has_collection(
                self.collection_name,
                using=self._connection_alias,
                timeout=self.initialization_timeout,
            ):
                self.collection = Collection(
                    self.collection_name,
                    using=self._connection_alias,
                    timeout=self.initialization_timeout,
                )
            else:
                self.collection = Collection(
                    self.collection_name,
                    schema=self._schema(),
                    using=self._connection_alias,
                    consistency_level="Strong",
                    timeout=self.initialization_timeout,
                )
            self._validate_schema()
            self._ensure_index(timeout=self.initialization_timeout)
            self.collection.load(timeout=self.initialization_timeout)
        except BaseException:
            try:
                connections.disconnect(self._connection_alias)
            except MilvusException:
                logger.exception(
                    "Failed to disconnect Milvus after candidate initialization failed"
                )
            self._closed = True
            raise

    def _validate_schema(self) -> None:
        actual = self.collection.schema
        expected = self._schema()
        try:
            description = json.loads(actual.description)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Milvus candidate schema description is invalid") from exc
        if description != json.loads(expected.description):
            raise ValueError("Milvus candidate schema or embedding space is incompatible")
        if actual.auto_id or actual.enable_dynamic_field:
            raise ValueError(
                "Milvus candidate schema requires stable IDs and disabled dynamic fields"
            )
        fields = {field.name: field for field in actual.fields}
        if set(fields) != {field.name for field in expected.fields}:
            raise ValueError("Milvus candidate schema fields are incompatible")
        for field in expected.fields:
            current = fields[field.name]
            if current.dtype != field.dtype or current.is_primary != field.is_primary:
                raise ValueError(f"Milvus candidate schema field {field.name} is incompatible")
            for key, value in field.params.items():
                if str(current.params.get(key)) != str(value):
                    raise ValueError(
                        f"Milvus candidate schema field {field.name} {key} is incompatible"
                    )

    def _ensure_index(self, *, timeout: float | None = None) -> None:
        timeout = self.timeout if timeout is None else timeout
        if self.collection.has_index(timeout=timeout):
            index = self.collection.index(timeout=timeout)
            if (
                index.field_name != "embedding"
                or index.params.get("metric_type") != self.metric_type
                or index.params.get("index_type") != self.index_type
            ):
                raise ValueError("Milvus candidate index or similarity metric is incompatible")
            return
        self.collection.create_index(
            field_name="embedding",
            index_params={
                "index_type": self.index_type,
                "metric_type": self.metric_type,
                "params": {"M": 16, "efConstruction": 128},
            },
            timeout=timeout,
        )

    def _validate_scope(self, scope: IndexScope) -> IndexScope:
        scope = IndexScope.model_validate(scope.model_dump())
        if scope.embedding_fingerprint != self.embedding_fingerprint:
            raise ValueError("Candidate scope embedding fingerprint differs from the collection")
        if scope.index_schema_version != INDEX_SCHEMA_VERSION:
            raise ValueError("Candidate index schema version is incompatible")
        return scope

    def _record_scope(self, record: CatalogRecord) -> IndexScope:
        return self._validate_scope(
            IndexScope(
                domain_id=record.domain_id,
                ontology_version=record.ontology_version,
                ontology_fingerprint=record.ontology_fingerprint,
                kind=record.kind,
                index_schema_version=record.index_schema_version,
                embedding_fingerprint=self.embedding_fingerprint,
            )
        )

    def _vector(self, values: Sequence[float]) -> list[float]:
        if len(values) != self.dimension:
            raise ValueError(f"Embedding dimension must be {self.dimension}")
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
            raise ValueError("Embedding values must be numeric")
        vector = [float(value) for value in values]
        if any(not math.isfinite(value) or abs(value) > _MAX_FLOAT32 for value in vector):
            raise ValueError("Embedding values must be finite float32 values")
        if not any(vector):
            raise ValueError("COSINE embedding vector must have nonzero magnitude")
        scale = max(map(abs, vector))
        scaled = [value / scale for value in vector]
        norm = math.sqrt(sum(value * value for value in scaled))
        if math.isclose(scale * norm, 1.0, rel_tol=1e-6, abs_tol=1e-7):
            normalized = vector
        else:
            normalized = [value / norm for value in scaled]
        # Milvus stores float32; canonicalize once so read/reuse/write is idempotent.
        return [struct.unpack("!f", struct.pack("!f", value))[0] for value in normalized]

    def _scope_expression(self, scope: IndexScope) -> str:
        return " and ".join(
            f"{name} == {_literal(value)}"
            for name, value in {
                **scope.model_dump(),
                "embedding_model": self.embedding_model,
            }.items()
        )

    def _row(
        self, generation_id: str, candidate: CatalogRecord, vector: Sequence[float]
    ) -> dict[str, Any]:
        record = CatalogRecord.model_validate(candidate.model_dump())
        self._record_scope(record)
        if record.kind == "entity" and (
            record.graph_revision is None or record.graph_revision >= 2**63
        ):
            raise ValueError("Entity candidate graph revision must be a native Milvus int64")
        row = {name: getattr(record, name) for name in _RECORD_SCALARS}
        row.update(
            id=digest([generation_id, record.record_id, record.record_hash]),
            generation_id=generation_id,
            embedding_model=self.embedding_model,
            embedding_fingerprint=self.embedding_fingerprint,
            graph_revision=-1 if record.graph_revision is None else record.graph_revision,
            metadata=json.dumps(
                record.model_dump(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            embedding=self._vector(vector),
        )
        for name, maximum in _VARCHAR_LIMITS.items():
            if len(row[name].encode("utf-8")) > maximum:
                raise ValueError(f"Candidate {name} exceeds the Milvus byte limit")
        return row

    def _read_row(self, row: Mapping[str, Any]) -> CatalogRecord:
        generation_id = _generation_id(row["generation_id"])
        try:
            metadata = json.loads(row["metadata"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Candidate metadata is invalid JSON") from exc
        record = CatalogRecord.model_validate(metadata)
        for name in _RECORD_SCALARS:
            if row[name] != getattr(record, name):
                raise ValueError(f"Candidate metadata and scalar {name} disagree")
        scope = self._record_scope(record)
        if (
            row["embedding_model"] != self.embedding_model
            or row["embedding_fingerprint"] != scope.embedding_fingerprint
        ):
            raise ValueError("Candidate row belongs to another embedding space")
        if row["id"] != digest([generation_id, record.record_id, record.record_hash]):
            raise ValueError("Candidate row identity hash mismatch")
        if row["graph_revision"] != (
            -1 if record.graph_revision is None else record.graph_revision
        ):
            raise ValueError("Candidate graph revision metadata mismatch")
        if record.kind == "entity" and record.graph_revision is None:
            raise ValueError("Entity candidate requires a native graph revision")
        self._vector(row["embedding"])
        return record

    def _rows(self, expression: str) -> Generator[Mapping[str, Any], None, None]:
        iterator = self.collection.query_iterator(
            expr=expression,
            output_fields=_OUTPUT_FIELDS,
            batch_size=512,
            consistency_level="Strong",
            timeout=self.timeout,
        )
        try:
            while True:
                rows = iterator.next()
                if not rows:
                    break
                yield from rows
        finally:
            iterator.close()

    def upsert(
        self,
        generation_id: str,
        records: Sequence[CatalogRecord],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        generation_id = _generation_id(generation_id)
        if len(records) != len(vectors):
            raise ValueError("Candidate and embedding counts must match")
        if not records:
            return
        if len({record.record_id for record in records}) != len(records):
            raise ValueError("Duplicate candidate record identity")
        rows = [
            self._row(generation_id, record, vector)
            for record, vector in zip(records, vectors, strict=True)
        ]
        scope = self._record_scope(records[0])
        revision = records[0].graph_revision
        for record in records:
            scope.validate_record(record)
            if record.graph_revision != revision:
                raise ValueError("Candidate generation graph revision cannot change")
        expression = f"generation_id == {_literal(generation_id)}"
        previous = self.collection.query(
            expr=expression,
            output_fields=_OUTPUT_FIELDS,
            limit=1,
            consistency_level="Strong",
            timeout=self.timeout,
        )
        for row in previous:
            existing = self._read_row(row)
            scope.validate_record(existing)
            if existing.graph_revision != revision:
                raise ValueError("Candidate generation graph revision cannot change")
        expected = {record.record_id: record.record_hash for record in records}
        for start in range(0, len(records), 256):
            batch_ids = [record.record_id for record in records[start : start + 256]]
            with closing(
                self._rows(expression + f" and record_id in {_literal(batch_ids)}")
            ) as existing_rows:
                for row in existing_rows:
                    existing = self._read_row(row)
                    if expected[existing.record_id] != existing.record_hash:
                        raise ValueError(
                            "Candidate generation record identity cannot change content"
                        )
        result = self.collection.upsert(rows, timeout=self.timeout)
        if result.upsert_count != len(rows):
            raise RuntimeError("Milvus did not upsert the complete candidate batch")

    def reusable_vectors(
        self, scope: IndexScope, text_hashes: Sequence[str]
    ) -> dict[str, list[float]]:
        scope = self._validate_scope(scope)
        hashes = sorted(set(text_hashes))
        if any(_DIGEST.fullmatch(value) is None for value in hashes):
            raise ValueError("Candidate text hash must be a SHA-256 digest")
        vectors: dict[str, list[float]] = {}
        texts: dict[str, str] = {}
        for start in range(0, len(hashes), 256):
            batch = hashes[start : start + 256]
            expression = self._scope_expression(scope) + f" and text_hash in {_literal(batch)}"
            with closing(self._rows(expression)) as rows:
                for row in rows:
                    record = self._read_row(row)
                    scope.validate_record(record)
                    if record.text_hash not in batch:
                        raise ValueError(
                            "Milvus returned a candidate outside the requested text hashes"
                        )
                    vector = self._vector(row["embedding"])
                    if record.text_hash in vectors and (
                        vectors[record.text_hash] != vector
                        or texts[record.text_hash] != record.text
                    ):
                        raise ValueError(
                            "Ambiguous candidate text hash has conflicting vectors or text"
                        )
                    vectors[record.text_hash] = vector
                    texts[record.text_hash] = record.text
        return vectors

    def search(
        self,
        query_vector: Sequence[float],
        *,
        scope: IndexScope,
        generation_id: str,
        expected_types: Sequence[str],
        top_k: int,
    ) -> list[CandidateHit]:
        scope = self._validate_scope(scope)
        generation_id = _generation_id(generation_id)
        if not 0 <= top_k <= 1000:
            raise ValueError("Candidate top_k must be between zero and 1000")
        if not top_k:
            return []
        vector = self._vector(query_vector)
        expression = (
            self._scope_expression(scope) + f" and generation_id == {_literal(generation_id)}"
        )
        if expected_types:
            expression += f" and object_type in {_literal(sorted(set(expected_types)))}"
        results = self.collection.search(
            data=[vector],
            anns_field="embedding",
            param={"metric_type": self.metric_type, "params": {"ef": max(top_k, 64)}},
            expr=expression,
            limit=top_k,
            output_fields=_OUTPUT_FIELDS,
            consistency_level="Strong",
            timeout=self.timeout,
        )
        hits = []
        for matches in results:
            for hit in matches:
                row = {name: hit.entity.get(name) for name in _OUTPUT_FIELDS}
                record = self._read_row(row)
                scope.validate_record(record)
                if (
                    row["generation_id"] != generation_id
                    or expected_types
                    and record.object_type not in expected_types
                ):
                    raise ValueError(
                        "Milvus returned a candidate outside the requested generation or type"
                    )
                hits.append(
                    CandidateHit(
                        record=record,
                        scope=scope,
                        generation_id=generation_id,
                        vector_score=float(hit.score),
                    )
                )
        return hits

    def verify_generation(
        self, generation_id: str, *, expected_count: int, expected_checksum: str
    ) -> IndexVerification:
        generation_id = _generation_id(generation_id)
        if expected_count < 0:
            raise ValueError("Expected candidate count cannot be negative")
        self._validate_schema()
        self._ensure_index()
        records = []
        scope = None
        revision = None
        with closing(self._rows(f"generation_id == {_literal(generation_id)}")) as rows:
            for row in rows:
                record = self._read_row(row)
                if row["generation_id"] != generation_id:
                    raise ValueError("Milvus returned a candidate outside the requested generation")
                if scope is None:
                    scope = self._record_scope(record)
                    revision = record.graph_revision
                scope.validate_record(record)
                if record.graph_revision != revision:
                    raise ValueError("Candidate generation contains mixed graph revisions")
                records.append(record)
        checksum = catalog_checksum(records)
        return IndexVerification(
            valid=len(records) == expected_count and checksum == expected_checksum,
            count=len(records),
            checksum=checksum,
            schema_fingerprint=self.schema_fingerprint,
        )

    def delete_generation(self, generation_id: str) -> None:
        """The publication service verifies retirement before calling this internal operation."""
        self.collection.delete(
            expr=f"generation_id == {_literal(_generation_id(generation_id))}",
            timeout=self.timeout,
        )

    def close(self) -> None:
        if self._owns_connection and not self._closed:
            connections.disconnect(self._connection_alias)
            self._closed = True
