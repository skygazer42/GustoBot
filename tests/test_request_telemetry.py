"""Provider counters belong to one request even across threads and cancellation."""

import asyncio
import importlib
import importlib.util
import json
import sys
from contextlib import ExitStack, asynccontextmanager, closing
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI
from openai import APIStatusError

from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings


def api():
    name = "gustobot.infrastructure.knowledge.request_telemetry"
    assert importlib.util.find_spec(name) is not None, "Request-local provider telemetry is missing"
    return importlib.import_module(name)


def embedding_client(purpose="candidate", handler=None, *, space_fingerprint=None):
    def response(request):
        inputs = json.loads(request.content)["input"]
        return httpx.Response(
            200,
            json={
                "data": [{"index": index, "embedding": [1.0, 0.0]} for index in range(len(inputs))]
            },
        )

    transport = httpx.Client(
        transport=httpx.MockTransport(response if handler is None else handler)
    )
    try:
        return OpenAICompatibleEmbeddings(
            model="fixture",
            api_key="test-secret",
            dimension=2,
            purpose=purpose,
            base_url="https://fixture.invalid/v1",
            http_client=transport,
            space_fingerprint=space_fingerprint,
        )
    except BaseException:
        transport.close()
        raise


def test_capture_copies_snapshots_and_restores_parent_after_nested_capture():
    module = api()
    request = httpx.Request("POST", "https://fixture.invalid/v1/chat/completions")
    with module.capture_request_trace() as outer:
        module.record_provider_event("candidate", logical_calls=1, texts=1, input_characters=3)
        first = outer.snapshot()
        first["candidate"]["texts"] = 999
        with module.provider_phase("analysis"):
            module.record_sync_http_request(request)
            with module.capture_request_trace() as inner:
                module.record_sync_http_request(request)  # Parent phase must not leak.
                with module.provider_phase("generation"):
                    module.record_sync_http_request(request)
            module.record_sync_http_request(request)
        snapshot = outer.snapshot()
    module.record_provider_event("candidate", logical_calls=100)
    assert outer.snapshot() == snapshot
    assert snapshot["candidate"] == {
        "logical_calls": 1,
        "provider_batches": 0,
        "http_attempts": 0,
        "texts": 1,
        "input_characters": 3,
        "elapsed_seconds": 0.0,
    }
    assert snapshot["analysis"]["logical_calls"] == 1
    assert snapshot["analysis"]["http_attempts"] == 2
    assert "generation" not in snapshot
    assert set(inner.snapshot()) == {"generation"}


@pytest.mark.asyncio
async def test_shared_real_embedding_sdk_has_independent_concurrent_request_counters():
    module = api()
    barrier = Barrier(2)

    def response(request):
        inputs = json.loads(request.content)["input"]
        barrier.wait(timeout=5)
        return httpx.Response(
            200,
            json={
                "data": [{"index": index, "embedding": [1.0, 0.0]} for index in range(len(inputs))]
            },
        )

    client = embedding_client(handler=response)

    async def request(texts):
        with module.capture_request_trace() as trace:
            await client.aembed_documents(texts)
        return trace.snapshot()["candidate"]

    try:
        results = await asyncio.gather(
            request(["one"]), request(["two", "three"]), return_exceptions=True
        )
        first, second = results
        if isinstance(first, BaseException):
            raise first
        if isinstance(second, BaseException):
            raise second
        assert (
            first["logical_calls"],
            first["texts"],
            first["input_characters"],
            first["http_attempts"],
        ) == (1, 1, 3, 1)
        assert (
            second["logical_calls"],
            second["texts"],
            second["input_characters"],
            second["http_attempts"],
        ) == (1, 2, 8, 1)
        assert client.telemetry.snapshot()["logical_calls"] == 2
        assert client.telemetry.snapshot()["http_attempts"] == 2
    finally:
        client.close()


def test_document_candidate_build_events_are_separate_and_never_store_text_or_keys():
    module = api()
    with ExitStack() as owners:
        clients = [
            owners.enter_context(closing(embedding_client(purpose)))
            for purpose in ("document", "candidate", "build")
        ]
        with module.capture_request_trace() as trace:
            for client in clients:
                client.embed_query("private input text")
        snapshot = trace.snapshot()
        assert set(snapshot) == {"document", "candidate", "build"}
        for counters in snapshot.values():
            assert (
                counters["logical_calls"]
                == counters["provider_batches"]
                == counters["http_attempts"]
                == 1
            )
            assert counters["texts"] == 1 and counters["input_characters"] == 18
            assert "input_tokens" not in counters and "output_tokens" not in counters
        encoded = json.dumps(snapshot)
        assert "private input text" not in encoded and "test-secret" not in encoded


