"""Deterministic document ingestion and retrieval of published source versions."""

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol

from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from gustobot.config import settings
from gustobot.config.domain import get_domain_definition
from gustobot.domain.knowledge import DomainDefinition, SourceDocument
from gustobot.infrastructure.core.resources import close_on_exit

from .embeddings import OpenAICompatibleEmbeddings
from .reranker import Reranker
from .vector_store import DocumentChunk, VectorHit, VectorStore


def source_version(text: str) -> str:
    """Hash exact raw source text so graph facts and document chunks share a version."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentIngestionResult(BaseModel):
    """Persisted document chunk identities and counts for one source version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    domain_id: str
    source_id: str
    version: str
    chunks: int = Field(ge=1)
    embedded: int = Field(ge=0)
    ids: list[str]


class DocumentVectors(Protocol):
    """Vector-store operations required by deterministic document ingestion."""

    def existing_ids(self, ids: Sequence[str]) -> set[str]:
        """Return the subset of chunk IDs that already exists."""
        ...

    def delete_source(self, *, domain_id: str, source_id: str, versions: Sequence[str]) -> None:
        """Delete only the confirmed versions of one domain source."""
        ...

    def read_chunk(
        self,
        chunk_id: str,
        *,
        domain_id: str,
        source_id: str,
        source_version: str,
        ontology_version: str,
    ) -> DocumentChunk | None:
        """Read a chunk only when all source and ontology identities match."""
        ...

    def upsert(
        self, chunks: Sequence[DocumentChunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        """Insert or replace chunk records and their vectors."""
        ...

    def refresh_entity_links(
        self, chunks: Sequence[DocumentChunk], *, replace_entity_ids: bool
    ) -> None:
        """Refresh linked entity IDs without changing source-version identity."""
        ...

    def search(
        self,
        embedding: Sequence[float],
        *,
        domain_id: str,
        ontology_version: str,
        source_versions: Mapping[str, str],
        entity_ids: Sequence[str] | None,
        top_k: int,
    ) -> list[VectorHit]:
        """Search only the requested domain, ontology, versions, and entities."""
        ...

    def close(self) -> None:
        """Release the vector-store client and its connections."""
        ...


class DocumentEmbedder(Protocol):
    """Embedding operations used for document batches and search queries."""

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per input document in the same order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Return the query vector in the configured document embedding space."""
        ...

    def close(self) -> None:
        """Release the embedding client's transport resources."""
        ...


class KnowledgeService:
    """Chunk, embed, publish, and retrieve documents within the active domain."""

    def __init__(
        self,
        *,
        domain: DomainDefinition | None = None,
        vector_store: DocumentVectors | None = None,
        embedder: DocumentEmbedder | None = None,
        embedding_model: str | None = None,
        reranker: Reranker | Literal[False] | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        source_versions: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        self.domain = get_domain_definition() if domain is None else domain
        self.embedding_model = (
            settings.EMBEDDING_MODEL if embedding_model is None else embedding_model
        )
        self.chunk_size = settings.KB_CHUNK_SIZE if chunk_size is None else chunk_size
        self.chunk_overlap = settings.KB_CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap
        if self.chunk_size <= 0 or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError(
                "chunk_size must be positive and chunk_overlap smaller than chunk_size"
            )
        if not self.embedding_model.strip():
            raise ValueError("Embedding model is required")
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
            strip_whitespace=False,
        )
        self.source_versions = source_versions
        self.reranker = None if reranker is False else Reranker() if reranker is None else reranker
        self._owns_embedder = embedder is None
        self._owns_vector_store = vector_store is None
        api_key = settings.EMBEDDING_API_KEY
        if api_key is None:
            api_key = settings.LLM_API_KEY
        fingerprint = None
        if settings.SEMANTIC_EMBEDDING_REVISION.strip():
            from gustobot.domain.linking import embedding_fingerprint

            fingerprint = embedding_fingerprint(
                provider=settings.EMBEDDING_PROVIDER,
                base_url=settings.EMBEDDING_BASE_URL,
                model=self.embedding_model,
                revision=settings.SEMANTIC_EMBEDDING_REVISION,
                dimension=settings.EMBEDDING_DIMENSION,
            )
        self.embedder: DocumentEmbedder = (
            OpenAICompatibleEmbeddings(
                model=self.embedding_model,
                api_key=api_key,
                base_url=settings.EMBEDDING_BASE_URL,
                dimension=settings.EMBEDDING_DIMENSION,
                max_batch_size=settings.EMBEDDING_BATCH_SIZE,
                request_timeout=settings.DOCUMENT_EMBEDDING_TIMEOUT,
                purpose="document",
                max_retries=0,
                space_fingerprint=fingerprint,
            )
            if embedder is None
            else embedder
        )
        try:
            self.vector_store: DocumentVectors = (
                VectorStore(
                    collection_name=settings.MILVUS_COLLECTION,
                    host=settings.MILVUS_HOST,
                    port=settings.MILVUS_PORT,
                    dimension=settings.EMBEDDING_DIMENSION,
                    embedding_model=self.embedding_model,
                    index_type=settings.MILVUS_INDEX_TYPE,
                    metric_type=settings.MILVUS_METRIC_TYPE,
                )
                if vector_store is None
                else vector_store
            )
        except BaseException:
            if self._owns_embedder:
                try:
                    self.embedder.close()
                # Cleanup preserves the initialization error.
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to close embedding client after initialization failed")
            raise

    def delete_source(self, source_id: str, versions: Sequence[str]) -> None:
        """Delete confirmed document vectors without accessing graph or upload storage."""
        self.vector_store.delete_source(
            domain_id=self.domain.id, source_id=source_id, versions=versions
        )

    async def ingest_source(
        self, source: SourceDocument, *, entity_ids: Sequence[str] | None = None
    ) -> DocumentIngestionResult:
        """Idempotently index one exact source version and its optional entity links."""
        if not source.text.strip():
            raise ValueError("Source text must not be empty")
        version = source_version(source.text)
        contents = await asyncio.to_thread(self.splitter.split_text, source.text)
        entities = [] if entity_ids is None else list(dict.fromkeys(entity_ids))
        chunks = []
        for index, content in enumerate(contents):
            # 块身份包含内容版本、本体和嵌入模型，避免不同版本或向量空间互相覆盖。
            identity = json.dumps(
                [
                    self.domain.id,
                    source.id,
                    version,
                    self.domain.version,
                    self.embedding_model,
                    index,
                    content,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            chunks.append(
                DocumentChunk(
                    id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    domain_id=self.domain.id,
                    source_id=source.id,
                    source_version=version,
                    ontology_version=self.domain.version,
                    embedding_model=self.embedding_model,
                    chunk_index=index,
                    content=content,
                    uri=source.uri,
                    entity_ids=entities,
                )
            )
        existing = await asyncio.to_thread(
            self.vector_store.existing_ids, [chunk.id for chunk in chunks]
        )
        pending = [chunk for chunk in chunks if chunk.id not in existing]
        previous = [chunk for chunk in chunks if chunk.id in existing]
        # 重复导入只刷新实体关联；仅为缺失的块生成向量，避免重复支付嵌入费用。
        if previous:
            await asyncio.to_thread(
                self.vector_store.refresh_entity_links,
                previous,
                replace_entity_ids=entity_ids is not None,
            )
        if pending:
            embeddings = await asyncio.to_thread(
                self.embedder.embed_documents, [chunk.content for chunk in pending]
            )
            if len(embeddings) != len(pending):
                raise ValueError("Chunk and embedding counts must match")
            await asyncio.to_thread(self.vector_store.upsert, pending, embeddings)
        return DocumentIngestionResult(
            domain_id=self.domain.id,
            source_id=source.id,
            version=version,
            chunks=len(chunks),
            embedded=len(pending),
            ids=[chunk.id for chunk in chunks],
        )

    async def ingest_text(
        self, text: str, *, metadata: dict[str, Any] | None = None
    ) -> DocumentIngestionResult:
        """Build a source record from text metadata and index it."""
        values = {} if metadata is None else metadata
        source_id = values.get("source_id", source_version(text))
        source = SourceDocument(id=source_id, text=text, uri=values.get("uri"))
        return await self.ingest_source(source, entity_ids=values.get("entity_ids"))

    def read_chunk(
        self, chunk_id: str, *, source_id: str, source_version: str, ontology_version: str
    ) -> DocumentChunk | None:
        """Read a chunk scoped to this domain and the exact requested version."""
        return self.vector_store.read_chunk(
            chunk_id,
            domain_id=self.domain.id,
            source_id=source_id,
            source_version=source_version,
            ontology_version=ontology_version,
        )

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        entity_ids: Sequence[str] | None = None,
        similarity_threshold: float | None = None,
        filter_by_similarity: bool = True,
    ) -> list[dict[str, Any]]:
        """Search published source versions and return ranked source-aware passages."""
        limit = settings.KB_TOP_K if top_k is None else top_k
        if limit < 0 or limit > 1000:
            raise ValueError("top_k must be between zero and 1000")
        if limit == 0 or not query.strip():
            return []
        if self.source_versions is None:
            raise ValueError("A published source_versions provider is required for document search")
        # 检索范围由发布元数据决定，未发布、失败或已撤回的来源不能进入回答。
        versions = dict(await asyncio.to_thread(self.source_versions))
        if not versions:
            return []
        recall = limit
        if self.reranker is not None and self.reranker.enabled:
            recall = max(limit, settings.RERANK_MAX_CANDIDATES)
        embedding = await asyncio.to_thread(self.embedder.embed_query, query)
        hits = await asyncio.to_thread(
            self.vector_store.search,
            embedding,
            domain_id=self.domain.id,
            ontology_version=self.domain.version,
            source_versions=versions,
            entity_ids=entity_ids,
            top_k=recall,
        )
        candidates: list[dict[str, Any]] = []
        threshold = (
            settings.KB_SIMILARITY_THRESHOLD
            if similarity_threshold is None
            else similarity_threshold
        )
        for hit in hits:
            chunk = hit["chunk"]
            if (
                chunk.domain_id != self.domain.id
                or chunk.ontology_version != self.domain.version
                or versions.get(chunk.source_id) != chunk.source_version
                or chunk.embedding_model != self.embedding_model
            ):
                raise ValueError(
                    "Document search returned a chunk outside the published source scope"
                )
            if filter_by_similarity and hit["score"] < threshold:
                continue
            candidates.append(
                {
                    "id": chunk.id,
                    "content": chunk.content,
                    "score": hit["score"],
                    "metadata": chunk.model_dump(exclude={"content"}),
                }
            )
        if candidates and self.reranker is not None and self.reranker.enabled:
            candidates = await self.reranker.rerank(query, candidates, limit)
            filtered = []
            for candidate in candidates:
                score = candidate.get("rerank_score")
                # 重排未返回分数时沿用向量阈值，不能把“未评分”误当作零分。
                if score is not None:
                    if score < settings.KB_RERANK_SCORE_THRESHOLD:
                        continue
                elif candidate["score"] < threshold:
                    continue
                filtered.append(candidate)
            candidates = filtered
        return candidates[:limit]

    async def close(self) -> None:
        """Close only the vector and embedding clients owned by this service."""

        async def close_embedder() -> None:
            """Close the embedder only when the knowledge service created it."""
            if self._owns_embedder:
                await asyncio.to_thread(self.embedder.close)

        async with close_on_exit(close_embedder):
            if self._owns_vector_store:
                await asyncio.to_thread(self.vector_store.close)

    @staticmethod
    def _format_recipe_document(recipe: dict[str, Any]) -> str:
        """Render recipe fields as a stable text passage for document retrieval."""
        parts: list[str] = []
        name = recipe.get("name")
        if name:
            parts.append(f"菜名：{name}")

        category = recipe.get("category")
        if category:
            parts.append(f"分类：{category}")

        difficulty = recipe.get("difficulty")
        if difficulty:
            parts.append(f"难度：{difficulty}")

        time_cost = recipe.get("time")
        if time_cost is None:
            time_cost = recipe.get("cook_time")
        if time_cost is not None and time_cost != "":
            parts.append(f"耗时：{time_cost}")

        ingredients = recipe.get("ingredients")
        if ingredients is None:
            ingredients = recipe.get("ingredient_list")
        if ingredients:
            if isinstance(ingredients, list):
                formatted = "、".join(str(item) for item in ingredients)
            else:
                formatted = str(ingredients)
            parts.append(f"食材：{formatted}")

        steps = recipe.get("steps")
        if steps:
            if isinstance(steps, list):
                step_lines = [f"步骤{idx + 1}：{step}" for idx, step in enumerate(steps)]
                parts.extend(step_lines)
            else:
                parts.append(f"步骤：{steps}")

        tips = recipe.get("tips")
        if tips:
            parts.append(f"小贴士：{tips}")

        nutrition = recipe.get("nutrition")
        if nutrition:
            if isinstance(nutrition, dict):
                nutritions = [f"{k}: {v}" for k, v in nutrition.items()]
                parts.append("营养：" + "、".join(nutritions))
            else:
                parts.append(f"营养：{nutrition}")

        return "\n".join(parts)
