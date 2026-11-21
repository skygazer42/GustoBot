"""Admin conversation inspection reads persisted sessions without changing them."""

from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.config import settings
from gustobot.infrastructure.core.database import Base, get_db
from gustobot.infrastructure.persistence.db.models import ChatMessage, ChatSession
from gustobot.main import application

CONVERSATIONS = "/api/v1/admin/conversations"


@pytest_asyncio.fixture
async def conversation_api(monkeypatch):
    database = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(database)
    monkeypatch.setattr(settings, "GUSTOBOT_ADMIN_PASSWORD", None)
    timestamp = datetime(2026, 11, 20, 8, tzinfo=timezone.utc)
    with Session(database) as db:
        db.add_all(
            [
                ChatSession(
                    id="session-a",
                    title="设备维护 %_",
                    user_id="operator-a",
                    created_at=timestamp,
                    updated_at=timestamp,
                    is_active=True,
                ),
                ChatSession(
                    id="session-b",
                    title="工艺核对",
                    user_id="operator-b",
                    created_at=timestamp,
                    updated_at=timestamp,
                    is_active=True,
                ),
                ChatSession(
                    id="session-c",
                    title="空会话",
                    user_id=None,
                    created_at=datetime(2026, 11, 19, 8),
                    updated_at=None,
                    is_active=False,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                ChatMessage(
                    session_id="session-a",
                    message_type="user_query",
                    content="温度是0°C吗？",
                    order_index=0,
                    created_at=timestamp,
                ),
                ChatMessage(
                    session_id="session-a",
                    message_type="agent_response",
                    content="原文记录为0°C。" + "完整证据" * 60,
                    order_index=1,
                    message_metadata={"sources": [{"name": "维护记录.txt"}], "model_calls": 0},
                    created_at=timestamp,
                ),
                ChatMessage(
                    session_id="session-b",
                    message_type="user_query",
                    content="核对检修周期",
                    order_index=0,
                    created_at=timestamp,
                ),
                ChatMessage(
                    session_id="session-b",
                    message_type="agent_response",
                    content="检修周期未明确记录。",
                    order_index=0,
                    created_at=timestamp,
                ),
            ]
        )
        db.commit()
        db.execute(update(ChatSession).where(ChatSession.id == "session-c").values(updated_at=None))
        db.commit()

    def session():
        with Session(database) as db:
            yield db

    application.dependency_overrides[get_db] = session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            yield client, database
    finally:
        application.dependency_overrides.pop(get_db, None)
        database.dispose()


@pytest.mark.asyncio
async def test_conversation_list_is_paginated_with_counts_and_latest_preview(conversation_api):
    client, database = conversation_api
    statements = []

    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(database, "before_cursor_execute", record_statement)
    try:
        response = await client.get(CONVERSATIONS, params={"limit": 1, "offset": 1})
    finally:
        event.remove(database, "before_cursor_execute", record_statement)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    page = response.json()
    assert (page["total"], page["offset"], page["limit"]) == (3, 1, 1)
    item = page["items"][0]
    assert item["id"] == "session-a"
    assert item["message_count"] == 2
    assert len(item["last_message_preview"]) == 160
    assert item["last_message_preview"].startswith("原文记录为0°C。")
    assert len(statements) == 2
    with Session(database) as db:
        assert db.scalar(select(func.count(ChatMessage.id))) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"q": "0°C"}, ["session-a"]),
        ({"q": "operator-b"}, ["session-b"]),
        ({"q": "%_"}, ["session-a"]),
        ({"q": "不存在"}, []),
        ({"state": "deleted"}, ["session-c"]),
        ({"state": "active"}, ["session-b", "session-a"]),
        ({"offset": 99}, []),
    ],
)
async def test_conversation_search_and_status_filters(conversation_api, query, expected):
    client, _database = conversation_api
    response = await client.get(CONVERSATIONS, params=query)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == expected
    if query == {"state": "deleted"}:
        item = response.json()["items"][0]
        assert item["message_count"] == 0
        assert item["last_message_preview"] is None
        assert item["user_id"] is None


@pytest.mark.asyncio
async def test_messages_keep_full_content_metadata_and_chronological_pagination(conversation_api):
    client, _database = conversation_api
    response = await client.get(
        f"{CONVERSATIONS}/session-a/messages", params={"offset": 1, "limit": 1}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    page = response.json()
    assert page["session"]["id"] == "session-a"
    assert page["total"] == page["session"]["message_count"] == 2
    assert page["offset"] == page["limit"] == 1
    message = page["items"][0]
    assert message["message_type"] == "agent_response"
    assert message["content"] == "原文记录为0°C。" + "完整证据" * 60
    assert message["message_metadata"] == {"sources": [{"name": "维护记录.txt"}], "model_calls": 0}
    assert message["order_index"] == 1
    tied = await client.get(f"{CONVERSATIONS}/session-b/messages")
    assert [item["message_type"] for item in tied.json()["items"]] == [
        "user_query",
        "agent_response",
    ]


@pytest.mark.asyncio
async def test_missing_conversation_and_empty_conversation_are_distinct(conversation_api):
    client, _database = conversation_api
    missing = await client.get(f"{CONVERSATIONS}/missing/messages")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"
    empty = await client.get(f"{CONVERSATIONS}/session-c/messages")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
    assert empty.json()["session"]["is_active"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 201}, {"state": "unknown"}]
)
async def test_conversation_query_bounds_are_validated(conversation_api, query):
    client, _database = conversation_api
    assert (await client.get(CONVERSATIONS, params=query)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_message_query_bounds_are_validated(conversation_api, query):
    client, _database = conversation_api
    assert (
        await client.get(f"{CONVERSATIONS}/session-a/messages", params=query)
    ).status_code == 422


@pytest.mark.asyncio
async def test_signed_in_administrator_can_read_conversations(conversation_api, monkeypatch):
    client, _database = conversation_api
    monkeypatch.setattr(
        settings, "GUSTOBOT_ADMIN_PASSWORD", SecretStr("conversation-test-password")
    )
    monkeypatch.setattr(settings, "SECRET_KEY", "independent-conversation-signing-key-for-tests")
    assert (await client.get(CONVERSATIONS)).status_code == 401
    login = await client.post(
        "/api/v1/admin/session", json={"password": "conversation-test-password"}
    )
    assert login.status_code == 204
    assert (await client.get(CONVERSATIONS)).status_code == 200
    detail = await client.get(f"{CONVERSATIONS}/session-a/messages")
    assert detail.status_code == 200
    assert detail.json()["session"]["id"] == "session-a"
    assert (await client.get("/api/v1/sessions/")).status_code == 200
    assert (await client.get("/api/v1/chat/history/session-a")).status_code == 200
