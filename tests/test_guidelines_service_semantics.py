"""Behavior regressions for the complete service-contract review."""

import asyncio
import importlib
import threading
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, create_autospec

import anyio
import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from gustobot.application.services import knowledge_runtime
from gustobot.application.services.knowledge_query import (
    KnowledgeQueryService,
    PreparedAnswer,
    QuestionPlan,
)
from gustobot.application.services.semantic_indexing import SemanticIndexingService
from gustobot.config.domain import get_domain_definition
from gustobot.domain.linking import IndexPublicationStatus
from gustobot.infrastructure.core import database
from gustobot.infrastructure.persistence.db.models.chat import ChatSession
from gustobot.interfaces.http.models.session import ChatSessionUpdate
from scripts.evaluate_knowledge import calculate_cost


@pytest.mark.parametrize("payload", [{"title": None}, {"is_active": None}, {"title": "x" * 501}])
def test_session_updates_reject_values_the_stored_contract_cannot_accept(payload):
    with pytest.raises(ValidationError):
        ChatSessionUpdate.model_validate(payload)


def test_session_update_preserves_empty_false_and_clearable_user_identity():
    update = ChatSessionUpdate(title="", is_active=False, user_id=None)
    assert update.model_dump(exclude_unset=True) == {
        "title": "",
        "is_active": False,
        "user_id": None,
    }


@pytest.mark.asyncio
async def test_session_query_model_preserves_http_parameters_and_rejects_negative_paging(
    monkeypatch,
):
    import httpx
    from fastapi import FastAPI

    from gustobot.infrastructure.core.database import get_db
    from gustobot.interfaces.http.v1 import sessions

    calls = []

    def by_user(db, **options):
        calls.append(options)
        return []

    monkeypatch.setattr(sessions.chat_session, "get_by_user", by_user)
    app = FastAPI()
    app.include_router(sessions.router, prefix="/sessions")
    app.dependency_overrides[get_db] = lambda: object()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/sessions/",
            params={"user_id": "owner", "skip": 0, "limit": 1, "active_only": "false"},
        )
        assert response.status_code == 200 and response.json() == []
        assert calls == [{"user_id": "owner", "skip": 0, "limit": 1, "active_only": False}]
        for parameters in ({"skip": -1}, {"limit": 0}):
            assert (await client.get("/sessions/", params=parameters)).status_code == 422
    assert len(calls) == 1


@pytest.mark.parametrize("usage,price", [(-1, -1), (0, -1), (-1, 0)])
def test_cost_rejects_each_negative_input_even_when_the_product_is_nonnegative(usage, price):
    with pytest.raises(ValueError, match="nonnegative"):
        calculate_cost(
            {"candidate": {"http_attempts": 1, "input_tokens": usage}},
            {"candidate": {"input_usd_per_million": price}},
        )


def test_empty_declared_prices_leave_the_total_unknown():
    result = calculate_cost(
        {"candidate": {"http_attempts": 1}, "generation": {"http_attempts": 1}},
        {"candidate": {"http_attempt_usd": "0.01"}, "generation": {}},
    )
    assert result["usd"] is None
    assert result["usd_known"] == "0.01"
    assert result["unknown"] == ["generation.price"]


