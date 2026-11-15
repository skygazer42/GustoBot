"""Shared LightRAG lifecycle and optional dependency behavior without external I/O."""

import asyncio
import builtins
import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
import anyio
from pydantic import ValidationError


def load_service(monkeypatch):
    name = "isolated_lightrag_service"
    path = Path(__file__).parents[1] / "gustobot/application/services/lightrag_service.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime(monkeypatch):
    instances = []
    arguments = []

    async def initialize():
        await asyncio.sleep(0)

    def factory(**kwargs):
        arguments.append(kwargs)
        instance = SimpleNamespace(
            initialize_storages=AsyncMock(side_effect=initialize),
            finalize_storages=AsyncMock(),
            aquery=AsyncMock(return_value="answer"),
            aquery_llm=AsyncMock(
                return_value={
                    "status": "success",
                    "message": "Query processed successfully",
                    "data": {
                        "entities": [],
                        "relationships": [],
                        "chunks": [
                            {
                                "chunk_id": "chunk-1",
                                "content": "evidence",
                                "file_path": "manual.pdf",
                                "reference_id": "1",
                            }
                        ],
                        "references": [{"reference_id": "1", "file_path": "manual.pdf"}],
                    },
                    "metadata": {"query_mode": "mix"},
                    "llm_response": {
                        "content": "answer",
                        "response_iterator": None,
                        "is_streaming": False,
                    },
                }
            ),
            ainsert=AsyncMock(return_value="insert-1"),
            aget_docs_by_track_id=AsyncMock(
                return_value={"doc-1": SimpleNamespace(status="processed", error_msg=None)}
            ),
            aget_docs_by_ids=AsyncMock(
                return_value={"doc-1": SimpleNamespace(status="processed", error_msg=None)}
            ),
        )
        instances.append(instance)
        return instance

    vendor = ModuleType("lightrag")
    vendor.__dict__.update(LightRAG=factory, QueryParam=lambda **kwargs: SimpleNamespace(**kwargs))
    utilities = ModuleType("lightrag.utils")
    utilities.__dict__["EmbeddingFunc"] = lambda **kwargs: SimpleNamespace(**kwargs)
    utilities.__dict__["sanitize_text_for_encoding"] = lambda text: text
    utilities.__dict__["compute_mdhash_id"] = (
        lambda text, prefix: prefix + hashlib.md5(text.encode()).hexdigest()
    )
    shared = ModuleType("lightrag.kg.shared_storage")
    shared.__dict__["initialize_pipeline_status"] = AsyncMock()
    openai = ModuleType("lightrag.llm.openai")
    openai.__dict__.update(
        openai_complete_if_cache=AsyncMock(return_value="answer"),
        openai_embed=SimpleNamespace(func=AsyncMock(return_value=np.ones((1, 4)))),
    )
    prompts = ModuleType("lightrag.prompt")
    prompts.__dict__["PROMPTS"] = {"fail_response": "Cannot answer.[no-context]"}
    domain = ModuleType("gustobot.config.domain")
    domain.__dict__["get_domain_definition"] = lambda: SimpleNamespace(
        id="devices", entity_types={"Device": object()}, document_index_namespace=None
    )
    for name, module in {
        "lightrag": vendor,
        "lightrag.utils": utilities,
        "lightrag.kg.shared_storage": shared,
        "lightrag.llm.openai": openai,
        "lightrag.prompt": prompts,
        "gustobot.config.domain": domain,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return SimpleNamespace(
        module=load_service(monkeypatch),
        vendor=vendor,
        instances=instances,
        arguments=arguments,
        pipeline=shared.__dict__["initialize_pipeline_status"],
        openai=openai,
    )


def test_llm_completion_preserves_vendor_stream(runtime, tmp_path):
    async def chunks():
        yield "first "
        yield "second"

    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        completion = chunks()
        runtime.openai.openai_complete_if_cache.return_value = completion
        result = await service._llm_model_func("device", stream=True)
        assert result is completion
        assert [chunk async for chunk in result] == ["first ", "second"]
        assert runtime.openai.openai_complete_if_cache.await_args.kwargs["stream"] is True
        assert runtime.instances == []

    asyncio.run(run())


def test_llm_completion_rejects_stream_when_not_requested(runtime, tmp_path):
    async def chunks():
        yield "answer"

    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        completion = chunks()
        runtime.openai.openai_complete_if_cache.return_value = completion
        try:
            with pytest.raises(ValueError, match="text"):
                await service._llm_model_func("device", stream=False)
        finally:
            await completion.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("stream", [False, True])
def test_llm_completion_rejects_nontext_payload(runtime, tmp_path, stream):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        runtime.openai.openai_complete_if_cache.return_value = {"content": "answer"}
        with pytest.raises(ValueError, match="text"):
            await service._llm_model_func("device", stream=stream)

    asyncio.run(run())


def test_structured_query_returns_one_vendor_answer_and_retrieved_evidence(runtime, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        request = runtime.module.LightRAGQueryRequest(query="device", mode="mix", top_k=3)
        result = await service.query_structured(request)
        vendor = runtime.instances[0]
        vendor.aquery_llm.assert_awaited_once()
        vendor.aquery.assert_not_awaited()
        assert result.response == "answer"
        assert result.metadata["data"] == vendor.aquery_llm.return_value["data"]
        assert result.metadata["query_mode"] == "mix"
        assert vendor.aquery_llm.await_args.kwargs["param"].stream is False
        assert vendor.aquery_llm.await_args.kwargs["param"].top_k == 3

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["local", "global", "hybrid", "mix"])
def test_structured_graph_query_preserves_vendor_content_only_no_context(runtime, tmp_path, mode):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        content = sys.modules["lightrag.prompt"].PROMPTS["fail_response"]
        vendor.aquery_llm.return_value = {
            "llm_response": {
                "content": content,
                "response_iterator": None,
                "is_streaming": False,
            }
        }
        result = await service.query_structured(
            runtime.module.LightRAGQueryRequest(query="question " * 10, mode=mode)
        )
        assert result.response == content
        assert result.metadata["failure_reason"] == "no_results"
        assert result.metadata["data"] == {}
        vendor.aquery_llm.assert_awaited_once()
        vendor.aquery.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["mix", "naive", "bypass"])
