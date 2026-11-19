"""Concurrent first requests must share one application-owned client."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from gustobot.application.services import knowledge_runtime as runtime


@pytest.mark.parametrize("kind", ["graph", "documents"])
def test_concurrent_first_requests_create_one_client(monkeypatch, kind):
    barrier = threading.Barrier(4)
    created = []

    class Client:
        def __init__(self, *args, **kwargs):
            created.append(self)
            time.sleep(0.05)

    monkeypatch.setattr(runtime, "_graph", None)
    monkeypatch.setattr(runtime, "_documents", None)
    monkeypatch.setattr(runtime.settings, "NEO4J_PASSWORD", "isolated-fixture")
    monkeypatch.setattr("gustobot.infrastructure.knowledge.graph_store.Neo4jGraphStore", Client)
    monkeypatch.setattr(
        "gustobot.infrastructure.knowledge.knowledge_service.KnowledgeService", Client
    )
    getter = runtime.get_graph_store if kind == "graph" else runtime.get_document_service

    def first_request():
        barrier.wait(timeout=5)
        return getter()

    with ThreadPoolExecutor(max_workers=4) as workers:
        clients = list(workers.map(lambda _: first_request(), range(4)))
    assert len(created) == 1
    assert all(client is clients[0] for client in clients)


def test_semantic_index_runtime_factory_is_lazy_and_matches_model(monkeypatch):
    from gustobot.config.domain import get_domain_definition

    configured = runtime.settings.model_copy(
        update={"SEMANTIC_EMBEDDING_REVISION": "fixture-deploy-1"}
    )
    monkeypatch.setattr(runtime, "settings", configured)

    def forbidden():
        raise AssertionError("Constructing a builder must not connect to services")

    monkeypatch.setattr(runtime, "get_graph_store", forbidden)
    builder = runtime.create_semantic_indexing_service()
    scope = builder.scope("entity")
    model = get_domain_definition().semantic_model
    assert model is not None
    assert scope.ontology_fingerprint == model.fingerprint
    assert scope.embedding_fingerprint == builder.scope("concept").embedding_fingerprint


def test_linking_activation_requires_an_explicit_embedding_revision(monkeypatch):
    configured = runtime.settings.model_copy(
        update={"SEMANTIC_LINKING_MODE": "on", "SEMANTIC_EMBEDDING_REVISION": ""}
    )
    monkeypatch.setattr(runtime, "settings", configured)
    monkeypatch.setattr(runtime, "_linker", None, raising=False)
    with pytest.raises(ValueError, match="revision|修订"):
        runtime.get_entity_linker()


def test_linking_off_does_not_require_embedding_credentials_or_revision(monkeypatch):
    configured = runtime.settings.model_copy(
        update={
            "SEMANTIC_LINKING_MODE": "off",
            "SEMANTIC_EMBEDDING_REVISION": "",
            "EMBEDDING_API_KEY": None,
        }
    )
    monkeypatch.setattr(runtime, "settings", configured)
    monkeypatch.setattr(runtime, "_linker", None, raising=False)
    assert runtime.get_entity_linker() is None


@pytest.mark.asyncio
async def test_cleanup_closes_candidate_store_and_both_embedding_purposes(monkeypatch):
    closed = []

    class Client:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    for name in ("_graph", "_documents", "_model"):
        monkeypatch.setattr(runtime, name, None)
    monkeypatch.setattr(runtime, "_candidates", Client("store"), raising=False)
    monkeypatch.setattr(runtime, "_candidate_embeddings", Client("candidate"), raising=False)
    monkeypatch.setattr(runtime, "_build_embeddings", Client("build"), raising=False)
    await runtime.cleanup_runtime()
    assert set(closed) == {"store", "candidate", "build"}


@pytest.fixture
def chat_provider_server():
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            name = body["tools"][0]["function"]["name"]
            content = json.dumps(
                {
                    "id": "fixture-response",
                    "object": "chat.completion",
                    "model": "fixture",
                    "created": 0,
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "fixture-tool",
                                        "type": "function",
                                        "function": {
                                            "name": name,
                                            "arguments": json.dumps({"documents": True}),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 11, "total_tokens": 18},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive(), "Fixture provider thread did not stop"


@pytest.mark.asyncio
async def test_actual_runtime_chat_transport_records_requests_and_provider_usage(
    monkeypatch, chat_provider_server
):
    from gustobot.application.services.knowledge_query import SemanticQuestionPlan
    from gustobot.infrastructure.knowledge.request_telemetry import (
        capture_request_trace,
        provider_phase,
    )

    monkeypatch.setattr(runtime, "_model", None)
    configured = runtime.settings.model_copy(
        update={
            "LLM_API_KEY": "isolated-fixture",
            "LLM_BASE_URL": f"http://127.0.0.1:{chat_provider_server.server_port}/v1",
            "LLM_MODEL": "fixture",
        }
    )
    monkeypatch.setattr(runtime, "settings", configured)
    try:
        model = runtime.get_model()
        assert model is not None
        with capture_request_trace() as trace, provider_phase("analysis"):
            result = await model.with_structured_output(
                SemanticQuestionPlan, method="function_calling"
            ).ainvoke("只查原文")
        assert isinstance(result, SemanticQuestionPlan)
        assert result.documents is True
        calls = trace.snapshot()["analysis"]
        assert calls["http_attempts"] == calls["provider_batches"] == 1
        assert calls["input_tokens"] == 7 and calls["output_tokens"] == 11
    finally:
        await runtime.cleanup_runtime()


@pytest.mark.asyncio
async def test_failed_model_construction_closes_both_instrumented_transports(monkeypatch):
    import httpx

    closed = []

    class SyncClient:
        def __init__(self, **kwargs):
            pass

        def close(self):
            closed.append("sync")

    class AsyncClient:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            closed.append("async")

    def invalid_model(**kwargs):
        raise ValueError("fixture model configuration rejected")

    monkeypatch.setattr(httpx, "Client", SyncClient)
    monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(runtime, "ChatOpenAI", invalid_model)
    monkeypatch.setattr(runtime, "_model", None)
    monkeypatch.setattr(
        runtime, "settings", runtime.settings.model_copy(update={"LLM_API_KEY": "fixture"})
    )
    with pytest.raises(ValueError, match="fixture model"):
        runtime.get_model()
    assert set(closed) == {"sync", "async"}


def test_offline_candidate_build_has_distinct_client_budget_from_online_ann(monkeypatch):
    calls = []

    class Store:
        def __init__(self, **options):
            calls.append(options)

    monkeypatch.setattr(runtime, "_candidates", None)
    monkeypatch.setattr(runtime, "_build_candidates", None, raising=False)
    monkeypatch.setattr(
        runtime,
        "settings",
        runtime.settings.model_copy(update={"SEMANTIC_EMBEDDING_REVISION": "fixture-r1"}),
    )
    monkeypatch.setattr(
        "gustobot.infrastructure.knowledge.semantic_index.SemanticCandidateStore", Store
    )
    online, build = runtime.get_candidate_store(), runtime.get_build_candidate_store()
    assert online is not build
    assert calls[0]["timeout"] == 1.0
    assert calls[1]["timeout"] == 30.0
    assert calls[0]["embedding_fingerprint"] == calls[1]["embedding_fingerprint"]
