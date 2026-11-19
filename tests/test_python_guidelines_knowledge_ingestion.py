"""Offline behavior coverage for ingestion contracts and resource ownership."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_embedding_empty_provider_vector_is_failure():
    from openai import OpenAI

    from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings

    embedder = OpenAICompatibleEmbeddings(model="test", api_key="test", request_timeout=1)
    embedder._client.close()
    embedder._client = Mock(
        spec=OpenAI,
        embeddings=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[])]),
        ),
    )
    with pytest.raises(ValueError, match="empty"):
        embedder.embed_query("question")


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
    store.index_type = "FLAT"
    store.dimension = 1
    store.embedding_model = "fixture"
    store.timeout = 1
    store.collection = SimpleNamespace(search=Mock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        store.search(
            [0.0],
            domain_id="recipes",
            ontology_version="1",
            source_versions={"source": "v1"},
            entity_ids=None,
            top_k=1,
        )


def test_search_zero_limit_does_not_make_network_request(monkeypatch):
    from gustobot.infrastructure.tools.search import SearchTool

    tool = SearchTool.__new__(SearchTool)
    tool.allow_network = True
    tool.default_results = 5
    assert tool.search("question", num_results=0) == []
