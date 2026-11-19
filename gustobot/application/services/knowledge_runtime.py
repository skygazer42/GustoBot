"""Application-owned clients, initialized only when their capability is used."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import RLock

from langchain_openai import ChatOpenAI
from loguru import logger

from gustobot.config import settings
from gustobot.config.domain import get_domain_definition

_runtime_lock = RLock()

_graph = None
_documents = None
_queries = None
_model: ChatOpenAI | None = None
_candidates = None
_build_candidates = None
_candidate_embeddings = None
_build_embeddings = None
_linker = None


def get_graph_store():
    global _graph
    with _runtime_lock:
        if _graph is None:
            from gustobot.infrastructure.knowledge.graph_store import Neo4jGraphStore

            if not settings.NEO4J_PASSWORD:
                raise RuntimeError("请配置 NEO4J_PASSWORD 后使用事实图")
            _graph = Neo4jGraphStore(
                get_domain_definition(),
                uri=settings.NEO4J_URI,
                user=settings.NEO4J_USER,
                password=settings.NEO4J_PASSWORD,
                database=settings.NEO4J_DATABASE,
            )
        return _graph


def published_versions():
    from gustobot.infrastructure.core.database import session_scope
    from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository

    with session_scope(commit=False) as session:
        domain = get_domain_definition()
        return KnowledgeRepository(session).published_versions(
            domain.id, ontology_version=domain.version
        )


def get_document_service():
    global _documents
    with _runtime_lock:
        if _documents is None:
            from gustobot.infrastructure.knowledge.knowledge_service import (
                KnowledgeService,
            )

            _documents = KnowledgeService(
                domain=get_domain_definition(), source_versions=published_versions
            )
        return _documents


def get_model() -> ChatOpenAI | None:
    global _model
    with _runtime_lock:
        if _model is None and settings.LLM_API_KEY:
            import httpx
            from pydantic import SecretStr

            from gustobot.infrastructure.knowledge.request_telemetry import (
                ProviderUsageCallback,
                record_async_http_request,
                record_sync_http_request,
            )

            sync_client = httpx.Client(
                timeout=90, event_hooks={"request": [record_sync_http_request]}
            )
            async_client = None
            try:
                async_client = httpx.AsyncClient(
                    timeout=90, event_hooks={"request": [record_async_http_request]}
                )
                _model = ChatOpenAI(
                    api_key=SecretStr(settings.LLM_API_KEY),
                    base_url=settings.LLM_BASE_URL,
                    model=settings.LLM_MODEL,
                    temperature=0,
                    timeout=90,
                    max_retries=0,
                    http_client=sync_client,
                    http_async_client=async_client,
                    callbacks=[ProviderUsageCallback()],
                    extra_body=settings.LLM_EXTRA_BODY,
                )
            except BaseException:
                try:
                    try:
                        if async_client is not None:
                            with ThreadPoolExecutor(max_workers=1) as closing:
                                closing.submit(asyncio.run, async_client.aclose()).result()
                    finally:
                        sync_client.close()
                # Cleanup must preserve the original model construction failure.
                except Exception as cleanup_error:  # noqa: BLE001
                    logger.error(
                        "Failed model transport cleanup: {}",
                        type(cleanup_error).__name__,
                    )
                raise
        return _model


def candidate_embedding_fingerprint() -> str:
    from gustobot.domain.linking import embedding_fingerprint

    if not settings.SEMANTIC_EMBEDDING_REVISION.strip():
        raise ValueError("Semantic candidate embedding revision must be explicitly configured")
    return embedding_fingerprint(
        provider=settings.EMBEDDING_PROVIDER,
        base_url=settings.EMBEDDING_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        revision=settings.SEMANTIC_EMBEDDING_REVISION,
        dimension=settings.EMBEDDING_DIMENSION,
    )


def get_candidate_store():
    global _candidates
    with _runtime_lock:
        if _candidates is None:
            from gustobot.infrastructure.knowledge.semantic_index import (
                SemanticCandidateStore,
            )

            _candidates = SemanticCandidateStore(
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
                dimension=settings.EMBEDDING_DIMENSION,
                embedding_model=settings.EMBEDDING_MODEL,
                embedding_fingerprint=candidate_embedding_fingerprint(),
                timeout=settings.SEMANTIC_ANN_TIMEOUT,
                initialization_timeout=settings.SEMANTIC_INITIALIZATION_TIMEOUT,
            )
        return _candidates


def get_build_candidate_store():
    global _build_candidates
    with _runtime_lock:
        if _build_candidates is None:
            from gustobot.infrastructure.knowledge.semantic_index import (
                SemanticCandidateStore,
            )

            _build_candidates = SemanticCandidateStore(
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
                dimension=settings.EMBEDDING_DIMENSION,
                embedding_model=settings.EMBEDDING_MODEL,
                embedding_fingerprint=candidate_embedding_fingerprint(),
                timeout=settings.SEMANTIC_BUILD_OPERATION_TIMEOUT,
                initialization_timeout=settings.SEMANTIC_INITIALIZATION_TIMEOUT,
            )
        return _build_candidates


def _new_candidate_embeddings(*, build: bool):
    from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings

    candidate_embedding_fingerprint()
    return OpenAICompatibleEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=(
            settings.EMBEDDING_API_KEY
            if settings.EMBEDDING_API_KEY is not None
            else settings.LLM_API_KEY
        ),
        base_url=settings.EMBEDDING_BASE_URL,
        dimension=settings.EMBEDDING_DIMENSION,
        max_batch_size=settings.EMBEDDING_BATCH_SIZE,
        request_timeout=(
            settings.BUILD_EMBEDDING_TIMEOUT if build else settings.SEMANTIC_EMBEDDING_TIMEOUT
        ),
        purpose="build" if build else "candidate",
        max_retries=0,
        space_fingerprint=candidate_embedding_fingerprint(),
    )


def get_candidate_embeddings():
    global _candidate_embeddings
    with _runtime_lock:
        if _candidate_embeddings is None:
            _candidate_embeddings = _new_candidate_embeddings(build=False)
        return _candidate_embeddings


def get_build_embeddings():
    global _build_embeddings
    with _runtime_lock:
        if _build_embeddings is None:
            _build_embeddings = _new_candidate_embeddings(build=True)
        return _build_embeddings


def semantic_publication(scope):
    from gustobot.infrastructure.core.database import session_scope
    from gustobot.infrastructure.persistence.crud.semantic_index import (
        SemanticIndexRepository,
    )

    with session_scope(commit=False) as session:
        return SemanticIndexRepository(session).publication_status(scope)


def create_semantic_indexing_service():
    from gustobot.application.services.semantic_indexing import SemanticIndexingService

    return SemanticIndexingService(
        get_domain_definition(),
        graph_store=get_graph_store,
        candidate_store=get_build_candidate_store,
        embedder=get_build_embeddings,
        embedding_fingerprint=candidate_embedding_fingerprint(),
    )


def get_entity_linker():
    global _linker
    if settings.SEMANTIC_LINKING_MODE == "off":
        return None
    with _runtime_lock:
        if _linker is None:
            from gustobot.application.services.entity_linking import (
                EntityLinkingService,
            )
            from gustobot.domain.linking import CandidateKind, IndexScope

            domain = get_domain_definition()
            if domain.semantic_model is None:
                raise ValueError("Semantic candidate linking requires a compiled formal ontology")
            fingerprint = candidate_embedding_fingerprint()
            kinds: tuple[CandidateKind, CandidateKind] = ("concept", "entity")
            scopes: dict[str, IndexScope] = {
                kind: IndexScope(
                    domain_id=domain.id,
                    ontology_version=domain.version,
                    ontology_fingerprint=domain.semantic_model.fingerprint,
                    embedding_fingerprint=fingerprint,
                    kind=kind,
                )
                for kind in kinds
            }
            _linker = EntityLinkingService(
                domain,
                graph_store=get_graph_store,
                candidate_store=get_candidate_store,
                embedder=get_candidate_embeddings,
                scopes=scopes,
                publication_provider=semantic_publication,
                mode=settings.SEMANTIC_LINKING_MODE,
                concept_top_k=settings.SEMANTIC_CONCEPT_TOP_K,
                entity_top_k=settings.SEMANTIC_ENTITY_TOP_K,
                family_limit=settings.SEMANTIC_FAMILY_LIMIT,
                retrieval_deadline=settings.SEMANTIC_RETRIEVAL_DEADLINE,
            )
        return _linker


def get_query_service():
    global _queries
    with _runtime_lock:
        if _queries is None:
            from gustobot.application.services.knowledge_query import (
                KnowledgeQueryService,
            )

            _queries = KnowledgeQueryService(
                get_domain_definition(),
                graph_store=get_graph_store,
                documents=get_document_service,
                model=get_model(),
                linker=get_entity_linker(),
                telemetry_instrumented=True,
            )
        return _queries


async def cleanup_runtime():
    global _build_candidates
    global _graph, _documents, _queries, _model, _candidates, _candidate_embeddings, _build_embeddings, _linker
    with _runtime_lock:
        graph, documents, model = _graph, _documents, _model
        clients = (
            _candidates,
            _build_candidates,
            _candidate_embeddings,
            _build_embeddings,
        )
        _graph = _documents = _queries = _model = None
        _candidates = _candidate_embeddings = _build_embeddings = _linker = None
        _build_candidates = None
    closing = [asyncio.to_thread(client.close) for client in clients if client is not None]
    if graph is not None:
        closing.append(graph.close())
    if documents is not None:
        closing.append(documents.close())
    if model is not None:
        closing.extend(
            [
                model.root_async_client.close(),
                asyncio.to_thread(model.root_client.close),
            ]
        )
    results = await asyncio.gather(*closing, return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        for error in errors[1:]:
            logger.error("Additional knowledge client close failure: {}", type(error).__name__)
        raise errors[0]
