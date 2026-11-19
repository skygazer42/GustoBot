"""Offline behavior regressions from the independent Agent/RAG review."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest


@pytest.mark.asyncio
async def test_knowledge_reranker_fallback_uses_measured_vector_score(monkeypatch):
    module = importlib.import_module("gustobot.infrastructure.knowledge.knowledge_service")
    from gustobot.infrastructure.knowledge.vector_store import DocumentChunk

    chunks = [
        DocumentChunk(
            id=str(i),
            domain_id="recipes",
            source_id="manual",
            source_version="v1",
            ontology_version="1",
            embedding_model="fixture",
            chunk_index=i,
            content=text,
        )
        for i, text in enumerate(["vector match", "weak vector match", "low rerank score"])
    ]
    hits = [{"chunk": chunk, "score": score} for chunk, score in zip(chunks, [0.9, 0.1, 0.9])]

    async def rerank(question, documents, limit):
        return [
            dict(item, rerank_score=0.1) if item["content"] == "low rerank score" else item
            for item in documents
        ]

    service = module.KnowledgeService(
        domain=SimpleNamespace(id="recipes", version="1"),
        embedder=SimpleNamespace(embed_query=Mock(return_value=[1.0])),
        vector_store=SimpleNamespace(search=Mock(return_value=hits)),
        embedding_model="fixture",
        source_versions=lambda: {"manual": "v1"},
        reranker=SimpleNamespace(enabled=True, rerank=rerank),
    )
    monkeypatch.setattr(module.settings, "RERANK_MAX_CANDIDATES", 3)
    monkeypatch.setattr(module.settings, "KB_RERANK_SCORE_THRESHOLD", 0.5)
    result = await service.search(
        "recipe", top_k=3, similarity_threshold=0.5, filter_by_similarity=False
    )
    assert [item["content"] for item in result] == ["vector match"]


@pytest.mark.asyncio
@pytest.mark.parametrize("class_name", ["RedisSemanticCache", "RedisConversationHistory"])
@pytest.mark.parametrize("borrowed", [True, False])
async def test_redis_adapters_close_only_owned_clients(monkeypatch, class_name, borrowed):
    module = importlib.import_module("gustobot.application.services.redis_cache")
    client = MagicMock()
    client.__bool__.return_value = False
    client.aclose = AsyncMock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(module.Redis, "from_url", factory)

    adapter = getattr(module, class_name)(redis_client=client if borrowed else None)
    await adapter.close()

    if borrowed:
        factory.assert_not_called()
        client.aclose.assert_not_awaited()
    else:
        factory.assert_called_once()
        client.aclose.assert_awaited_once()