@pytest.mark.asyncio
async def test_late_thread_events_after_cancellation_cannot_contaminate_next_request():
    module = api()
    entered, release, completed = Event(), Event(), Event()

    def worker():
        try:
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Test thread was not released")
            module.record_provider_event("candidate", http_attempts=1)
        finally:
            completed.set()

    with module.capture_request_trace() as cancelled:
        module.record_provider_event("candidate", logical_calls=1)
        task = asyncio.create_task(asyncio.to_thread(worker))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with module.capture_request_trace() as next_request:
            release.set()
            assert await asyncio.to_thread(completed.wait, 5)
            assert next_request.snapshot() == {}
        assert cancelled.snapshot()["candidate"]["http_attempts"] == 1
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert await asyncio.to_thread(completed.wait, 5), "Telemetry worker did not exit"


def test_exception_resets_trace_and_phase():
    module = api()
    with (
        pytest.raises(RuntimeError),
        module.capture_request_trace() as failed,
        module.provider_phase("analysis"),
    ):
        raise RuntimeError("controlled failure")
    with module.capture_request_trace() as next_request:
        module.record_sync_http_request(httpx.Request("POST", "https://fixture.invalid"))
    assert next_request.snapshot() == {}
    assert failed.snapshot()["analysis"]["logical_calls"] == 1
    assert failed.snapshot()["analysis"]["http_attempts"] == 0


def chat_payload():
    return {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "created": 0,
        "model": "fixture",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }


