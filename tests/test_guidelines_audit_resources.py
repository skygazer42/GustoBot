"""Audit regressions for test-resource ownership and current diagnostic behavior."""

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest


def test_chat_fixture_disposes_engine_when_schema_setup_fails(monkeypatch):
    from tests import test_chat_knowledge as fixture_module

    engine = SimpleNamespace(dispose=Mock())
    failure = RuntimeError("schema setup failed")
    monkeypatch.setattr(fixture_module, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(fixture_module.Base.metadata, "create_all", Mock(side_effect=failure))

    fixture = fixture_module.chat_api.__wrapped__(monkeypatch)
    with pytest.raises(RuntimeError) as raised:
        next(fixture)
    assert raised.value is failure
    engine.dispose.assert_called_once_with()


@pytest.mark.asyncio
async def test_startup_test_disposes_engine_when_migration_setup_fails(monkeypatch):
    import sqlalchemy

    import migrations
    from tests import test_main_knowledge

    engine = SimpleNamespace(dispose=Mock())
    failure = RuntimeError("migration setup failed")
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(migrations, "migrate_database", Mock(side_effect=failure))

    with pytest.raises(RuntimeError) as raised:
        await test_main_knowledge.test_startup_checks_migration_revision_instead_of_creating_tables(
            monkeypatch
        )
    assert raised.value is failure
    engine.dispose.assert_called_once_with()


def test_provider_fixture_closes_its_socket_when_the_consumer_fails():
    from tests import test_knowledge_runtime

    fixture = test_knowledge_runtime.chat_provider_server.__wrapped__()
    server = next(fixture)
    try:
        with pytest.raises(RuntimeError, match="consumer cleanup failed"):
            fixture.throw(RuntimeError("consumer cleanup failed"))
        assert server.fileno() == -1
    finally:
        fixture.close()


@pytest.mark.parametrize("backend", ["sqlite", "mysql"])
def test_index_fixture_registers_engine_cleanup_before_schema_setup(monkeypatch, backend):
    from tests import test_semantic_indexing as fixture_module

    finalizers: list[Callable[[], None]] = []
    request = SimpleNamespace(param=backend, addfinalizer=finalizers.append)
    engine = SimpleNamespace(dispose=Mock())
    failure = RuntimeError("index schema setup failed")
    if backend == "mysql":
        monkeypatch.setenv("GUSTOBOT_TEST_MYSQL_URL", "isolated-fixture")
        monkeypatch.setattr(fixture_module, "create_database_engine", lambda *args: engine)
        monkeypatch.setattr(fixture_module, "migrate_database", Mock(side_effect=failure))
    else:
        monkeypatch.setattr(fixture_module, "create_engine", lambda *args, **kwargs: engine)
        monkeypatch.setattr(fixture_module.Base.metadata, "create_all", Mock(side_effect=failure))
    fixture = fixture_module.setup.__wrapped__(request)
    try:
        with pytest.raises(RuntimeError) as raised:
            next(fixture)
        assert raised.value is failure
    finally:
        for finalizer in reversed(finalizers):
            finalizer()
    engine.dispose.assert_called_once_with()


@pytest.mark.parametrize(
    "question",
    ["我想做菜", "宫保鸡丁的历史典故是什么", "小炒肉需要哪些食材？", "数据库里有多少道菜"],
)
def test_router_diagnostic_accepts_the_unified_knowledge_route(question):
    from tests import test_router_smoke

    case = next(case for case in test_router_smoke.TEST_CASES if case["question"] == question)
    response = {
        "status": 200,
        "data": {"route": "knowledge-query", "message": "仅根据现有记录回答。", "sources": []},
    }
    assert test_router_smoke.evaluate_case(case, response)["passed"]


@pytest.mark.asyncio
async def test_router_diagnostic_sends_the_explicit_image_action(monkeypatch):
    from tests import test_router_smoke

    sent = []

    def respond(request):
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "route": "image-generation",
                "message": "fixture image",
                "session_id": "test",
                "message_id": "test-message",
                "route_logic": "explicit action",
                "sources": [],
                "metadata": {},
            },
        )

    case = test_router_smoke.TEST_CASES[-1]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        response = await test_router_smoke.invoke_chat(
            client, case["question"], 0, action=case["action"]
        )
    assert sent[0]["action"] == "generate_image"
    assert response["data"]["route"] == "image-generation"


@pytest.mark.asyncio
async def test_telemetry_model_factory_closes_transports_when_model_setup_fails(monkeypatch):
    from tests import test_request_telemetry as fixture_module

    clients: list[httpx.Client | httpx.AsyncClient] = []
    sync_client, async_client = httpx.Client, httpx.AsyncClient

    def make_sync(**kwargs):
        client = sync_client(**kwargs)
        clients.append(client)
        return client

    def make_async(**kwargs):
        client = async_client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(fixture_module.httpx, "Client", make_sync)
    monkeypatch.setattr(fixture_module.httpx, "AsyncClient", make_async)
    monkeypatch.setattr(
        fixture_module, "ChatOpenAI", Mock(side_effect=ValueError("model rejected"))
    )
    try:
        with pytest.raises(ValueError, match="model rejected"):
            async with fixture_module.chat_model(fixture_module.api()):
                pytest.fail("Model setup should have failed")
        assert len(clients) == 2 and all(client.is_closed for client in clients)
    finally:
        for client in clients:
            if isinstance(client, sync_client):
                client.close()
            else:
                await client.aclose()


@pytest.mark.parametrize("fail_activity", [False, True])
def test_add_session_message_commits_message_and_activity_together(fail_activity):
    from sqlalchemy import create_engine, event, func, select
    from sqlalchemy.orm import Session

    from gustobot.infrastructure.core.database import Base
    from gustobot.infrastructure.persistence.db.models import ChatMessage, ChatSession
    from gustobot.interfaces.http.models.session import ChatMessageCreate
    from gustobot.interfaces.http.v1.sessions import add_message_to_session

    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(ChatSession(id="atomic-message", title="fixture"))
            db.commit()

            def reject_activity(session, flush_context, instances):
                if fail_activity and any(isinstance(row, ChatSession) for row in session.dirty):
                    raise RuntimeError("activity update failed")

            event.listen(db, "before_flush", reject_activity)
            try:
                message = ChatMessageCreate(
                    session_id="atomic-message",
                    message_type="user_query",
                    content="question",
                    order_index=0,
                )
                if fail_activity:
                    with pytest.raises(RuntimeError, match="activity update failed"):
                        add_message_to_session(
                            db=db, session_id="atomic-message", message_in=message
                        )
                    assert not db.in_transaction()
                else:
                    saved = add_message_to_session(
                        db=db, session_id="atomic-message", message_in=message
                    )
                    assert saved.content == "question"
                assert db.scalar(select(func.count(ChatMessage.id))) == (0 if fail_activity else 1)
            finally:
                event.remove(db, "before_flush", reject_activity)
    finally:
        engine.dispose()
