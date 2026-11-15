"""Offline behavior coverage for ingestion contracts and resource ownership."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_database_environment_defaults_are_values(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.core.config import DatabaseConfig

    for key in (
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
        "PGHOST",
        "PGPORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    assert DatabaseConfig.from_env().as_dict() == {
        "dbname": "vector_db",
        "user": "postgres",
        "password": "",
        "host": "localhost",
        "port": "5432",
    }


def test_embedding_empty_provider_vector_is_failure():
    from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings
    from openai import OpenAI

    embedder = OpenAICompatibleEmbeddings.__new__(OpenAICompatibleEmbeddings)
    embedder.model = "test"
    embedder.dimension = None
    embedder.max_batch_size = 64
    embedder.request_timeout = 1
    embedder._client = Mock(
        spec=OpenAI,
        embeddings=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[])]),
        ),
    )
    with pytest.raises(ValueError, match="empty"):
        embedder.embed_query("question")


def test_ingestion_json_conversion_handles_numpy_arrays(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    import numpy as np
    from kb_service.services.processor import DataProcessor

    processor = DataProcessor.__new__(DataProcessor)
    assert processor._convert_for_json(np.array([0, 1])) == [0, 1]


def test_knowledge_service_preserves_zero_overlap(monkeypatch):
    from gustobot.infrastructure.knowledge import knowledge_service

    monkeypatch.setattr(
        knowledge_service, "OpenAICompatibleEmbeddings", lambda **kwargs: SimpleNamespace()
    )
    service = knowledge_service.KnowledgeService(
        vector_store=Mock(spec=knowledge_service.VectorStore), chunk_overlap=0
    )
    assert service.splitter._chunk_overlap == 0


def test_knowledge_close_releases_owned_embedding_client(monkeypatch):
    from gustobot.infrastructure.knowledge import knowledge_service

    events = []
    monkeypatch.setattr(
        knowledge_service,
        "OpenAICompatibleEmbeddings",
        lambda **kwargs: SimpleNamespace(close=lambda: events.append("embedding")),
    )
    external_store = Mock(
        spec=knowledge_service.VectorStore, close=lambda: events.append("external-store")
    )
    service = knowledge_service.KnowledgeService(vector_store=external_store)
    asyncio.run(service.close())
    assert events == ["embedding"]


def test_knowledge_construction_failure_closes_embedding_client(monkeypatch):
    from gustobot.infrastructure.knowledge import knowledge_service

    events = []
    monkeypatch.setattr(
        knowledge_service,
        "OpenAICompatibleEmbeddings",
        lambda **kwargs: SimpleNamespace(close=lambda: events.append("embedding closed")),
    )

    def unavailable_store(**kwargs):
        raise OSError("vector store unavailable")

    monkeypatch.setattr(knowledge_service, "VectorStore", unavailable_store)
    with pytest.raises(OSError, match="vector store unavailable"):
        knowledge_service.KnowledgeService()
    assert events == ["embedding closed"]


def test_vector_store_search_failure_is_visible():
    from gustobot.infrastructure.knowledge.vector_store import VectorStore

    store = VectorStore.__new__(VectorStore)
    store.metric_type = "IP"
    store.collection = SimpleNamespace(search=Mock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        store.search([0.0])


def test_postgres_writer_closes_connection_and_rejects_truncated_batch(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.services import vector_store
    from kb_service.core.config import Config

    events = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("cursor closed")

        def execute(self, *args):
            pass

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("rollback" if args[0] is not None else "commit")

        def cursor(self):
            return Cursor()

        def commit(self):
            pass

        def close(self):
            events.append("connection closed")

    monkeypatch.setattr(vector_store.psycopg2, "connect", lambda **kwargs: Connection())
    monkeypatch.setattr(vector_store, "register_vector", lambda conn: None)
    monkeypatch.setattr(vector_store.VectorStoreWriter, "_ensure_table", lambda *args: None)
    writer = vector_store.VectorStoreWriter(
        Config(),
        embedding_client=Mock(
            spec=vector_store.EmbeddingClient, dimension=1, embed_texts=lambda texts: [[0.1]]
        ),
    )
    with pytest.raises(ValueError, match="count"):
        writer.upsert(
            [
                {"source_table": "recipes", "source_id": "0", "rewritten_content": "first"},
                {"source_table": "recipes", "source_id": "1", "rewritten_content": "second"},
            ]
        )
    assert events == ["cursor closed", "rollback", "connection closed"]


def test_custom_reranker_keeps_zero_score_and_limits_results(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.services import reranker
    from kb_service.core.config import Config
    import requests

    response = requests.Response()
    response.status_code = 200
    response._content = b'{"results":[{"index":0,"relevance_score":0.0}]}'
    monkeypatch.setattr(reranker.requests, "post", lambda *args, **kwargs: response)
    client = reranker.RerankerClient(
        Config(
            rerank_timeout=1,
            rerank_provider="custom",
            rerank_base_url="http://test",
            rerank_endpoint="/rerank",
            rerank_api_key=None,
            rerank_model=None,
            rerank_top_n=1,
        )
    )
    assert client.rerank("question", [{"id": "0", "content": "answer"}]) == [
        {"id": "0", "score": 0.0}
    ]


def test_search_zero_limit_does_not_make_network_request(monkeypatch):
    from gustobot.infrastructure.tools.search import SearchTool

    tool = SearchTool.__new__(SearchTool)
    tool.allow_network = True
    tool.default_results = 5
    assert tool.search("question", num_results=0) == []
