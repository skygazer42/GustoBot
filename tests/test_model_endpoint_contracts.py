"""Configured OpenAI extensions and rerank wire formats reach the real adapters."""

import json
from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai.types.chat import ChatCompletion


def completion_payload():
    return {
        "id": "fixture",
        "object": "chat.completion",
        "created": 0,
        "model": "fixture",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_model_extension_settings_decode_json_and_rerank_format(monkeypatch):
    from gustobot.config.settings import Settings

    monkeypatch.setenv("LLM_EXTRA_BODY", '{"thinking":{"type":"disabled"}}')
    monkeypatch.setenv("RERANK_API_FORMAT", "standard")
    configured = Settings(_env_file=None).model_dump()
    assert configured.get("LLM_EXTRA_BODY") == {"thinking": {"type": "disabled"}}
    assert configured.get("RERANK_API_FORMAT") == "standard"


@pytest.mark.asyncio
@pytest.mark.parametrize("api_format", ["standard", "dashscope"])
async def test_custom_rerank_uses_the_selected_wire_format(monkeypatch, api_format):
    from gustobot.infrastructure.knowledge import reranker

    monkeypatch.setattr(
        reranker,
        "settings",
        reranker.settings.model_copy(
            update={
                "RERANK_ENABLED": True,
                "RERANK_PROVIDER": "custom",
                "RERANK_API_FORMAT": api_format,
                "RERANK_BASE_URL": "https://rerank.invalid/v1",
                "RERANK_ENDPOINT": "/rerank",
                "RERANK_API_KEY": "fixture",
                "RERANK_MODEL": "BAAI/bge-reranker-v2-m3",
                "RERANK_TOP_N": 6,
            }
        ),
    )
    requests = []

    def respond(request):
        requests.append((str(request.url), json.loads(request.content)))
        rows = [{"index": 1, "relevance_score": 0.9}]
        return httpx.Response(
            200,
            json={"results": rows} if api_format == "standard" else {"output": {"results": rows}},
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        reranker.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    documents = [{"content": "unrelated"}, {"content": "target"}]
    result = await reranker.Reranker().rerank("question", documents, 1)
    expected = (
        {
            "model": "BAAI/bge-reranker-v2-m3",
            "query": "question",
            "documents": ["unrelated", "target"],
            "top_n": 1,
            "return_documents": False,
        }
        if api_format == "standard"
        else {
            "model": "BAAI/bge-reranker-v2-m3",
            "input": {"query": "question", "documents": ["unrelated", "target"]},
            "parameters": {"return_documents": True, "top_n": 2},
        }
    )
    assert requests == [("https://rerank.invalid/v1/rerank", expected)]
    assert result[0]["content"] == "target" and result[0]["rerank_score"] == 0.9


@pytest.mark.asyncio
async def test_runtime_chat_serializes_configured_request_extensions(monkeypatch):
    from gustobot.application.services import knowledge_runtime as runtime

    monkeypatch.setattr(runtime, "_model", None)
    monkeypatch.setattr(
        runtime,
        "settings",
        runtime.settings.model_copy(
            update={
                "LLM_API_KEY": "fixture",
                "LLM_MODEL": "deepseek-flash",
                "LLM_BASE_URL": "https://chat.invalid/v1",
                "LLM_EXTRA_BODY": {"thinking": {"type": "disabled"}},
            }
        ),
    )
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion_payload())

    async with AsyncExitStack() as owners:

        class SyncClient(httpx.Client):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(respond), **kwargs)
                owners.callback(self.close)

        class AsyncClient(httpx.AsyncClient):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(respond), **kwargs)
                owners.push_async_callback(self.aclose)

        monkeypatch.setattr(httpx, "Client", SyncClient)
        monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)
        model = runtime.get_model()
        assert model is not None
        assert (await model.ainvoke("question")).content == "OK"
    assert bodies[0].get("thinking") == {"type": "disabled"}


@pytest.mark.asyncio
@pytest.mark.parametrize("response_format", [None, {"type": "json_object"}])
async def test_llm_wrapper_forwards_request_extensions(monkeypatch, response_format):
    from gustobot.application.services import llm_client

    monkeypatch.setattr(
        llm_client,
        "settings",
        llm_client.settings.model_copy(
            update={
                "LLM_EXTRA_BODY": {"thinking": {"type": "disabled"}},
            }
        ),
    )
    client = llm_client.LLMClient(api_key="", model="deepseek-flash")
    create = AsyncMock(return_value=ChatCompletion.model_validate(completion_payload()))
    monkeypatch.setattr(
        client,
        "_client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    await client.complete(
        messages=[{"role": "user", "content": "question"}],
        temperature=0,
        response_format=response_format,
    )
    (invocation,) = create.await_args_list
    assert invocation.kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_search_tool_and_answer_share_configured_request_extensions(monkeypatch):
    from gustobot.application.services import search_service

    monkeypatch.setattr(
        search_service,
        "settings",
        search_service.settings.model_copy(
            update={
                "LLM_EXTRA_BODY": {"thinking": {"type": "disabled"}},
            }
        ),
    )
    closed = []

    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def close(self):
            closed.append(True)

    create = AsyncMock(side_effect=[ChatCompletion.model_validate(completion_payload()), Stream()])
    service = search_service.SearchService.__new__(search_service.SearchService)
    service.model = "deepseek-flash"
    service.tools_description = "fixture"
    service._openai_tools = []
    monkeypatch.setattr(
        service,
        "client",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        raising=False,
    )
    events = [event async for event in service.generate_stream("question")]
    assert events and closed == [True] and create.await_count == 2
    assert all(
        call.kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}
        for call in create.await_args_list
    )
