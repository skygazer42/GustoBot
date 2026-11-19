"""Offline regressions found by the second API and ingestion review."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from openai import OpenAI


@pytest.fixture
def embedding_call():
    from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings

    create = Mock()
    sdk = Mock(spec=OpenAI, embeddings=SimpleNamespace(create=create))
    client = OpenAICompatibleEmbeddings(
        model="test",
        api_key="test",
        dimension=1,
        max_batch_size=2,
        request_timeout=1,
    )
    client._client.close()
    client._client = sdk
    return client.embed_documents, create


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
    assert embed(["1", "2", "3"]) == [[1], [2], [3]]


@pytest.mark.parametrize("indices", [[0], [0, 0], [0, 2], [-1, 0]])
def test_embedding_batch_rejects_missing_duplicate_or_invalid_indices(embedding_call, indices):
    embed, create = embedding_call
    create.return_value = SimpleNamespace(
        data=[SimpleNamespace(index=index, embedding=[1.0]) for index in indices]
    )
    with pytest.raises((ValueError, RuntimeError), match="index|indices|count|number"):
        embed(["first", "second"])


def test_explicit_empty_user_identifier_keeps_session_filter(monkeypatch):
    from gustobot.interfaces.http.models.session import SessionListQuery
    from gustobot.interfaces.http.v1 import sessions

    filtered = Mock(return_value=[])
    unfiltered = Mock(return_value=["unrelated session"])
    monkeypatch.setattr(sessions.chat_session, "get_by_user", filtered)
    monkeypatch.setattr(sessions.chat_session, "get_all", unfiltered)
    db = Mock()
    assert (
        sessions.get_sessions(
            SessionListQuery(user_id="", skip=0, limit=5, active_only=True), db=db
        )
        == []
    )
    filtered.assert_called_once_with(db, user_id="", skip=0, limit=5, active_only=True)
    unfiltered.assert_not_called()


def test_semantic_cache_does_not_hit_a_vector_from_another_dimension(monkeypatch):
    from redis.asyncio import Redis

    from gustobot.application.services.redis_cache import RedisSemanticCache

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


def test_message_save_preserves_query_error_when_rollback_fails(monkeypatch):
    from gustobot.interfaces.http.v1 import chat

    original = ValueError("message query failed")
    db = Mock(rollback=Mock(side_effect=RuntimeError("rollback failed")))
    db.scalar = Mock(side_effect=original)

    with pytest.raises(ValueError) as raised:
        chat._save_message(db, "session", "question", True, None, None)
    assert raised.value is original
    db.rollback.assert_called_once()


def test_fixed_api_responses_publish_named_schemas():
    from fastapi import FastAPI

    from gustobot.interfaces.http import knowledge_router, ontology_router
    from gustobot.interfaces.http.v1 import chat, sessions

    app = FastAPI()
    app.include_router(knowledge_router.router)
    app.include_router(ontology_router.router)
    app.include_router(chat.router, prefix="/chat")
    app.include_router(sessions.router, prefix="/sessions")
    paths = app.openapi()["paths"]
    routes = [
        ("/knowledge/recipes", "post", "201"),
        ("/knowledge/recipes/batch", "post", "201"),
        ("/ontology/domain", "get", "200"),
        ("/ontology/facts", "post", "200"),
        ("/chat/session/{session_id}", "delete", "200"),
        ("/chat/routes", "get", "200"),
        ("/sessions/user/{user_id}/count", "get", "200"),
    ]
    for path, method, status in routes:
        schema = paths[path][method]["responses"][status]["content"]["application/json"]["schema"]
        if path == "/knowledge/recipes/batch":
            assert schema["type"] == "array"
            assert "$ref" in schema["items"]
        else:
            assert "$ref" in schema, path