def test_failed_rollback_invalidates_connection_and_preserves_commit_failure(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback.sqlite'}")
    try:
        database.Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(ChatSession(id="pending", title="uncommitted"))
            session.flush()
            connection = session.connection()
            original = RuntimeError("commit failed")

            def fail_commit():
                raise original

            def fail_rollback():
                raise RuntimeError("rollback failed")

            monkeypatch.setattr(session, "commit", fail_commit)
            monkeypatch.setattr(session, "rollback", fail_rollback)
            with pytest.raises(RuntimeError, match="commit failed") as failure:
                database.commit_session(session)
            assert failure.value is original
            assert connection.invalidated or connection.closed
        with Session(engine) as verification:
            assert verification.scalar(select(ChatSession.id)) is None
    finally:
        engine.dispose()


def test_failed_rollback_and_invalidation_keep_the_primary_failure_visible(monkeypatch, capsys):
    from gustobot.infrastructure.core.logger import configure_logging

    original = RuntimeError("commit failed")

    def commit():
        raise original

    def rollback():
        raise OSError("rollback failed")

    def invalidate():
        raise OSError("invalidate failed")

    configure_logging()
    with Session() as session:
        monkeypatch.setattr(session, "commit", commit)
        monkeypatch.setattr(session, "rollback", rollback)
        monkeypatch.setattr(session, "invalidate", invalidate)
        with pytest.raises(RuntimeError, match="commit failed") as failure:
            database.commit_session(session)
        assert failure.value is original
    output = capsys.readouterr().err
    assert "Rollback failed" in output and "invalidate failed" in output


@pytest.mark.asyncio
async def test_async_index_metadata_does_not_block_other_tasks(monkeypatch):
    from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings
    from gustobot.infrastructure.knowledge.graph_store import Neo4jGraphStore
    from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore

    domain = get_domain_definition()
    builder = SemanticIndexingService(
        domain,
        graph_store=create_autospec(Neo4jGraphStore, instance=True),
        candidate_store=create_autospec(SemanticCandidateStore, instance=True),
        embedder=create_autospec(OpenAICompatibleEmbeddings, instance=True),
        embedding_fingerprint="a" * 64,
    )
    released = threading.Event()
    progressed = []
    scope = builder.scope("concept")

    def metadata(operation):
        released.wait(timeout=0.2)
        return IndexPublicationStatus(scope=scope)

    async def other_request():
        progressed.append(True)
        released.set()

    monkeypatch.setattr(builder, "_transaction", metadata)
    task = asyncio.create_task(other_request())
    try:
        assert (await builder.status(scope)).status == "missing"
        assert progressed == [True]
    finally:
        released.set()
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_async_constructor,fail_sync_close", [(True, False), (False, True)])
async def test_failed_chat_construction_closes_every_transport(
    monkeypatch, fail_async_constructor, fail_sync_close
):
    import httpx

    closed = []

    class SyncTransport:
        def __init__(self, **kwargs):
            pass

        def close(self):
            closed.append("sync")
            if fail_sync_close:
                raise OSError("sync close failed")

    class AsyncTransport:
        def __init__(self, **kwargs):
            if fail_async_constructor:
                raise ValueError("async transport failed")

        async def aclose(self):
            closed.append("async")

    def model(**kwargs):
        raise ValueError("model failed")

    monkeypatch.setattr(httpx, "Client", SyncTransport)
    monkeypatch.setattr(httpx, "AsyncClient", AsyncTransport)
    monkeypatch.setattr(knowledge_runtime, "ChatOpenAI", model)
    monkeypatch.setattr(knowledge_runtime, "_model", None)
    monkeypatch.setattr(
        knowledge_runtime,
        "settings",
        knowledge_runtime.settings.model_copy(update={"LLM_API_KEY": "fixture"}),
    )
    with pytest.raises(ValueError):
        knowledge_runtime.get_model()
    assert set(closed) == ({"sync"} if fail_async_constructor else {"sync", "async"})


@pytest.mark.asyncio
async def test_query_stream_closes_its_model_iterator_inside_a_cancelled_scope(
    monkeypatch,
):
    closed = []

    class Model:
        async def astream(self, messages):
            try:
                yield AIMessage(content="first")
                yield AIMessage(content="second")
            finally:
                await anyio.lowlevel.checkpoint()
                closed.append(True)

    service = KnowledgeQueryService(
        get_domain_definition(), graph_store=object(), documents=object(), model=Model()
    )

    async def prepare(question, *, history):
        return PreparedAnswer(question, QuestionPlan(documents=True))

    monkeypatch.setattr(service, "prepare", prepare)
    stream = service.stream("document")
    try:
        assert (await anext(stream))["type"] == "metadata"
        assert (await anext(stream))["content"] == "first"
        with anyio.CancelScope() as cancelled:
            cancelled.cancel()
            await stream.aclose()
        assert closed == [True]
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_sse_send_failure_closes_the_suspended_query_stream(monkeypatch):
    from gustobot.interfaces.http.v1 import chat

    closed = []

    class Query:
        def stream(self, question, *, history):
            async def events():
                try:
                    yield {"type": "message", "content": "first"}
                    yield {"type": "message", "content": "second"}
                finally:
                    await anyio.lowlevel.checkpoint()
                    closed.append(True)

            self.current = events()
            return self.current

    query = Query()

    async def prepare(request, db):
        return "session", [], None, "parent", None

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        if b'"content": "first"' in message.get("body", b""):
            raise OSError("client disconnected")

    monkeypatch.setattr(chat, "prepare_request", prepare)
    monkeypatch.setattr(chat, "get_query_service", lambda: query)
    with Session() as db:
        response = await chat.chat_stream(chat.ChatRequest(message="question"), db)
        try:
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        # Validate the task group's original failure across Python versions.
        except Exception as failure:  # noqa: BLE001
            # ExceptionGroup uses the backport on supported Python 3.10.
            errors = getattr(failure, "exceptions")  # noqa: B009
            assert len(errors) == 1 and isinstance(errors[0], OSError)
            assert str(errors[0]) == "client disconnected"
        else:
            pytest.fail("The failed ASGI send must remain visible")
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [float("inf"), float("nan")])
async def test_cleanup_owners_reject_unbounded_or_nonfinite_budgets(timeout):
    from gustobot.infrastructure.core.resources import acquire_in_thread, close_on_exit

    async def close(*args):
        raise AssertionError("Invalid cleanup budgets must fail before acquisition")

    with pytest.raises(ValueError, match="finite"):
        async with close_on_exit(close, timeout=timeout):
            pass
    with pytest.raises(ValueError, match="finite"):
        async with acquire_in_thread(lambda: object(), close, timeout=timeout):
            pass