@asynccontextmanager
async def chat_model(module, *, sync_handler=None, async_handler=None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_payload())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler if async_handler is None else async_handler),
        event_hooks={"request": [module.record_async_http_request]},
    ) as async_client:
        with httpx.Client(
            transport=httpx.MockTransport(handler if sync_handler is None else sync_handler),
            event_hooks={"request": [module.record_sync_http_request]},
        ) as sync_client:
            yield ChatOpenAI(
                model="fixture",
                api_key="test-secret",
                base_url="https://fixture.invalid/v1",
                max_retries=0,
                http_client=sync_client,
                http_async_client=async_client,
                callbacks=[module.ProviderUsageCallback()],
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("synchronous", [True, False])
async def test_real_chat_sdk_hooks_and_inline_usage_callback_share_request_context(synchronous):
    module = api()
    async with chat_model(module) as model:
        with module.capture_request_trace() as trace, module.provider_phase("analysis"):
            if synchronous:
                response = await asyncio.to_thread(model.invoke, "question")
            else:
                response = await model.ainvoke("question")
        counters = trace.snapshot()["analysis"]
        assert response.content == "answer"
        assert (
            counters["logical_calls"]
            == counters["provider_batches"]
            == counters["http_attempts"]
            == 1
        )
        assert counters["input_tokens"] == 7 and counters["output_tokens"] == 3
        assert counters["elapsed_seconds"] >= 0


@pytest.mark.asyncio
async def test_shared_model_keeps_parallel_phases_and_usage_with_their_own_requests():
    module = api()
    arrived, ready = 0, asyncio.Event()

    async def response(request):
        nonlocal arrived
        arrived += 1
        if arrived == 2:
            ready.set()
        await ready.wait()
        text = json.loads(request.content)["messages"][0]["content"]
        payload = chat_payload()
        payload["usage"] = {
            "prompt_tokens": len(text),
            "completion_tokens": 3,
            "total_tokens": len(text) + 3,
        }
        return httpx.Response(200, json=payload)

    async with chat_model(module, async_handler=response) as model:

        async def invoke(phase, text):
            with module.capture_request_trace() as trace, module.provider_phase(phase):
                await model.ainvoke(text)
            return trace.snapshot()

        results = await asyncio.wait_for(
            asyncio.gather(
                invoke("analysis", "a"), invoke("generation", "abc"), return_exceptions=True
            ),
            timeout=5,
        )
        first, second = results
        if isinstance(first, BaseException):
            raise first
        if isinstance(second, BaseException):
            raise second
        assert set(first) == {"analysis"} and set(second) == {"generation"}
        assert first["analysis"]["input_tokens"] == 1 and second["generation"]["input_tokens"] == 3
        assert first["analysis"]["http_attempts"] == second["generation"]["http_attempts"] == 1


@pytest.mark.asyncio
async def test_cancelled_phase_restores_request_context_before_next_capture():
    module = api()
    with (
        pytest.raises(asyncio.CancelledError),
        module.capture_request_trace() as cancelled,
        module.provider_phase("generation"),
    ):
        raise asyncio.CancelledError
    with module.capture_request_trace() as after:
        await module.record_async_http_request(httpx.Request("POST", "https://fixture.invalid"))
    assert after.snapshot() == {}
    assert cancelled.snapshot()["generation"]["logical_calls"] == 1


@pytest.mark.asyncio
async def test_failed_real_chat_sdk_counts_one_actual_attempt_and_leaves_usage_unknown():
    module = api()
    async with chat_model(
        module,
        async_handler=lambda request: httpx.Response(429, json={"error": {"message": "limited"}}),
    ) as model:
        with (
            module.capture_request_trace() as trace,
            pytest.raises(APIStatusError),
            module.provider_phase("generation"),
        ):
            await model.ainvoke("question")
        counters = trace.snapshot()["generation"]
        assert (
            counters["logical_calls"]
            == counters["provider_batches"]
            == counters["http_attempts"]
            == 1
        )
        assert "input_tokens" not in counters and "output_tokens" not in counters


def test_usage_prefers_raw_totals_over_repeated_choices_and_preserves_missing_dimensions():
    module = api()
    message = AIMessage(
        content="answer", usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    )
    choices = [ChatGeneration(message=message), ChatGeneration(message=message)]
    callback = module.ProviderUsageCallback()
    with module.capture_request_trace() as trace, module.provider_phase("analysis"):
        callback.on_llm_end(
            LLMResult(generations=[choices], llm_output={"token_usage": {"prompt_tokens": 11}}),
            run_id=uuid4(),
        )
    counters = trace.snapshot()["analysis"]
    assert counters["input_tokens"] == 11
    assert "output_tokens" not in counters
    with module.capture_request_trace() as trace, module.provider_phase("generation"):
        callback.on_llm_end(LLMResult(generations=[choices]), run_id=uuid4())
    counters = trace.snapshot()["generation"]
    assert counters["input_tokens"] == 7 and counters["output_tokens"] == 3


@pytest.mark.asyncio
async def test_stream_keeps_first_chunk_live_and_reuses_trace_without_spanning_yields():
    module = api()
    release = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            first = {
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "model": "fixture",
                "created": 0,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "first"},
                        "finish_reason": None,
                    }
                ],
            }
            yield ("data: " + json.dumps(first) + "\n\n").encode()
            await release.wait()
            usage = {
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "model": "fixture",
                "created": 0,
                "choices": [],
                "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
            }
            yield ("data: " + json.dumps(usage) + "\n\ndata: [DONE]\n\n").encode()

    async with chat_model(
        module,
        async_handler=lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Stream()
        ),
    ) as model:
        with module.capture_request_trace() as trace:
            module.record_provider_event("generation", logical_calls=1)
        iterator = model.astream("question", stream_usage=True)
        try:
            with (
                module.capture_request_trace(trace),
                module.provider_phase("generation", count_call=False),
            ):
                first = await asyncio.wait_for(iterator.__anext__(), timeout=2)
            assert first.content == "first" and not release.is_set()
            release.set()
            while True:
                try:
                    with (
                        module.capture_request_trace(trace),
                        module.provider_phase("generation", count_call=False),
                    ):
                        await iterator.__anext__()
                except StopAsyncIteration:
                    break
            counters = trace.snapshot()["generation"]
            assert (
                counters["logical_calls"]
                == counters["provider_batches"]
                == counters["http_attempts"]
                == 1
            )
            assert counters["input_tokens"] == 9 and counters["output_tokens"] == 2
        finally:
            release.set()
            await iterator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["custom", "jina", "voyage"])
