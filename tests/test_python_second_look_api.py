"""Offline regressions found by the second API and ingestion review."""

import asyncio
import logging
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pytest
from openai import OpenAI


@pytest.fixture(params=["application", "ingestion"])
def embedding_call(request, monkeypatch):
    create = Mock()
    sdk = Mock(spec=OpenAI, embeddings=SimpleNamespace(create=create))
    if request.param == "application":
        from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings

        client = OpenAICompatibleEmbeddings.__new__(OpenAICompatibleEmbeddings)
        client._client = sdk
        client.model = "test"
        client.dimension = 1
        client.max_batch_size = 2
        client.request_timeout = 1
        return client.embed_documents, create
    else:
        monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
        from kb_service.clients.embedding import EmbeddingClient
        from kb_service.core.config import Config

        ingest_client = EmbeddingClient.__new__(EmbeddingClient)
        ingest_client.openai_client = sdk
        ingest_client.config = Config(embedding_model="test")
        return ingest_client._embed_openai, create


def test_embedding_batch_indices_keep_vectors_attached_to_input(embedding_call):
    embed, create = embedding_call

    def provider(**kwargs):
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[float(text)])
                for index, text in reversed(list(enumerate(kwargs["input"])))
            ]
        )

    create.side_effect = provider
    np.testing.assert_array_equal(embed(["1", "2", "3"]), [[1], [2], [3]])


@pytest.mark.parametrize("indices", [[0], [0, 0], [0, 2], [-1, 0]])
def test_embedding_batch_rejects_missing_duplicate_or_invalid_indices(embedding_call, indices):
    embed, create = embedding_call
    create.return_value = SimpleNamespace(
        data=[SimpleNamespace(index=index, embedding=[1.0]) for index in indices]
    )
    with pytest.raises((ValueError, RuntimeError), match="index|indices|count|number"):
        embed(["first", "second"])