def test_debug_exception_logging_keeps_frames_without_local_secret_values(capsys):
    from loguru import logger

    from gustobot.infrastructure.core.logger import configure_logging

    def fail(password):
        if password:
            raise RuntimeError("fixture failure")

    password = "fixture-secret-must-not-appear"
    configure_logging(debug=True)
    try:
        try:
            fail(password)
        except RuntimeError:
            logger.exception("Operation failed")
        output = capsys.readouterr().err
        assert password not in output
        assert "RuntimeError" in output and "fail" in output
    finally:
        configure_logging()


@pytest.mark.asyncio
async def test_repeated_ingestion_cancel_waits_for_registration_and_durable_outcome(
    monkeypatch,
):
    from gustobot.application.services.knowledge_ingestion import (
        IngestionReceipt,
        KnowledgeIngestionService,
    )
    from gustobot.domain.knowledge import SourceDocument

    entered, release = threading.Event(), threading.Event()
    recorded = []
    domain = get_domain_definition()
    service = KnowledgeIngestionService(domain)
    receipt = IngestionReceipt(
        job_id="job",
        domain_id=domain.id,
        source_id="source",
        version="version",
        ontology_version=domain.version,
        kind="document",
        status="processing",
    )

    def register(*args):
        entered.set()
        assert release.wait(timeout=2)
        return receipt

    async def outcome(current, status, details, error):
        await asyncio.sleep(0)
        recorded.append(status)
        return current, None

    async def write(_receipt):
        raise AssertionError("Cancelled registration must not begin the external write")

    monkeypatch.setattr(service, "_start", register)
    monkeypatch.setattr(service, "_failed", outcome)
    task = asyncio.create_task(
        service._execute(SourceDocument(id="source", text="text"), "document", {}, write)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert recorded == ["cancelled"]
    finally:
        release.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["semantic_indexing", "knowledge_backend"])
async def test_integration_setup_failure_closes_the_engine_before_yield(
    target, monkeypatch, tmp_path
):
    module = importlib.import_module(f"tests.test_{target}_integration")
    closed = []
    engine = SimpleNamespace(dispose=lambda: closed.append(True))

    def fail_migration(current):
        assert current is engine
        raise RuntimeError("migration setup failed")

    monkeypatch.setattr(module, "create_database_engine", lambda url: engine)
    monkeypatch.setattr(module, "migrate_database", fail_migration)
    monkeypatch.setenv("GUSTOBOT_TEST_MYSQL_URL", "isolated-fixture")
    monkeypatch.setenv("GUSTOBOT_MILVUS_TEST_CONFIG", "unused-fixture")
    with pytest.raises(RuntimeError, match="migration setup failed"):
        if target == "semantic_indexing":
            scope = SimpleNamespace(
                domain=get_domain_definition(),
                quick=object(),
                store=SimpleNamespace(upsert=AsyncMock()),
            )
            await module.test_three_store_build_publish_link_query_update_and_rebuild(scope)
        else:
            await module.test_http_ingestion_publication_query_stream_and_ambiguity_with_real_stores(
                monkeypatch, tmp_path
            )
    assert closed == [True]