@pytest.mark.parametrize("status", [200, 429])
async def test_reranker_counts_actual_http_attempt_without_hidden_retries(
    monkeypatch, provider, status
):
    module = api()
    from gustobot.infrastructure.knowledge import reranker

    settings = {
        "RERANK_ENABLED": True,
        "RERANK_PROVIDER": provider,
        "RERANK_BASE_URL": "https://rerank.invalid",
        "RERANK_API_KEY": "rerank-secret",
        "RERANK_MODEL": "fixture",
        "RERANK_TOP_N": 2,
        "RERANK_TIMEOUT": 1.0,
    }
    for key, value in settings.items():
        monkeypatch.setattr(reranker.settings, key, value)
    requests = []

    def response(request):
        requests.append(request)
        rows = [{"index": 1, "relevance_score": 0.9}]
        return httpx.Response(
            status, json={"results": rows, "output": {"results": rows}, "data": rows}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        reranker.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs),
    )
    documents = [{"content": "first"}, {"content": "second"}]
    with module.capture_request_trace() as trace:
        result = await reranker.Reranker().rerank("q", documents, 1)
    assert len(requests) == 1
    assert result[0]["content"] == ("second" if status == 200 else "first")
    counters = trace.snapshot()["rerank"]
    assert (
        counters["logical_calls"] == counters["provider_batches"] == counters["http_attempts"] == 1
    )
    assert counters["texts"] == 3 and counters["input_characters"] == 12
    assert "rerank-secret" not in json.dumps(trace.snapshot())


@pytest.mark.asyncio
async def test_cohere_boundary_sets_zero_retries_and_counts_real_transport_attempt(monkeypatch):
    module = api()
    from gustobot.infrastructure.knowledge import reranker

    for key, value in {
        "RERANK_ENABLED": True,
        "RERANK_PROVIDER": "cohere",
        "RERANK_API_KEY": "rerank-secret",
        "RERANK_MODEL": "fixture",
        "RERANK_TOP_N": 2,
    }.items():
        monkeypatch.setattr(reranker.settings, key, value)
    transports = []

    class SDK:
        def __init__(self, *, token, timeout, httpx_client, max_retries):
            assert token == "rerank-secret" and max_retries == 0
            self.http = httpx_client
            transports.append(self.http)

        def rerank(self, *, query, documents, top_n, model, request_options):
            assert request_options["max_retries"] == 0
            response = self.http.post(
                "https://cohere.invalid/rerank", json={"query": query, "documents": documents}
            )
            response.raise_for_status()
            return SimpleNamespace(results=[SimpleNamespace(index=1, relevance_score=0.9)])

    monkeypatch.setitem(sys.modules, "cohere", SimpleNamespace(Client=SDK))
    original = httpx.Client
    monkeypatch.setattr(
        reranker.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kwargs
        ),
    )
    with module.capture_request_trace() as trace:
        result = await reranker.Reranker().rerank(
            "q", [{"content": "first"}, {"content": "second"}], 1
        )
    assert result[0]["content"] == "second"
    counters = trace.snapshot()["rerank"]
    assert (
        counters["logical_calls"] == counters["provider_batches"] == counters["http_attempts"] == 1
    )
    assert transports[0].is_closed


@pytest.mark.asyncio
async def test_optional_real_cohere_sdk_transport_trace(monkeypatch):
    pytest.importorskip("cohere", reason="Optional Cohere SDK is not installed")
    module = api()
    from gustobot.infrastructure.knowledge import reranker

    for key, value in {
        "RERANK_ENABLED": True,
        "RERANK_PROVIDER": "cohere",
        "RERANK_API_KEY": "rerank-secret",
        "RERANK_MODEL": "fixture",
        "RERANK_TOP_N": 2,
    }.items():
        monkeypatch.setattr(reranker.settings, key, value)
    original = httpx.Client
    monkeypatch.setattr(
        reranker.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "id": "rerank-fixture",
                        "results": [{"index": 1, "relevance_score": 0.9}],
                    },
                )
            ),
            **kwargs,
        ),
    )
    with module.capture_request_trace() as trace:
        result = await reranker.Reranker().rerank(
            "q", [{"content": "first"}, {"content": "second"}], 1
        )
    assert result[0]["content"] == "second"
    assert trace.snapshot()["rerank"]["http_attempts"] == 1


def test_request_embedding_cache_reuses_same_space_without_hiding_network_counts():
    from gustobot.infrastructure.knowledge.request_telemetry import (
        capture_request_trace,
    )

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    with ExitStack() as owners:
        clients = [
            owners.enter_context(
                closing(embedding_client(purpose, handler=respond, space_fingerprint="a" * 64))
            )
            for purpose in ("candidate", "document")
        ]
        with capture_request_trace() as trace:
            assert clients[0].embed_query("相同问题") == clients[1].embed_query("相同问题")
        assert len(requests) == 1
        assert trace.snapshot()["candidate"]["http_attempts"] == 1
        assert trace.snapshot()["document"]["cache_hits"] == 1
        assert trace.snapshot()["document"]["http_attempts"] == 0
        with capture_request_trace():
            clients[1].embed_query("相同问题")
        assert len(requests) == 2