def test_structured_query_does_not_assume_incomplete_payload_is_success(runtime, tmp_path, mode):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        content = (
            "unverified answer"
            if mode == "mix"
            else sys.modules["lightrag.prompt"].PROMPTS["fail_response"]
        )
        vendor.aquery_llm.return_value = {
            "llm_response": {
                "content": content,
                "response_iterator": None,
                "is_streaming": False,
            }
        }
        with pytest.raises(RuntimeError, match="incomplete"):
            await service.query_structured(
                runtime.module.LightRAGQueryRequest(query="device", mode=mode)
            )
        vendor.aquery_llm.assert_awaited_once()
        vendor.aquery.assert_not_awaited()

    asyncio.run(run())


def test_structured_bypass_query_accepts_explicit_success_without_retrieval(runtime, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        vendor.aquery_llm.return_value.update(data={}, metadata={})
        result = await service.query_structured(
            runtime.module.LightRAGQueryRequest(query="device", mode="bypass")
        )
        assert result.response == "answer"
        assert result.metadata["data"] == {}
        assert "failure_reason" not in result.metadata
        vendor.aquery_llm.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("query", ["", " ", "\t\n"])
def test_shared_query_request_rejects_blank_text(runtime, query):
    with pytest.raises(ValidationError):
        runtime.module.LightRAGQueryRequest(query=query)
    assert runtime.instances == []


@pytest.mark.parametrize("case", ["no_results", "failure", "streaming", "cancelled"])
def test_structured_query_preserves_no_results_failure_and_cancellation(runtime, tmp_path, case):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        payload = vendor.aquery_llm.return_value
        request = runtime.module.LightRAGQueryRequest(query="device", mode="mix")
        if case == "no_results":
            payload.update(status="failure", data={}, metadata={"failure_reason": "no_results"})
            payload["llm_response"]["content"] = "No relevant context"
            result = await service.query_structured(request)
            assert result.response == "No relevant context"
            assert result.metadata["data"] == {}
        elif case == "failure":
            payload.update(status="failure", message="provider unavailable", metadata={})
            with pytest.raises(RuntimeError, match="provider unavailable"):
                await service.query_structured(request)
        elif case == "streaming":
            payload["llm_response"].update(content=None, is_streaming=True)
            with pytest.raises(RuntimeError, match="non-streaming"):
                await service.query_structured(request)
        else:
            cancellation = asyncio.CancelledError("cancel query")
            vendor.aquery_llm.side_effect = cancellation
            with pytest.raises(asyncio.CancelledError) as raised:
                await service.query_structured(request)
            assert raised.value is cancellation
        vendor.aquery.assert_not_awaited()
        vendor.finalize_storages.assert_not_awaited()

    asyncio.run(run())


def test_structured_query_rejects_stream_before_initializing_runtime(runtime, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        with pytest.raises(ValueError, match="streaming"):
            await service.query_structured(
                runtime.module.LightRAGQueryRequest(query="device", stream=True)
            )
        assert runtime.instances == []

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["failed", "pending", "processing"])
def test_insert_does_not_report_silent_pipeline_failure_as_success(runtime, tmp_path, failure):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        vendor.aget_docs_by_track_id.return_value = {
            "doc-1": SimpleNamespace(status=failure, error_msg="extraction failed")
        }
        result = await service.insert_documents(["raw source"], file_paths=["manual.pdf"])
        assert (result.success, result.failed) == (0, 1)
        assert "extraction failed" in result.errors[0]
        vendor.ainsert.assert_awaited_once_with("raw source", file_paths="manual.pdf")

    asyncio.run(run())


@pytest.mark.parametrize("duplicate", [False, True])
def test_only_processed_documents_are_counted_as_inserted(runtime, tmp_path, duplicate):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        if duplicate:
            vendor.aget_docs_by_track_id.return_value = {}
        result = await service.insert_documents(["raw source"])
        assert (result.success, result.failed) == (1, 0)
        vendor.ainsert.assert_awaited_once_with("raw source")
        if duplicate:
            vendor.aget_docs_by_ids.assert_awaited_once()
        else:
            vendor.aget_docs_by_ids.assert_not_awaited()

    asyncio.run(run())


def test_duplicate_pending_document_is_not_reported_processed(runtime, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        vendor.aget_docs_by_track_id.return_value = {}
        vendor.aget_docs_by_ids.return_value = {
            "doc-1": SimpleNamespace(status="pending", error_msg=None)
        }
        result = await service.insert_documents(["raw source"])
        assert (result.success, result.failed) == (0, 1)
        assert "pending" in result.errors[0]

    asyncio.run(run())


def test_duplicate_document_identity_uses_vendor_normalization(runtime, monkeypatch, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        vendor.aget_docs_by_track_id.return_value = {}
        normalize = Mock(return_value="normalized source")
        monkeypatch.setattr(sys.modules["lightrag.utils"], "sanitize_text_for_encoding", normalize)
        result = await service.insert_documents(["source"])
        assert result.success == 1
        normalize.assert_called_once_with("source")
        expected_id = "doc-" + hashlib.md5(b"normalized source").hexdigest()
        vendor.aget_docs_by_ids.assert_awaited_once_with(expected_id)

    asyncio.run(run())


def test_missing_document_status_cannot_be_reported_as_processed(runtime, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        vendor.aget_docs_by_track_id.return_value = {}
        vendor.aget_docs_by_ids.return_value = {}
        result = await service.insert_documents(["raw source"])
        assert (result.success, result.failed) == (0, 1)
        assert "status" in result.errors[0]

    asyncio.run(run())


def test_insert_cancellation_propagates_without_closing_shared_runtime(runtime, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        vendor = runtime.instances[0]
        cancellation = asyncio.CancelledError("cancel import")
        vendor.aget_docs_by_track_id.side_effect = cancellation
        with pytest.raises(asyncio.CancelledError) as raised:
            await service.insert_documents(["raw source"])
        assert raised.value is cancellation
        vendor.finalize_storages.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("file_paths", [[], ["first", "second"]])
def test_insert_source_count_is_checked_before_runtime_initialization(
    runtime, tmp_path, file_paths
):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        with pytest.raises(ValueError, match="file_paths"):
            await service.insert_documents(["raw source"], file_paths=file_paths)
        assert runtime.instances == []

    asyncio.run(run())


def test_core_import_does_not_require_lightrag(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "lightrag" or name.startswith("lightrag."):
            raise AssertionError("core import loaded optional LightRAG")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert load_service(monkeypatch).LightRAGService


def test_default_indexes_are_separated_by_domain(runtime, monkeypatch, tmp_path):
    domain_module = sys.modules["gustobot.config.domain"]
    monkeypatch.setattr(runtime.module.settings, "LIGHTRAG_WORKING_DIR", str(tmp_path))
    services = []
    for domain_id, namespace in (("recipes", "."), ("equipment", None), ("generic", None)):
        domain = SimpleNamespace(id=domain_id, document_index_namespace=namespace)
        monkeypatch.setattr(domain_module, "get_domain_definition", lambda: domain)
        monkeypatch.setattr(runtime.module, "_lightrag_service", None)
        services.append(runtime.module.get_lightrag_service())
    assert [Path(service.working_dir) for service in services] == [
        tmp_path,
        tmp_path / "equipment",
        tmp_path / "generic",
    ]
    assert list(tmp_path.iterdir()) == []


def test_explicit_working_directory_is_preserved(runtime, monkeypatch, tmp_path):
    explicit = str(tmp_path / "explicit" / ".." / "chosen")
    service = runtime.module.LightRAGService(working_dir=explicit)
    assert service.working_dir == explicit
    assert list(tmp_path.iterdir()) == []


def test_recipe_importer_rejects_other_domains_before_opening_resources(monkeypatch, capsys):
    script = importlib.import_module("scripts.init_lightrag")
    service_module = importlib.import_module("gustobot.application.services.lightrag_service")
    domain_module = importlib.import_module("gustobot.config.domain")
    constructor = Mock(side_effect=AssertionError("non-recipe importer opened a runtime"))
    importer = AsyncMock(side_effect=AssertionError("non-recipe importer read recipe data"))
    monkeypatch.setattr(service_module, "LightRAGService", constructor)
    monkeypatch.setattr(script, "import_from_json", importer)
    monkeypatch.setattr(
        domain_module,
        "get_domain_definition",
        lambda: SimpleNamespace(id="equipment"),
    )
    monkeypatch.setattr(sys, "argv", ["init_lightrag.py", "--source", "json"])
    with pytest.raises(SystemExit) as raised:
        asyncio.run(script.main())
    assert raised.value.code == 2
    assert "recipe-only" in capsys.readouterr().err
    constructor.assert_not_called()
    importer.assert_not_awaited()


def test_recipe_importer_accepts_recipe_extension_and_owns_runtime(monkeypatch):
    script = importlib.import_module("scripts.init_lightrag")
    service_module = importlib.import_module("gustobot.application.services.lightrag_service")
    domain_module = importlib.import_module("gustobot.config.domain")
    service = SimpleNamespace(
        cleanup=AsyncMock(), working_dir="explicit-index", default_mode="local"
    )
    constructor = Mock(return_value=service)
    importer = AsyncMock(return_value=3)
    monkeypatch.setattr(service_module, "LightRAGService", constructor)
    monkeypatch.setattr(script, "import_from_json", importer)
    monkeypatch.setattr(
        domain_module,
        "get_domain_definition",
        lambda: SimpleNamespace(id="recipes"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "init_lightrag.py",
            "--source",
            "json",
            "--json-path",
            "recipe.json",
            "--working-dir",
            "explicit-index",
        ],
    )
    asyncio.run(script.main())
    constructor.assert_called_once_with(
        working_dir="explicit-index",
        default_mode=service_module.settings.LIGHTRAG_RETRIEVAL_MODE,
        default_top_k=service_module.settings.LIGHTRAG_TOP_K,
    )
    importer.assert_awaited_once_with(service, "recipe.json", limit=None)
    service.cleanup.assert_awaited_once()


def test_concurrent_initialization_and_cleanup_have_one_owner(runtime, tmp_path):
    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await asyncio.gather(service.initialize(), service.initialize())
        assert len(runtime.instances) == 1
        runtime.pipeline.assert_awaited_once()
        await asyncio.gather(service.cleanup(), service.cleanup())
        runtime.instances[0].finalize_storages.assert_awaited_once()
        assert service.rag is None
        assert service.initialized is False

    asyncio.run(run())


@pytest.mark.parametrize("error_type", [ValueError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_initialization_preserves_error_and_can_retry(
    runtime, tmp_path, error_type, cleanup_fails
):
    async def run():
        failure = error_type("pipeline failed")
        runtime.pipeline.side_effect = [failure, None]
        original = runtime.vendor.LightRAG

        def factory(**kwargs):
            instance = original(**kwargs)
            if cleanup_fails:
                instance.finalize_storages.side_effect = RuntimeError("cleanup failed")
            return instance

        runtime.vendor.LightRAG = factory
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        with pytest.raises(error_type) as raised:
            with anyio.fail_after(1):
                await service.initialize()
        assert raised.value is failure
        assert service.rag is None
        assert service.initialized is False
        runtime.instances[0].finalize_storages.assert_awaited_once()
        await service.initialize()
        assert service.initialized is True
        assert len(runtime.instances) == 2
        runtime.instances[1].finalize_storages.side_effect = None
        await service.cleanup()

    asyncio.run(run())


def test_index_dimension_and_domain_types_are_passed_to_runtime(runtime, monkeypatch, tmp_path):
    monkeypatch.delenv("EMBEDDING_DIMENSION", raising=False)
    (tmp_path / "vdb_chunks.json").write_text('{"embedding_dim": 4}', encoding="utf-8")

    async def run():
        service = runtime.module.LightRAGService(working_dir=str(tmp_path))
        await service.initialize()
        assert runtime.arguments[0]["embedding_func"].embedding_dim == 4
        assert runtime.arguments[0]["addon_params"] == {
            "entity_types": ["Device"],
            "language": "Chinese",
        }
        result = await service._embedding_func(["device"])
        assert result.shape == (1, 4)
        runtime.openai.openai_embed.func.assert_awaited_once()
        await service.cleanup()

    asyncio.run(run())


def test_missing_vendor_is_explicit_and_internal_missing_dependency_is_not_hidden(
    runtime, monkeypatch, tmp_path
):
    original = importlib.import_module

    async def run():
        for missing in ("lightrag", "broken_vendor_dependency"):
            failure = ModuleNotFoundError("missing dependency", name=missing)

            def unavailable(name, *args, **kwargs):
                if name == "lightrag":
                    raise failure
                return original(name, *args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(importlib, "import_module", unavailable)
                service = runtime.module.LightRAGService(working_dir=str(tmp_path))
                if missing == "lightrag":
                    with pytest.raises(RuntimeError, match="LightRAG.*not installed"):
                        await service.initialize()
                else:
                    with pytest.raises(ModuleNotFoundError) as raised:
                        await service.initialize()
                    assert raised.value is failure
        assert runtime.instances == []

    asyncio.run(run())