@pytest.mark.parametrize("field,value", [("max_messages", 0), ("max_messages", -1), ("ttl", 0)])
def test_history_rejects_retention_that_would_keep_unbounded_messages(field, value):
    from gustobot.application.services.redis_cache import RedisConversationHistory

    with pytest.raises(ValueError):
        RedisConversationHistory(redis_client=Mock(), **{field: value})


def test_cache_empty_scope_keeps_an_explicit_namespace():
    from gustobot.application.services.redis_cache import RedisSemanticCache

    cache = RedisSemanticCache(redis_client=Mock())
    assert cache._namespace("") != cache._namespace(None)


def test_cache_namespace_cannot_expand_the_redis_scan_glob():
    from gustobot.application.services.redis_cache import RedisSemanticCache

    patterns = []

    async def scan(pattern):
        patterns.append(pattern)
        if False:
            yield b"unused"

    cache = RedisSemanticCache(redis_client=Mock(scan_iter=scan))
    asyncio.run(cache.clear_namespace("team*[a]?"))
    assert patterns == [r"semantic:team\*\[a\]\?:*"]


def test_history_corruption_does_not_become_an_empty_success():
    from gustobot.application.services.redis_cache import RedisConversationHistory

    history = RedisConversationHistory(
        redis_client=Mock(lrange=AsyncMock(return_value=[b"broken"]))
    )
    with pytest.raises(ValueError):
        asyncio.run(history.get_recent("session"))


@pytest.mark.parametrize("empty_field", ["model_name", "redis_url"])
def test_cache_explicit_empty_configuration_does_not_reuse_defaults(empty_field):
    from gustobot.application.services.redis_cache import RedisSemanticCache

    with pytest.raises(ValueError):
        if empty_field == "model_name":
            RedisSemanticCache(model_name="")
        else:
            RedisSemanticCache(redis_url="")


@pytest.mark.parametrize("data", [[[1.0]], [{"embedding": [True]}]])
def test_cache_embedding_rejects_unsupported_bare_vector_shape(monkeypatch, data):
    from gustobot.application.services import redis_cache

    response = httpx.Response(
        200, json={"data": data}, request=httpx.Request("POST", "http://test")
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = response
    monkeypatch.setattr(redis_cache.httpx, "AsyncClient", Mock(return_value=client))
    cache = redis_cache.RedisSemanticCache(redis_client=Mock())
    with pytest.raises((ValueError, ValidationError)):
        asyncio.run(cache._get_embedding("question"))


@pytest.mark.parametrize("item", [{"link": "https://test"}, {"title": "missing URL"}])
def test_search_provider_result_requires_a_title_and_link(item):
    from gustobot.infrastructure.tools.search import SearchTool

    tool = SearchTool.__new__(SearchTool)
    with pytest.raises((KeyError, ValueError, ValidationError)):
        tool._parse_results({"organic_results": [item]}, limit=1)


def test_search_tool_explicit_empty_api_key_does_not_use_configured_secret(monkeypatch):
    from gustobot.infrastructure.tools import search

    monkeypatch.setattr(search.settings, "ENABLE_EXTERNAL_SEARCH", True)
    monkeypatch.setattr(search.settings, "SERPAPI_KEY", "configured-secret")
    with pytest.raises(RuntimeError, match="SERPAPI_KEY"):
        search.SearchTool(api_key="")


def test_stream_tool_arguments_are_validated_before_search(monkeypatch):
    from gustobot.application.services.search_service import SearchService

    service = SearchService.__new__(SearchService)
    service.tools_description = "search"
    service.search_tool = Mock()
    monkeypatch.setattr(
        service,
        "_call_with_tool",
        AsyncMock(
            return_value=SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            type="function",
                            function=SimpleNamespace(name="search", arguments='{"query":42}'),
                        )
                    ]
                ),
            )
        ),
    )

    async def consume():
        async for _event in service.generate_stream("question"):
            pass

    with pytest.raises((ValueError, ValidationError)):
        asyncio.run(consume())
    service.search_tool.search.assert_not_called()


