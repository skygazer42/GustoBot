"""Milvus document chunks with scalar provenance and scoped retrieval."""

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

_CHUNK_FIELDS = (
    "id",
    "domain_id",
    "source_id",
    "source_version",
    "ontology_version",
    "embedding_model",
    "chunk_index",
    "content",
)


def _literal(value: str | list[str]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _chunk_from_record(record: Mapping[str, Any]) -> "DocumentChunk":
    metadata = record["metadata"]
    return DocumentChunk.model_validate(
        {
            **{name: record[name] for name in _CHUNK_FIELDS},
            "uri": metadata["uri"],
            "entity_ids": metadata["entity_ids"],
        }
    )


class DocumentChunk(BaseModel):
    """Stored text chunk with source, ontology, and embedding identities."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=64)
    domain_id: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    source_version: str = Field(min_length=1, max_length=64)
    ontology_version: str = Field(min_length=1, max_length=64)
    embedding_model: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    uri: str | None = None
    entity_ids: list[str] = Field(default_factory=list)


class VectorHit(TypedDict):
    """A document chunk and its vector similarity score."""

    chunk: DocumentChunk
    score: float


class VectorStore:
    """Persist and retrieve document vectors with mandatory source scoping."""

    def __init__(
        self,
        collection_name: str = "gustobot_documents_v1",
        host: str = "localhost",
        port: int = 19530,
        dimension: int = 1536,
        index_type: str = "IVF_FLAT",
        metric_type: str = "IP",
        *,
        embedding_model: str = "text-embedding-3-small",
        collection: Collection | None = None,
        timeout: float = 30,
    ) -> None:
        if dimension <= 0 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Vector dimension and timeout must be finite and positive")
        if metric_type not in {"IP", "COSINE"}:
            raise ValueError("Document retrieval requires an IP or COSINE similarity metric")
        if not embedding_model.strip():
            raise ValueError("Embedding model is required")
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.dimension = dimension
        self.index_type = index_type
        self.metric_type = metric_type
        self.embedding_model = embedding_model
        self.timeout = timeout
        self._owns_connection = collection is None
        self._connection_alias = f"documents_{uuid4().hex}"
        self.collection: Collection
        if collection is not None:
            self.collection = collection
            self._validate_schema()
        else:
            self._initialize()

    def _schema(self) -> CollectionSchema:
        """Build the expected vector and metadata schema for document chunks."""
        return CollectionSchema(
            fields=[
                FieldSchema("id", DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=self.dimension),
                FieldSchema("domain_id", DataType.VARCHAR, max_length=256),
                FieldSchema("source_id", DataType.VARCHAR, max_length=1024),
                FieldSchema("source_version", DataType.VARCHAR, max_length=64),
                FieldSchema("ontology_version", DataType.VARCHAR, max_length=256),
                FieldSchema("embedding_model", DataType.VARCHAR, max_length=256),
                FieldSchema("chunk_index", DataType.INT64),
                FieldSchema("content", DataType.VARCHAR, max_length=65535),
                FieldSchema("metadata", DataType.JSON),
            ],
            description=json.dumps(
                {
                    "schema_version": "gustobot_documents_v1",
                    "embedding_model": self.embedding_model,
                },
                sort_keys=True,
            ),
            auto_id=False,
            enable_dynamic_field=False,
        )

    def _initialize(self) -> None:
        """Create the document collection if needed and validate its schema."""
        try:
            connections.connect(
                alias=self._connection_alias, host=self.host, port=self.port, timeout=self.timeout
            )
            if utility.has_collection(
                self.collection_name, using=self._connection_alias, timeout=self.timeout
            ):
                self.collection = Collection(self.collection_name, using=self._connection_alias)
            else:
                self.collection = Collection(
                    self.collection_name,
                    schema=self._schema(),
                    using=self._connection_alias,
                    consistency_level="Strong",
                )
            self._validate_schema()
            self._ensure_index()
            self.collection.load(timeout=self.timeout)
        except BaseException:
            try:
                connections.disconnect(self._connection_alias)
            # Disconnection preserves the initialization error.
            except Exception:  # noqa: BLE001
                logger.exception("Failed to disconnect Milvus after document initialization failed")
            raise

    def _ensure_index(self) -> None:
        """Create a missing document vector index or reject incompatible settings."""
        if self.collection.has_index(timeout=self.timeout):
            index = self.collection.index(timeout=self.timeout)
            if (
                index.field_name != "embedding"
                or index.params.get("metric_type") != self.metric_type
                or index.params.get("index_type") != self.index_type
            ):
                raise ValueError("Milvus document index or similarity metric is incompatible")
            return
        parameters: dict[str, int] = {}
        if self.index_type.startswith("IVF_"):
            parameters = {"nlist": 128}
        elif self.index_type == "HNSW":
            parameters = {"M": 16, "efConstruction": 128}
        self.collection.create_index(
            field_name="embedding",
            index_params={
                "index_type": self.index_type,
                "metric_type": self.metric_type,
                "params": parameters,
            },
            timeout=self.timeout,
        )

    def _validate_schema(self) -> None:
        """Reject a persisted document collection with incompatible fields."""
        expected = self._schema()
        try:
            description = json.loads(self.collection.schema.description)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Milvus document schema description is missing or invalid") from exc
        if description != json.loads(expected.description):
            raise ValueError("Milvus document schema or embedding model is incompatible")
        actual_fields = {field.name: field for field in self.collection.schema.fields}
        if set(actual_fields) != {field.name for field in expected.fields}:
            raise ValueError("Milvus document schema fields are incompatible")
        for field in expected.fields:
            actual = actual_fields[field.name]
            if actual.dtype != field.dtype or actual.is_primary != field.is_primary:
                raise ValueError(f"Milvus document schema field {field.name} is incompatible")
            for key, value in field.params.items():
                if str(actual.params.get(key)) != str(value):
                    raise ValueError(
                        f"Milvus document schema field {field.name} {key} is incompatible"
                    )
        if self.collection.schema.auto_id:
            raise ValueError("Milvus document schema requires stable application chunk IDs")

    def existing_ids(self, ids: Sequence[str]) -> set[str]:
        """Return stored chunk identifiers in bounded query batches."""
        existing: set[str] = set()
        for start in range(0, len(ids), 256):
            batch = list(ids[start : start + 256])
            rows = self.collection.query(
                expr="id in " + json.dumps(batch, ensure_ascii=False),
                output_fields=["id"],
                limit=len(batch),
                consistency_level="Strong",
                timeout=self.timeout,
            )
            existing.update(row["id"] for row in rows)
        return existing

    def delete_source(self, *, domain_id: str, source_id: str, versions: Sequence[str]) -> None:
        """Remove confirmed versions across ontologies, retaining every other source."""
        if not versions:
            raise ValueError("Source versions are required for document deletion")
        self.collection.delete(
            expr=(
                f"domain_id == {_literal(domain_id)} and source_id == {_literal(source_id)} "
                f"and source_version in {_literal(list(versions))}"
            ),
            timeout=self.timeout,
        )

    def read_chunk(
        self,
        chunk_id: str,
        *,
        domain_id: str,
        source_id: str,
        source_version: str,
        ontology_version: str,
    ) -> DocumentChunk | None:
        """Read a chunk only when its domain and source versions match."""
        scope = {
            "id": chunk_id,
            "domain_id": domain_id,
            "source_id": source_id,
            "source_version": source_version,
            "ontology_version": ontology_version,
            "embedding_model": self.embedding_model,
        }
        rows = self.collection.query(
            expr=" and ".join(f"{field} == {_literal(value)}" for field, value in scope.items()),
            output_fields=list(_CHUNK_FIELDS),
            limit=1,
            consistency_level="Strong",
            timeout=self.timeout,
        )
        if not rows:
            return None
        if len(rows) != 1 or any(rows[0].get(field) != value for field, value in scope.items()):
            raise ValueError("Milvus returned a chunk outside the requested scope")
        return DocumentChunk.model_validate(rows[0])

    def _validate_embedding(self, embedding: Sequence[float]) -> None:
        if len(embedding) != self.dimension:
            raise ValueError(f"Embedding dimension must be {self.dimension}")
        if not all(math.isfinite(value) for value in embedding):
            raise ValueError("Embedding values must be finite")

    def refresh_entity_links(
        self, chunks: Sequence[DocumentChunk], *, replace_entity_ids: bool = True
    ) -> None:
        """Replace explicit linkage using stored vectors; original source identity is immutable."""
        for start in range(0, len(chunks), 256):
            batch = chunks[start : start + 256]
            ids = [chunk.id for chunk in batch]
            records = self.collection.query(
                expr="id in " + json.dumps(ids, ensure_ascii=False),
                output_fields=[*_CHUNK_FIELDS, "metadata"],
                limit=len(batch),
                consistency_level="Strong",
                timeout=self.timeout,
            )
            existing = {record["id"]: _chunk_from_record(record) for record in records}
            if set(existing) != set(ids):
                raise RuntimeError("Existing document chunks disappeared during linkage refresh")
            changed = []
            for chunk in batch:
                previous = existing[chunk.id]
                if previous.model_dump(exclude={"entity_ids"}) != chunk.model_dump(
                    exclude={"entity_ids"}
                ):
                    raise ValueError(
                        "Existing chunk identity or URI cannot change during linkage refresh"
                    )
                if replace_entity_ids and previous.entity_ids != chunk.entity_ids:
                    changed.append(chunk)
            if not changed:
                continue
            changed_ids = [chunk.id for chunk in changed]
            stored = self.collection.query(
                expr="id in " + json.dumps(changed_ids, ensure_ascii=False),
                output_fields=["id", "embedding"],
                limit=len(changed),
                consistency_level="Strong",
                timeout=self.timeout,
            )
            vectors = {record["id"]: record["embedding"] for record in stored}
            if set(vectors) != set(changed_ids):
                raise RuntimeError("Stored embeddings disappeared during linkage refresh")
            self.upsert(changed, [vectors[chunk.id] for chunk in changed])

    def upsert(
        self, chunks: Sequence[DocumentChunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        """Write aligned chunk and embedding batches after validating dimensions."""
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts must match")
        if not chunks:
            return
        rows = []
        limits = {
            field.name: int(field.params["max_length"])
            for field in self._schema().fields
            if field.dtype == DataType.VARCHAR
        }
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self._validate_embedding(embedding)
            if chunk.embedding_model != self.embedding_model:
                raise ValueError("Chunk embedding model does not match the collection")
            row = chunk.model_dump(exclude={"uri", "entity_ids"})
            for field, maximum in limits.items():
                if len(row[field].encode("utf-8")) > maximum:
                    raise ValueError(f"Document chunk {field} exceeds the Milvus byte limit")
            row["embedding"] = list(embedding)
            row["metadata"] = {"uri": chunk.uri, "entity_ids": chunk.entity_ids}
            rows.append(row)
        result = self.collection.upsert(rows, timeout=self.timeout)
        if result.upsert_count != len(rows):
            raise RuntimeError("Milvus did not upsert the complete document batch")

    def search(
        self,
        embedding: Sequence[float],
        *,
        domain_id: str,
        ontology_version: str,
        source_versions: Mapping[str, str],
        entity_ids: Sequence[str] | None = None,
        top_k: int = 10,
    ) -> list[VectorHit]:
        """Search requested published source versions and optional entity links."""
        if top_k < 0 or top_k > 1000:
            raise ValueError("top_k must be between zero and 1000")
        if top_k == 0 or not source_versions:
            return []
        self._validate_embedding(embedding)

        versions = " or ".join(
            f"(source_id == {_literal(source)} and source_version == {_literal(version)})"
            for source, version in sorted(source_versions.items())
        )
        expression = (
            f"domain_id == {_literal(domain_id)} and ontology_version == {_literal(ontology_version)} "
            f"and embedding_model == {_literal(self.embedding_model)} and ({versions})"
        )
        if entity_ids:
            expression += (
                f' and JSON_CONTAINS_ANY(metadata["entity_ids"], {_literal(list(entity_ids))})'
            )
        parameters: dict[str, int] = {}
        if self.index_type.startswith("IVF_"):
            parameters = {"nprobe": 10}
        elif self.index_type == "HNSW":
            parameters = {"ef": max(top_k, 64)}
        result = self.collection.search(
            data=[list(embedding)],
            anns_field="embedding",
            param={"metric_type": self.metric_type, "params": parameters},
            limit=top_k,
            expr=expression,
            output_fields=[
                field.name for field in self._schema().fields if field.name != "embedding"
            ],
            consistency_level="Strong",
            timeout=self.timeout,
        )
        hits: list[VectorHit] = []
        for matches in result:
            for hit in matches:
                chunk = _chunk_from_record(
                    {name: hit.entity.get(name) for name in (*_CHUNK_FIELDS, "metadata")}
                )
                hits.append({"chunk": chunk, "score": float(hit.score)})
        return hits

    def get_collection_stats(self) -> dict[str, Any]:
        """Return collection dimensions and configured embedding/index metadata."""
        return {
            "name": self.collection_name,
            "document_count": self.collection.num_entities,
            "dimension": self.dimension,
            "embedding_model": self.embedding_model,
            "index_type": self.index_type,
            "metric_type": self.metric_type,
        }

    def close(self) -> None:
        """Disconnect the collection connection only when this store owns it."""
        if self._owns_connection:
            connections.disconnect(self._connection_alias)
