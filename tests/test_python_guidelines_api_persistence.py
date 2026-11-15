"""Offline regressions for API contracts and owned resource lifecycles."""

import asyncio
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from jose import jwt


def test_semantic_cache_preserves_zero_threshold_and_capacity():
    from gustobot.application.services.redis_cache import RedisSemanticCache

    cache = RedisSemanticCache(redis_client=Mock(), score_threshold=0.0, max_cache_size=0)
    assert cache.score_threshold == 0.0
    assert cache.max_cache_size == 0


def test_zero_history_limit_returns_no_messages():
    from gustobot.application.services.redis_cache import RedisConversationHistory

    from redis.asyncio import Redis

    redis = Mock(spec=Redis, lrange=AsyncMock(return_value=[b'{"content":"old"}']))
    history = RedisConversationHistory(redis_client=redis)
    assert asyncio.run(history.get_recent("session", limit=0)) == []
    redis.lrange.assert_not_awaited()


def test_token_zero_expiry_is_not_replaced(monkeypatch):
    from gustobot.infrastructure.core import security

    monkeypatch.setattr(security, "settings", SimpleNamespace(SECRET_KEY="test", ALGORITHM="HS256"))
    token = security.create_access_token({"sub": "test"}, expires_delta=timedelta(0))
    payload = jwt.decode(token, "test", algorithms=["HS256"], options={"verify_exp": False})
    assert abs(payload["exp"] - datetime.now(timezone.utc).timestamp()) < 3


@pytest.mark.parametrize(
    "endpoint,field,filename", [("file", "file", "data.txt"), ("image", "image", "pic.png")]
)
def test_upload_rejects_large_content_with_413(monkeypatch, tmp_path, endpoint, field, filename):
    from gustobot.interfaces.http.v1 import upload

    monkeypatch.setattr(upload, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(upload, "MAX_FILE_SIZE", 3)
    app = FastAPI()
    app.include_router(upload.router)

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(f"/{endpoint}", files={field: (filename, b"large")})

    assert asyncio.run(request()).status_code == 413
    assert not list(tmp_path.rglob("*.*"))


@pytest.mark.parametrize("filename", [None, "../data.txt", "..\\data.txt"])
def test_upload_rejects_missing_or_path_filenames(monkeypatch, tmp_path, filename):
    from gustobot.interfaces.http.v1 import upload

    monkeypatch.setattr(upload, "UPLOAD_DIR", tmp_path)
    file = UploadFile(io.BytesIO(b"small"), filename=filename)
    with pytest.raises(HTTPException) as error:
        asyncio.run(upload.upload_file(file))
    assert error.value.status_code == 400


def test_llm_missing_text_is_visible(monkeypatch):
    from gustobot.application.services.llm_client import LLMClient

    client = LLMClient(api_key="test")
    monkeypatch.setattr(
        client,
        "complete",
        AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
            )
        ),
    )
    try:
        with pytest.raises(ValueError, match="content|text"):
            asyncio.run(client.chat(system_prompt=None, user_message="hello"))
    finally:
        assert client._client is not None
        asyncio.run(client._client.close())


def test_lightrag_sse_close_releases_upstream(monkeypatch):
    from gustobot.interfaces.http import lightrag_router
    from gustobot.application.services.lightrag_service import LightRAGQueryRequest

    closed = []

    async def chunks():
        try:
            yield "first"
            yield "second"
        finally:
            closed.append(True)

    monkeypatch.setattr(
        lightrag_router,
        "get_lightrag_service",
        lambda: SimpleNamespace(query=AsyncMock(return_value=chunks())),
    )

    async def consume():
        response = await lightrag_router.query_lightrag_stream(LightRAGQueryRequest(query="hello"))
        iterator = response.body_iterator
        assert await iterator.__anext__() == "data: first\n\n"
        await iterator.aclose()

    asyncio.run(consume())
    assert closed == [True]


def test_missing_crud_delete_is_normal_not_found():
    from gustobot.infrastructure.persistence.crud.base import CRUDBase

    db = Mock()
    db.get.return_value = None
    db.query.return_value.get.return_value = None
    assert CRUDBase(Mock()).delete(db, id="missing") is None
    db.delete.assert_not_called()


def test_message_save_failure_rolls_back_and_propagates(monkeypatch):
    from gustobot.interfaces.http.v1 import chat

    db = Mock()
    monkeypatch.setattr(
        chat.chat_message,
        "get_latest_by_session",
        Mock(side_effect=RuntimeError("database failed")),
    )
    with pytest.raises(RuntimeError, match="database failed"):
        asyncio.run(chat.save_message(db, "session", "hello", is_user=True))
    db.rollback.assert_called_once()


def test_search_stream_close_releases_openai_response(monkeypatch):
    from gustobot.application.services.search_service import SearchService
    from openai import AsyncOpenAI

    closed = []

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.close()

        async def close(self):
            closed.append(True)

        def __aiter__(self):
            return self

        async def __anext__(self):
            return SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="chunk"))]
            )

    service = SearchService.__new__(SearchService)
    service.tools_description = "search"
    service.model = "offline"
    monkeypatch.setattr(
        service, "_call_with_tool", AsyncMock(return_value=SimpleNamespace(finish_reason="stop"))
    )
    service.client = Mock(
        spec=AsyncOpenAI,
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=Stream()))),
    )

    async def consume():
        stream = service.generate_stream("hello")
        assert "direct_answer" in await stream.__anext__()
        assert "chunk" in await stream.__anext__()
        await stream.aclose()

    asyncio.run(consume())
    assert closed == [True]