def test_fused_reranking_keeps_candidates_without_a_provider_score(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.core.config import Config
    from kb_service.services.reranker import RerankerClient
    from kb_service.services.search import VectorSearcher

    searcher = VectorSearcher.__new__(VectorSearcher)
    searcher.config = Config(rerank_max_candidates=3, rerank_score_fusion_alpha=0.5)
    searcher.logger = logging.getLogger(__name__)
    searcher.rerank_client = Mock(
        spec=RerankerClient,
        rerank=Mock(return_value=[{"id": "b", "score": 1.0}, {"id": "a", "score": 0.0}]),
        zscore_normalize=RerankerClient.zscore_normalize,
    )
    candidates = [
        {"id": key, "content": key, "source_table": "recipes", "source_id": key, "similarity": 0.5}
        for key in "abcd"
    ]
    result = searcher._apply_reranker("question", candidates)
    assert [item["id"] for item in result] == ["b", "a", "c", "d"]
    assert result[1]["rerank_score"] == 0.0


def test_explicit_empty_user_identifier_keeps_session_filter(monkeypatch):
    from gustobot.interfaces.http.v1 import sessions

    filtered = Mock(return_value=[])
    unfiltered = Mock(return_value=["unrelated session"])
    monkeypatch.setattr(sessions.chat_session, "get_by_user", filtered)
    monkeypatch.setattr(sessions.chat_session, "get_all", unfiltered)
    db = Mock()
    assert sessions.get_sessions(db=db, user_id="", skip=0, limit=5, active_only=True) == []
    filtered.assert_called_once_with(db, user_id="", skip=0, limit=5, active_only=True)
    unfiltered.assert_not_called()


def test_semantic_cache_does_not_hit_a_vector_from_another_dimension(monkeypatch):
    from gustobot.application.services.redis_cache import RedisSemanticCache
    from redis.asyncio import Redis

    async def scan(_pattern):
        yield b"semantic:vec:old"

    async def get(key):
        return b"[1, 0]" if key == b"semantic:vec:old" else b"unrelated answer"

    redis = Mock(spec=Redis, scan_iter=scan, get=AsyncMock(side_effect=get))
    cache = RedisSemanticCache(redis_client=redis, score_threshold=0.5)
    monkeypatch.setattr(cache, "_get_embedding", AsyncMock(return_value=[1.0]))
    metadata = AsyncMock()
    monkeypatch.setattr(cache, "_update_metadata", metadata)
    assert asyncio.run(cache.lookup([{"role": "user", "content": "question"}])) is None
    metadata.assert_not_awaited()
    assert redis.get.await_count == 1


@pytest.mark.parametrize("stage", ["writer", "outputs"])
@pytest.mark.parametrize("close_error", [False, True])
def test_processor_initialization_closes_acquired_owners(monkeypatch, tmp_path, stage, close_error):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    monkeypatch.chdir(tmp_path)
    from kb_service.core.config import Config
    from kb_service.services import processor

    failure = OSError("initialization failed")
    llm = Mock(close=Mock(side_effect=RuntimeError("close failed") if close_error else None))
    writer = Mock(close=Mock(side_effect=RuntimeError("close failed") if close_error else None))
    handler = logging.NullHandler()
    close_handler = Mock(wraps=handler.close)
    monkeypatch.setattr(handler, "close", close_handler)
    monkeypatch.setattr(processor, "LLMClient", Mock(return_value=llm))
    monkeypatch.setattr(
        processor,
        "VectorStoreWriter",
        Mock(side_effect=failure) if stage == "writer" else Mock(return_value=writer),
    )

    def setup_logging(instance):
        instance.logger = logging.Logger("isolated processor")
        instance.logger.addHandler(handler)

    monkeypatch.setattr(processor.DataProcessor, "_setup_logging", setup_logging)
    monkeypatch.setattr(processor.DataProcessor, "_init_output_files", Mock(side_effect=failure))
    with pytest.raises(OSError) as raised:
        processor.DataProcessor(Config(use_llm=True))
    assert raised.value is failure
    llm.close.assert_called_once()
    if stage == "outputs":
        writer.close.assert_called_once()
        close_handler.assert_called_once()


def test_milvus_bootstrap_requires_real_ingestion_statistics():
    from scripts.init_kb_milvus import _ingest_chunk
    from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService

    service = Mock(spec=KnowledgeService, ingest_text=AsyncMock(return_value={}))
    with pytest.raises(KeyError, match="add_count"):
        asyncio.run(_ingest_chunk(service, "document", "source.txt", 1))


def test_lightrag_document_omits_optional_match_null_ingredients():
    from scripts.init_lightrag import format_recipe_document

    result = format_recipe_document(
        {
            "dish_name": "test",
            "ingredients": [{"name": None, "amount": None}, {"name": "salt", "amount": 0}],
        }
    )
    assert "None" not in result
    assert "- salt: 0" in result


def test_lightrag_insert_retains_explicit_partial_success(monkeypatch):
    from gustobot.application.services.lightrag_service import LightRAGService

    service = LightRAGService()
    service.rag = SimpleNamespace(
        ainsert=AsyncMock(side_effect=["track-first", ValueError("invalid")]),
        aget_docs_by_track_id=AsyncMock(
            return_value={"doc-first": SimpleNamespace(status="processed", error_msg=None)}
        ),
    )
    monkeypatch.setattr(service, "initialize", AsyncMock())
    result = asyncio.run(service.insert_documents(["first", "second"], batch_size=1))
    assert (result.total, result.success, result.failed) == (2, 1, 1)
    assert len(result.errors) == 1
    assert "2" in result.errors[0] and "invalid" in result.errors[0]


@pytest.mark.asyncio
async def test_lightrag_stats_reads_files_outside_event_loop(monkeypatch):
    from gustobot.interfaces.http import lightrag_router

    event_loop_thread = get_ident()
    reader_threads = []
    stats = {"working_dir": "test", "total_size_mb": 0, "files": {}, "initialized": False}

    def read_stats():
        reader_threads.append(get_ident())
        return stats

    monkeypatch.setattr(
        lightrag_router,
        "get_lightrag_service",
        Mock(return_value=SimpleNamespace(get_index_stats=read_stats)),
    )
    assert await lightrag_router.get_index_stats() == stats
    assert len(reader_threads) == 1
    assert reader_threads[0] != event_loop_thread


def test_message_save_preserves_query_error_when_rollback_fails(monkeypatch):
    from gustobot.interfaces.http.v1 import chat

    original = ValueError("message query failed")
    db = Mock(rollback=Mock(side_effect=RuntimeError("rollback failed")))
    monkeypatch.setattr(chat.chat_message, "get_latest_by_session", Mock(side_effect=original))

    with pytest.raises(ValueError) as raised:
        chat._save_message(db, "session", "question", True, None, None)
    assert raised.value is original
    db.rollback.assert_called_once()


@pytest.fixture
def recovery_processor(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.core.config import Config
    from kb_service.services import processor

    instance = processor.DataProcessor.__new__(processor.DataProcessor)
    instance.config = Config(use_llm=True)
    instance.logger = logging.getLogger(__name__)
    instance.vector_writer = Mock()
    instance.llm_client = Mock(generate=Mock(return_value="regenerated"))
    instance.prompt_manager = Mock(get_prompt=Mock(return_value=("system", "user")))
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(processor.psycopg2, "connect", Mock(return_value=connection))
    return instance, cursor


@pytest.mark.parametrize("metadata", [{"count": 0}, '{"count": 0}'])
def test_reprocess_uses_stored_json_object_without_losing_zero(recovery_processor, metadata):
    processor, cursor = recovery_processor
    cursor.fetchall.return_value = [("reports", "0", "old", "company", "0", metadata)]

    processor.reprocess_by_filter(source_table="reports")

    prompt_data = processor.prompt_manager.get_prompt.call_args.args[1]
    assert prompt_data == {"count": 0}
    assert processor.vector_writer.upsert.call_args.args[0][0]["rewritten_content"] == "regenerated"


@pytest.mark.parametrize("metadata", ["not JSON", "[]", None])
def test_reprocess_rejects_missing_or_invalid_metadata_before_generation(
    recovery_processor, metadata
):
    processor, cursor = recovery_processor
    cursor.fetchall.return_value = [("reports", "0", "old", "company", "0", metadata)]

    with pytest.raises(ValueError):
        processor.reprocess_by_filter(source_table="reports")
    processor.llm_client.generate.assert_not_called()
    processor.vector_writer.upsert.assert_not_called()


def test_specific_record_update_preserves_zero_identifier(recovery_processor):
    processor, _cursor = recovery_processor
    processor.update_specific_records(
        [{"source_table": "reports", "source_id": 0, "content": "answer"}]
    )

    items = processor.vector_writer.upsert.call_args.args[0]
    assert len(items) == 1
    assert items[0]["source_id"] == 0


@pytest.mark.parametrize("row", [{}, {"id": None}])
def test_configured_mysql_identifier_cannot_fall_back_to_row_index(monkeypatch, row):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.services.mysql_ingest import MySQLIngestor

    ingestor = MySQLIngestor.__new__(MySQLIngestor)
    with pytest.raises((KeyError, ValueError)):
        ingestor._extract_identifier(row, "id", 7)
    assert ingestor._extract_identifier({}, None, 7) == "7"
    assert ingestor._extract_identifier({"id": 0}, "id", 7) == "0"


def test_fixed_api_responses_publish_named_schemas(monkeypatch):
    from fastapi import FastAPI
    from gustobot.interfaces.http import knowledge_router, lightrag_router
    from gustobot.interfaces.http.v1 import chat, sessions

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.main import create_app

    app = FastAPI()
    app.include_router(knowledge_router.router)
    app.include_router(lightrag_router.router)
    app.include_router(chat.router, prefix="/chat")
    app.include_router(sessions.router, prefix="/sessions")
    paths = app.openapi()["paths"]
    routes = [
        ("/knowledge/recipes", "post", "201"),
        ("/knowledge/recipes/batch", "post", "201"),
        ("/knowledge/recipes/{recipe_id}", "delete", "200"),
        ("/knowledge/stats", "get", "200"),
        ("/knowledge/clear", "delete", "200"),
        ("/lightrag/stats", "get", "200"),
        ("/lightrag/test-modes", "post", "200"),
        ("/chat/session/{session_id}", "delete", "200"),
        ("/chat/routes", "get", "200"),
        ("/sessions/user/{user_id}/count", "get", "200"),
    ]
    for path, method, status in routes:
        schema = paths[path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert "$ref" in schema, path

    ingest_paths = create_app().openapi()["paths"]
    for path, method in [("/health", "get"), ("/api/search/hybrid", "post")]:
        schema = ingest_paths[path][method]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert "$ref" in schema, path


@pytest.fixture
def metadata_searcher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.core.config import Config
    from kb_service.services import search

    instance = search.VectorSearcher.__new__(search.VectorSearcher)
    instance.config = Config()
    instance.logger = logging.getLogger(__name__)
    instance.embedding_client = Mock(embed_texts=Mock(return_value=np.array([[0.2]])))
    instance.rerank_client = None
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.mogrify.return_value = b"SELECT"
    monkeypatch.setattr(search.psycopg2, "connect", Mock(return_value=connection))
    monkeypatch.setattr(search, "register_vector", Mock())
    return instance, cursor, connection


@pytest.mark.parametrize("metadata", ["not JSON", "", "[]", [], 0, False])
def test_search_rejects_invalid_stored_metadata(metadata_searcher, metadata):
    searcher, cursor, connection = metadata_searcher
    cursor.fetchall.return_value = [(1, "reports", "1", metadata, "answer", 0.9, 0.1)]

    with pytest.raises(ValueError):
        searcher.search_similar("question")
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [(None, {}), ({}, {}), ({"count": 0}, {"count": 0}), ('{"count": 0}', {"count": 0})],
)
def test_search_preserves_optional_and_object_metadata(metadata_searcher, metadata, expected):
    searcher, cursor, connection = metadata_searcher
    cursor.fetchall.return_value = [(1, "reports", "1", metadata, "answer", 0.9, 0.1)]

    results = searcher.search_similar("question")

    assert results[0]["metadata"] == expected
    connection.close.assert_called_once()


@pytest.mark.parametrize("field_name", ["company", "year", ""])
def test_explicit_optional_mysql_column_must_exist(monkeypatch, field_name):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.services.mysql_ingest import MySQLIngestor

    ingestor = MySQLIngestor.__new__(MySQLIngestor)
    with pytest.raises(KeyError):
        ingestor._extract_optional_field({}, field_name)
    assert ingestor._extract_optional_field({}, None) is None
    assert ingestor._extract_optional_field({field_name: None}, field_name) is None
    assert ingestor._extract_optional_field({field_name: ""}, field_name) is None
    assert ingestor._extract_optional_field({field_name: 0}, field_name) == "0"
