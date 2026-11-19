"""HTTP chat keeps the same evidence and persistence in both response modes."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.application.services.knowledge_query import KnowledgeAnswer
from gustobot.infrastructure.core.database import Base, get_db
from gustobot.infrastructure.persistence.db.models import ChatMessage


@pytest.fixture
def chat_api(monkeypatch):
    from fastapi import FastAPI

    from gustobot.interfaces.http.v1 import chat

    database = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    try:
        Base.metadata.create_all(database)
        app = FastAPI()
        app.include_router(chat.router, prefix="/chat")

        def session():
            with Session(database) as db:
                yield db

        class Queries:
            def __init__(self):
                self.history = []

            async def answer(self, message, *, history=None):
                self.history.append(list(history))
                return KnowledgeAnswer(
                    message="来源记载糖为适量。",
                    sources=[{"backend": "neo4j", "source": "recipe.json"}],
                    metadata={"model_calls": 0},
                )

            async def stream(self, message, *, history=None):
                self.history.append(list(history))
                yield {"type": "message", "content": "来源记载"}
                yield {"type": "message", "content": "糖为适量。"}
                yield {
                    "type": "done",
                    "message": "来源记载糖为适量。",
                    "route": "knowledge-query",
                    "sources": [{"backend": "neo4j", "source": "recipe.json"}],
                    "metadata": {"model_calls": 0},
                }

        queries = Queries()
        monkeypatch.setattr(chat, "get_query_service", lambda: queries, raising=False)
        app.dependency_overrides[get_db] = session
        yield app, database, queries
    finally:
        database.dispose()


@pytest.mark.asyncio
async def test_nonstream_chat_preserves_frontend_contract_and_loads_persisted_history(chat_api):
    app, _database, queries = chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/chat/", json={"message": "佛跳墙加多少糖？"})
        assert first.status_code == 200
        payload = first.json()
        assert payload["route"] == "knowledge-query"
        assert payload["sources"][0]["source"] == "recipe.json"
        assert payload["message_id"] and payload["session_id"]
        second = await client.post(
            "/chat/", json={"message": "它需要炒多久？", "session_id": payload["session_id"]}
        )
        assert second.status_code == 200
        assert len(queries.history[1]) == 2
        cleared = await client.delete("/chat/session/" + payload["session_id"])
        assert cleared.status_code == 200
        await client.post(
            "/chat/", json={"message": "重新开始", "session_id": payload["session_id"]}
        )
        assert queries.history[-1] == []


@pytest.mark.asyncio
async def test_uploaded_image_asset_id_selects_image_analysis_directly(
    chat_api, monkeypatch, tmp_path
):
    from gustobot.application.services import multimodal
    from gustobot.infrastructure.persistence.db.models.knowledge import UploadedAsset
    from gustobot.interfaces.http.v1 import chat

    app, database, queries = chat_api
    path = tmp_path / "sample.png"
    path.write_bytes(b"fixture-image")
    with Session(database) as session:
        session.add(
            UploadedAsset(
                id="image-asset",
                original_name="sample.png",
                path=str(path),
                file_type=".png",
                size=path.stat().st_size,
            )
        )
        session.commit()
    calls = []

    async def analyze(message, *, action, path):
        calls.append((action, path))
        return KnowledgeAnswer(
            message="图片中的菜品", route="image-query", metadata={"model_calls": 1}
        )

    monkeypatch.setattr(chat, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(multimodal, "answer_image", analyze)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/chat/", json={"message": "看看这张图", "asset_id": "image-asset"}
        )
    assert response.status_code == 200
    assert response.json()["route"] == "image-query"
    assert calls == [("knowledge", path)]
    assert not queries.history


@pytest.mark.asyncio
async def test_stream_persists_the_exact_assistant_output_and_sources(chat_api):
    app, database, _queries = chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/chat/stream", json={"message": "佛跳墙加多少糖？"})
        assert response.status_code == 200
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert [item["content"] for item in events if item["type"] == "message"] == [
            "来源记载",
            "糖为适量。",
        ]
        assert events[-1]["type"] == "done"
        session_id = events[-1]["session_id"]
        history = await client.get("/chat/history/" + session_id)
        assert history.status_code == 200
        assert len(history.json()) == 2
    with Session(database) as db:
        messages = db.scalars(select(ChatMessage).order_by(ChatMessage.order_index)).all()
        assert messages[-1].content == "来源记载糖为适量。"
        metadata = messages[-1].message_metadata
        assert metadata is not None
        sources = metadata["sources"]
        assert isinstance(sources, list)
        assert sources[0]["source"] == "recipe.json"


@pytest.mark.asyncio
async def test_chat_attachment_cannot_read_an_arbitrary_server_file(chat_api, tmp_path):
    app, _, _ = chat_api
    secret = tmp_path / "private.txt"
    secret.write_text("not an uploaded asset", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/chat/", json={"message": "读取附件", "file_path": str(secret)}
        )
        assert response.status_code in {400, 404}


@pytest.mark.asyncio
async def test_cleared_session_rejects_a_late_reply_from_the_deleted_turn(chat_api):
    app, database, queries = chat_api
    from gustobot.infrastructure.persistence.db.models import ChatSession

    with Session(database) as db:
        db.add(ChatSession(id="clear-during-generation", user_id="default_user", title="new"))
        db.commit()
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow_answer(message, *, history=None):
        started.set()
        await finish.wait()
        return KnowledgeAnswer(message="迟到的旧上下文回答")

    queries.answer = slow_answer
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        pending = asyncio.create_task(
            client.post(
                "/chat/", json={"message": "旧问题", "session_id": "clear-during-generation"}
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 10)
            await client.delete("/chat/session/clear-during-generation")
            finish.set()
            response = await pending
            assert response.status_code == 409
            history = await client.get("/chat/history/clear-during-generation")
            assert history.json() == []
        finally:
            finish.set()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
