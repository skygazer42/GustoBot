"""Offline regressions for explicit data contracts and SQL boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import anyio
import anyio.lowlevel
import httpx
import pytest


def test_application_reranker_preserves_zero_score():
    from gustobot.infrastructure.knowledge.reranker import Reranker

    reranker = Reranker.__new__(Reranker)
    documents = [{"id": 0, "content": "answer"}]
    ranked = reranker._process_rerank_results(
        [{"index": 0, "relevance_score": 0.0, "score": 1.0}], documents, 1
    )
    assert ranked == [{"id": 0, "content": "answer", "rerank_score": 0.0}]


@pytest.mark.asyncio
@pytest.mark.parametrize("close_error", [False, True])
async def test_search_stream_cancel_releases_openai_owner(monkeypatch, close_error):
    from openai import AsyncOpenAI

    from gustobot.application.services.search_service import SearchService

    closed = []
    started = anyio.Event()

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.close()

        def __aiter__(self):
            return self

        async def __anext__(self):
            started.set()
            await anyio.sleep_forever()

        async def close(self):
            await anyio.lowlevel.checkpoint()
            closed.append(True)
            if close_error:
                raise RuntimeError("stream close failed")

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
        async for _event in service.generate_stream("question"):
            pass

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(consume)
        await started.wait()
        tasks.cancel_scope.cancel()
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["success", "error", "cancel"])
@pytest.mark.parametrize("close_error", [False, True])
async def test_owned_cleanup_preserves_operation_outcome(operation, close_error):
    from gustobot.infrastructure.core.resources import close_on_exit

    failure = (
        asyncio.CancelledError("operation cancelled")
        if operation == "cancel"
        else RuntimeError("operation failed")
    )
    cleanup_failure = RuntimeError("resource close failed")
    close = AsyncMock(side_effect=cleanup_failure if close_error else None)

    async def run_operation():
        async with close_on_exit(close):
            if operation != "success":
                raise failure
            return "completed"

    if operation != "success":
        with pytest.raises(type(failure)) as raised:
            await run_operation()
        assert raised.value is failure
    elif close_error:
        with pytest.raises(RuntimeError) as raised:
            await run_operation()
        assert raised.value is cleanup_failure
    else:
        assert await run_operation() == "completed"
    close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 500])
async def test_json_chat_does_not_retry_unrelated_provider_failure(monkeypatch, status):
    from openai import AuthenticationError, InternalServerError

    from gustobot.application.services.llm_client import LLMClient

    client = LLMClient.__new__(LLMClient)
    response = httpx.Response(status, request=httpx.Request("POST", "https://provider.test"))
    error_type = AuthenticationError if status == 401 else InternalServerError
    failure = error_type("provider failure", response=response, body={})
    complete = AsyncMock(side_effect=[failure, SimpleNamespace()])
    monkeypatch.setattr(client, "complete", complete)
    with pytest.raises(error_type) as raised:
        await client.chat_json(system_prompt=None, user_message="question")
    assert raised.value is failure
    assert complete.await_count == 1


@pytest.mark.asyncio
async def test_json_chat_falls_back_only_for_unsupported_response_format(monkeypatch):
    from openai import BadRequestError

    from gustobot.application.services.llm_client import LLMClient

    client = LLMClient.__new__(LLMClient)
    failure = BadRequestError(
        "response_format is not supported",
        response=httpx.Response(400, request=httpx.Request("POST", "https://provider.test")),
        body={"param": "response_format"},
    )
    complete = AsyncMock(
        side_effect=[
            failure,
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": 0}'))]
            ),
        ]
    )
    monkeypatch.setattr(client, "complete", complete)
    assert await client.chat_json(system_prompt=None, user_message="question") == {"ok": 0}
    assert complete.await_count == 2
    assert "response_format" not in complete.await_args_list[1].kwargs


@pytest.mark.asyncio
async def test_owned_cleanup_propagates_new_cleanup_cancellation():
    from gustobot.infrastructure.core.resources import close_on_exit

    cancellation = asyncio.CancelledError("resource close cancelled")
    close = AsyncMock(side_effect=cancellation)
    with pytest.raises(asyncio.CancelledError) as raised:
        async with close_on_exit(close):
            raise ValueError("operation failed")
    assert raised.value is cancellation
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_owned_cleanup_reports_cooperative_timeout():
    from gustobot.infrastructure.core.resources import close_on_exit

    with anyio.fail_after(0.25):
        with pytest.raises(TimeoutError):
            async with close_on_exit(anyio.sleep_forever, timeout=0.01):
                pass


def test_llm_explicit_empty_key_does_not_reuse_configured_secret(monkeypatch):
    from gustobot.application.services import llm_client

    monkeypatch.setattr(llm_client.settings, "LLM_API_KEY", "configured-secret")
    sdk = Mock()
    monkeypatch.setattr(llm_client, "AsyncOpenAI", sdk)
    client = llm_client.LLMClient(api_key="")
    with pytest.raises(RuntimeError, match="not configured"):
        client._ensure_client()
    sdk.assert_not_called()


@pytest.mark.parametrize("field", ["model", "base_url"])
def test_llm_explicit_empty_required_configuration_is_invalid(monkeypatch, field):
    from gustobot.application.services import llm_client

    monkeypatch.setattr(llm_client, "AsyncOpenAI", Mock())
    with pytest.raises(ValueError, match=field):
        if field == "model":
            llm_client.LLMClient(api_key="test", model="")
        else:
            llm_client.LLMClient(api_key="test", base_url="")


def test_milvus_initialization_preserves_error_when_disconnect_fails(monkeypatch):
    from gustobot.infrastructure.knowledge import vector_store

    failure = ValueError("load failed")
    monkeypatch.setattr(vector_store.connections, "connect", Mock())
    monkeypatch.setattr(
        vector_store.connections, "disconnect", Mock(side_effect=RuntimeError("close"))
    )
    monkeypatch.setattr(vector_store.utility, "has_collection", Mock(return_value=True))
    monkeypatch.setattr(
        vector_store, "Collection", Mock(return_value=Mock(load=Mock(side_effect=failure)))
    )
    monkeypatch.setattr(vector_store.VectorStore, "_validate_schema", Mock())
    monkeypatch.setattr(vector_store.VectorStore, "_ensure_index", Mock())
    with pytest.raises(ValueError) as caught:
        vector_store.VectorStore()
    assert caught.value is failure


def test_reranker_keeps_unranked_documents_with_duplicate_or_missing_ids():
    from gustobot.infrastructure.knowledge.reranker import Reranker

    documents: list[dict[str, int | str]] = [
        {"id": 0, "content": "first"},
        {"id": 0, "content": "second"},
        {"content": "third"},
    ]
    reranker = Reranker.__new__(Reranker)
    result = reranker._process_rerank_results([{"index": 1, "score": 0.0}], documents, 3)
    assert [item["content"] for item in result] == ["second", "first", "third"]


def test_recipe_mapping_preserves_explicit_zero_values():
    from gustobot.infrastructure.knowledge.recipe_catalog import (
        _clean_name,
    )
    from gustobot.infrastructure.knowledge.recipe_import import (
        recipe_json_entry_to_recipe,
    )

    recipe = recipe_json_entry_to_recipe("test", {"类型": 0, "耗时": 0})
    assert recipe["category"] == 0
    assert recipe["time"] == 0
    assert _clean_name(0) == "0"


@pytest.mark.parametrize("field,value", [("RERANK_TOP_N", 0), ("RERANK_MODEL", "")])
def test_enabled_reranker_rejects_invalid_required_configuration(monkeypatch, field, value):
    from gustobot.infrastructure.knowledge import reranker

    monkeypatch.setattr(reranker.settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(reranker.settings, field, value)
    with pytest.raises(ValueError):
        reranker.Reranker()
