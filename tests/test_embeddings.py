"""Embedding provider boundaries count real requests and reject corrupt output."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings


@pytest.fixture
def provider_client():
    with ExitStack() as owners:

        def create(handler, **options):
            transport = httpx.Client(transport=httpx.MockTransport(handler))
            try:
                client = OpenAICompatibleEmbeddings(
                    model="fixture",
                    api_key="test",
                    base_url="https://embedding.invalid/v1",
                    dimension=2,
                    http_client=transport,
                    **options,
                )
            except BaseException:
                transport.close()
                raise
            owners.callback(client.close)
            return client

        yield create


@pytest.mark.parametrize("purpose", ["candidate", "document", "build"])
def test_raw_http_booleans_cannot_be_coerced_into_embedding_numbers(purpose, provider_client):
    client = provider_client(
        lambda request: httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [True, False]}]}
        ),
        purpose=purpose,
    )
    with pytest.raises(ValueError, match="numeric"):
        client.embed_query("question")


@pytest.mark.parametrize(
    "purpose,timeout", [("document", 25.0), ("candidate", 3.0), ("build", 60.0)]
)
def test_provider_attempts_are_counted_and_not_retried_by_sdk(purpose, timeout, provider_client):
    requests = []

    def limited(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "limited", "type": "rate_limit"}})

    events = []
    client = provider_client(
        limited,
        purpose=purpose,
        request_timeout=timeout,
        telemetry_callback=lambda event, snapshot: events.append((event, snapshot)),
    )
    with pytest.raises(APIStatusError):
        client.embed_documents(["one", "two"])
    assert len(requests) == 1
    assert requests[0].extensions["timeout"] == {
        "connect": timeout,
        "read": timeout,
        "write": timeout,
        "pool": timeout,
    }
    snapshot = client.telemetry.snapshot()
    assert snapshot["purpose"] == purpose
    assert (
        snapshot["logical_calls"] == snapshot["provider_batches"] == snapshot["http_attempts"] == 1
    )
    assert snapshot["texts"] == 2
    assert any(event == "http_attempt" for event, _ in events)
    assert client._client.max_retries == 0
    assert client._client.timeout == timeout


@pytest.mark.parametrize(
    "data,match",
    [
        ([{"index": 0, "embedding": [1.0]}], "dimension"),
        ([{"index": 0, "embedding": [float("nan"), 0.0]}], "finite"),
        ([{"index": 0, "embedding": [float("inf"), 0.0]}], "finite"),
        ([{"index": 0, "embedding": []}], "empty"),
        ([], "count|indices"),
        ([{"index": 1, "embedding": [1.0, 0.0]}], "indices"),
        ([{"index": False, "embedding": [1.0, 0.0]}], "indices"),
        ([{"index": 0.0, "embedding": [1.0, 0.0]}], "indices"),
    ],
)
def test_embedding_batch_indices_dimension_and_finiteness_are_strict(
    data, match, monkeypatch, provider_client
):
    client = provider_client(lambda request: httpx.Response(500), purpose="candidate")
    from types import SimpleNamespace

    monkeypatch.setattr(
        client._client.embeddings,
        "create",
        lambda **kwargs: SimpleNamespace(data=[SimpleNamespace(**item) for item in data]),
    )
    with pytest.raises(ValueError, match=match):
        client.embed_query("question")


def test_batches_preserve_order_with_independent_call_and_http_counts(provider_client):
    import json

    def success(request):
        inputs = json.loads(request.content)["input"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [float(value), 0.0]}
                    for i, value in reversed(list(enumerate(inputs)))
                ]
            },
        )

    client = provider_client(success, purpose="build", max_batch_size=2)
    assert client.embed_documents(["1", "2", "3"]) == [
        [1.0, 0.0],
        [2.0, 0.0],
        [3.0, 0.0],
    ]
    snapshot = client.telemetry.snapshot()
    assert (
        snapshot["logical_calls"],
        snapshot["provider_batches"],
        snapshot["http_attempts"],
    ) == (1, 2, 2)
    assert client.embed_documents([]) == []
    assert client.telemetry.snapshot() == snapshot


@pytest.mark.parametrize("purpose", ["document", "candidate", "build"])
def test_proxy_fallback_keeps_timeout_retries_and_http_attempts(monkeypatch, purpose):
    from gustobot.infrastructure.knowledge import embeddings

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:9")

    def response(self, request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    monkeypatch.setattr(embeddings.httpx.HTTPTransport, "handle_request", response)
    with closing(
        OpenAICompatibleEmbeddings(
            model="fixture",
            api_key="test",
            dimension=2,
            purpose=purpose,
            request_timeout=7.0,
        )
    ) as client:
        assert client.embed_query("question") == [1.0, 0.0]
        assert client._client.max_retries == 0 and client._client.timeout == 7.0
        assert client.telemetry.snapshot()["http_attempts"] == 1


def test_other_constructor_errors_propagate_without_proxy_fallback(monkeypatch):
    from gustobot.infrastructure.knowledge import embeddings

    def broken(**kwargs):
        raise ValueError("invalid client settings")

    monkeypatch.setattr(embeddings, "OpenAI", broken)
    with pytest.raises(ValueError, match="invalid client settings"):
        OpenAICompatibleEmbeddings(model="fixture", api_key="test", purpose="candidate")


@pytest.mark.parametrize("purpose", ["document", "candidate", "build"])
def test_provider_timeout_propagates_with_one_actual_attempt(purpose, provider_client):
    attempts = []

    def timed_out(request):
        attempts.append(request)
        raise httpx.ReadTimeout("provider timeout", request=request)

    client = provider_client(timed_out, purpose=purpose, request_timeout=0.25)
    with pytest.raises(APITimeoutError):
        client.embed_query("question")
    assert len(attempts) == 1
    telemetry = client.telemetry.snapshot()
    assert (
        telemetry["logical_calls"]
        == telemetry["provider_batches"]
        == telemetry["http_attempts"]
        == 1
    )


@pytest.mark.asyncio
async def test_async_build_calls_and_threaded_telemetry_preserve_counts(provider_client):
    client = provider_client(
        lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]}),
        purpose="build",
    )
    assert await client.aembed_documents(["first"]) == [[1.0, 0.0]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        vectors = await asyncio.to_thread(lambda: list(pool.map(client.embed_query, ["one"] * 20)))
    assert vectors == [[1.0, 0.0]] * 20
    snapshot = client.telemetry.snapshot()
    assert (
        snapshot["logical_calls"] == snapshot["provider_batches"] == snapshot["http_attempts"] == 21
    )