def test_zero_cache_score_can_match_and_preserve_an_empty_response(monkeypatch):
    from gustobot.application.services.redis_cache import RedisSemanticCache

    async def scan(_pattern):
        yield b"semantic:vec:hash"

    redis = Mock(scan_iter=scan, get=AsyncMock(side_effect=[b"[0, 1]", b""]))
    cache = RedisSemanticCache(redis_client=redis, score_threshold=0.0)
    monkeypatch.setattr(cache, "_get_embedding", AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setattr(cache, "_update_metadata", AsyncMock())
    assert asyncio.run(cache.lookup([{"role": "user", "content": "question"}])) == ""


def test_search_logging_uses_the_bound_loguru_protocol(monkeypatch):
    from loguru import logger
    from openai.types.chat import ChatCompletion

    from gustobot.application.services.search_service import SearchService

    completion = ChatCompletion(
        id="test",
        created=0,
        model="fixture",
        object="chat.completion",
        choices=[
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "answer"},
            }
        ],
    )
    service = SearchService.__new__(SearchService)
    service.model = "fixture"
    service._openai_tools = []
    monkeypatch.setattr(
        service,
        "client",
        SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=completion))
            )
        ),
        raising=False,
    )
    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{message}", level="DEBUG")
    try:
        asyncio.run(service._call_with_tool([{"role": "user", "content": "private question"}]))
    finally:
        logger.remove(sink_id)
    text = "".join(messages)
    assert "Selecting a tool for 1 messages" in text
    assert "Model tool selection finished: stop" in text
    assert "private question" not in text


def test_restore_cleanup_releases_other_resources_when_database_drop_fails(tmp_path, monkeypatch):
    from tests.test_knowledge_restore_integration import OwnedResources

    owned = OwnedResources.__new__(OwnedResources)
    owned.engine = Mock()
    owned.admin_engine = MagicMock()
    connection = owned.admin_engine.begin.return_value.__enter__.return_value
    connection.execute.side_effect = ValueError("drop failed")
    owned.created_database = owned.created_container = owned.created_volume = True
    owned.database = "gustobot_restore_" + "a" * 16
    owned.token = "a" * 16
    owned.name = "gustobot-restore-" + owned.token
    owned.volume = owned.name + "-data"
    owned.path = tmp_path
    owned.evidence = {"cleanup": {}}

    def docker(args, **options):
        return owned.token.encode() if "inspect" in args else b""

    commands = Mock(side_effect=docker)
    monkeypatch.setattr(owned, "docker", commands)
    with pytest.raises(ValueError, match="drop failed"):
        owned.cleanup()
    owned.engine.dispose.assert_called_once()
    owned.admin_engine.dispose.assert_called_once()
    assert any(call.args[0] == ["rm", "--force", owned.name] for call in commands.call_args_list)
    assert any(call.args[0] == ["volume", "rm", owned.volume] for call in commands.call_args_list)


def test_milvus_fixture_disconnects_partial_setup_without_querying_a_failed_connection(
    tmp_path, monkeypatch
):
    from pymilvus import connections, utility

    from tests.test_semantic_index import actual_milvus_collection

    config = tmp_path / "isolated.json"
    config.write_text('{"host":"127.0.0.1","port":1}', encoding="utf-8")
    monkeypatch.setenv("GUSTOBOT_MILVUS_TEST_CONFIG", str(config))
    failure = ValueError("connection setup failed")
    monkeypatch.setattr(connections, "connect", Mock(side_effect=failure))
    disconnect = Mock()
    exists = Mock()
    monkeypatch.setattr(connections, "disconnect", disconnect)
    monkeypatch.setattr(utility, "has_collection", exists)
    fixture = actual_milvus_collection.__wrapped__()
    with pytest.raises(ValueError) as raised:
        next(fixture)
    assert raised.value is failure
    disconnect.assert_called_once()
    exists.assert_not_called()
