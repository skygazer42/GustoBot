"""Offline regressions for explicit data contracts and SQL boundaries."""

from pathlib import Path
import asyncio
import importlib.util
from types import SimpleNamespace
from typing import Dict, List, Union
from unittest.mock import Mock
from unittest.mock import AsyncMock

import anyio
import httpx

import pytest


@pytest.fixture
def ingest_types(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "kb_ingest"))
    from kb_service.schemas.ingest import MySQLIngestRequest
    from kb_service.services.mysql_ingest import MySQLIngestor

    return MySQLIngestRequest, MySQLIngestor


def test_mysql_filter_binds_compound_range_and_literal_values(ingest_types):
    request_type, ingestor_type = ingest_types
    request = request_type(
        connection_url="mysql+pymysql://unused",
        table="reports",
        where="(year BETWEEN 0 AND 2025 OR status IN ('new', 'ready')) "
        "AND LOWER(company) LIKE 'o''reilly%' AND deleted IS NULL",
        limit=3,
        extra_metadata={},
    )
    query = ingestor_type.__new__(ingestor_type)._build_query(request)
    compiled = query.compile()
    assert "o'reilly%" not in str(query)
    assert "2025" not in str(query)
    assert set(compiled.params.values()) == {0, 2025, "new", "ready", "o'reilly%", 3}
    assert "BETWEEN" in str(query)
    assert "LOWER" in str(query)


@pytest.mark.parametrize(
    "condition",
    [
        "id = 1; DELETE FROM reports",
        "id IN (SELECT id FROM secrets)",
        "id = 1 -- comment",
        "id = 1 /* comment */",
        "SLEEP(10) = 0",
        "id = @session_value",
        "id = 1 UNION SELECT 2",
        "some_schema.LOWER(company) = 'value'",
        "some_schema.CHAR(65) = 'A'",
    ],
)
def test_mysql_filter_rejects_statements_comments_and_side_effects(ingest_types, condition):
    request_type, ingestor_type = ingest_types
    request = request_type(
        connection_url="mysql+pymysql://unused",
        table="reports",
        where=condition,
        extra_metadata={},
    )
    with pytest.raises(ValueError):
        ingestor_type.__new__(ingestor_type)._build_query(request)


def test_mysql_filter_treats_sql_inside_literal_as_data(ingest_types):
    request_type, ingestor_type = ingest_types
    dangerous_text = "x'; DELETE FROM reports; --"
    request = request_type(
        connection_url="mysql+pymysql://unused",
        table="reports",
        where="name = 'x''; DELETE FROM reports; --'",
        extra_metadata={},
    )
    query = ingestor_type.__new__(ingestor_type)._build_query(request)
    assert dangerous_text in query.compile().params.values()
    assert "DELETE" not in str(query)


def test_mysql_filter_keeps_column_qualification_and_decimal_cast(ingest_types):
    request_type, ingestor_type = ingest_types
    request = request_type(
        connection_url="mysql+pymysql://unused",
        table="reports",
        where="CAST(reports.total AS DECIMAL(10, 2)) >= 0 AND (reports.id = 0 OR NOT (hidden = 1))",
        extra_metadata={},
    )
    query = ingestor_type.__new__(ingestor_type)._build_query(request)
    assert "`reports` . `total`" in str(query)
    assert "DECIMAL ( 10 , 2 )" in str(query)
    assert list(query.compile().params.values()) == [0, 0, 1]


def test_llm_provider_missing_text_is_explicit_failure(ingest_types):
    from kb_service.clients.llm import LLMClient
    from kb_service.core.config import Config
    from openai import OpenAI

    client = LLMClient.__new__(LLMClient)
    client.config = Config(llm_model="test", llm_temperature=0)
    client.openai_client = Mock(
        spec=OpenAI,
        chat=Mock(
            completions=Mock(
                create=Mock(
                    return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
                    )
                )
            )
        ),
    )
    with pytest.raises(ValueError, match="text"):
        client._generate_openai("prompt", "")


def test_mysql_rows_preserve_nested_values_and_zero_identifiers(ingest_types):
    import logging

    import pandas as pd

    from kb_service.core.config import Config

    request_type, ingestor_type = ingest_types
    ingestor = ingestor_type.__new__(ingestor_type)
    ingestor.config = Config()
    captured = []

    def capture_items(items, logger):
        captured.extend(items)
        return len(items)

    ingestor.vector_writer = SimpleNamespace(upsert=capture_items)
    ingestor.logger = logging.getLogger(__name__)
    request = request_type(
        connection_url="mysql+pymysql://unused",
        table="reports",
        mode="flatten",
        id_column="id",
        report_year_field="year",
        extra_metadata={},
    )
    rows = pd.DataFrame([{"id": 0, "year": 0, "tags": [0, 1], "info": {"active": False}}])
    assert ingestor._process_chunk(rows, [], request) == 1
    assert captured[0]["source_id"] == "0"
    assert captured[0]["report_year"] == "0"
    assert captured[0]["original_data"]["tags"] == [0, 1]
    assert captured[0]["original_data"]["info"] == {"active": False}


def test_application_reranker_preserves_zero_score():
    from gustobot.infrastructure.knowledge.reranker import Reranker

    reranker = Reranker.__new__(Reranker)
    documents = [{"id": 0, "content": "answer"}]
    ranked = reranker._process_rerank_results(
        [{"index": 0, "relevance_score": 0.0, "score": 1.0}], documents, 1
    )
    assert ranked == [{"id": 0, "content": "answer", "rerank_score": 0.0}]


def test_knowledge_storage_preserves_zero_document_identity():
    from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService
    from gustobot.infrastructure.knowledge.vector_store import VectorStore
    from langchain_core.documents import Document

    service = KnowledgeService.__new__(KnowledgeService)
    service.vector_store = Mock(spec=VectorStore)
    service.vector_store.add_documents.return_value = True
    result = service._store_documents(
        [Document(page_content="answer", metadata={"id": 0})], [[0.5]]
    )
    assert result["ids"] == ["0_0"]
    assert service.vector_store.add_documents.call_args.kwargs["metadatas"][0]["recipe_id"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("recipe", [{"id": 0, "recipe_id": "fallback"}, {"recipe_id": 0}])
async def test_batch_recipe_preserves_zero_document_identity(monkeypatch, recipe):
    from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService

    service = KnowledgeService.__new__(KnowledgeService)
    add_recipe = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "add_recipe", add_recipe)
    result = await service.add_recipes_batch([recipe])
    assert result == {"success": 1, "error": 0, "total": 1}
    add_recipe.assert_awaited_once_with("0", recipe)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["document", "recipe"])
async def test_knowledge_add_requires_internal_ingestion_statistics(monkeypatch, method):
    from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService

    service = KnowledgeService.__new__(KnowledgeService)
    monkeypatch.setattr(service, "ingest_text", AsyncMock(return_value={}))
    with pytest.raises(KeyError, match="add_count"):
        if method == "document":
            await service.add_document(doc_id="id", title="title", content="text")
        else:
            await service.add_recipe("id", {"name": "title"})


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_lightrag_missing_response_is_visible(monkeypatch, stream):
    from gustobot.application.services.lightrag_service import LightRAGService

    service = LightRAGService()
    monkeypatch.setattr(service, "initialize", AsyncMock())
    service.rag = Mock(aquery=AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="text|response"):
        await service.query("question", stream=stream)


@pytest.mark.asyncio
async def test_knowledge_dependency_closes_inside_cancelled_scope(monkeypatch):
    from gustobot.infrastructure import knowledge
    from gustobot.interfaces.http import knowledge_router

    closed = []

    async def close():
        await anyio.sleep(0)
        closed.append(True)

    service = SimpleNamespace(close=close)
    monkeypatch.setattr(knowledge, "KnowledgeService", lambda: service)
    dependency = knowledge_router.get_knowledge_service()
    assert await dependency.__anext__() is service
    with anyio.CancelScope() as scope:
        scope.cancel()
        await dependency.aclose()
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("close_error", [False, True])
async def test_search_stream_cancel_releases_openai_owner(monkeypatch, close_error):
    from gustobot.application.services.search_service import SearchService
    from openai import AsyncOpenAI

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
            await anyio.sleep(0)
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
async def test_knowledge_cleanup_failure_preserves_request_cancellation(monkeypatch):
    from gustobot.infrastructure import knowledge
    from gustobot.interfaces.http import knowledge_router

    close = AsyncMock(side_effect=RuntimeError("knowledge close failed"))
    service = SimpleNamespace(close=close)
    monkeypatch.setattr(knowledge, "KnowledgeService", lambda: service)
    dependency = knowledge_router.get_knowledge_service()
    assert await dependency.__anext__() is service
    cancellation = asyncio.CancelledError("request cancelled")
    with pytest.raises(asyncio.CancelledError) as failure:
        await dependency.athrow(cancellation)
    assert failure.value is cancellation
    close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["storage", "pipeline", "cancel"])
@pytest.mark.parametrize("close_error", [False, True])
async def test_lightrag_partial_initialization_is_finalized_before_retry(
    monkeypatch, tmp_path, stage, close_error
):
    from gustobot.application.services import lightrag_service

    original = (
        asyncio.CancelledError("initialization cancelled")
        if stage == "cancel"
        else RuntimeError("initialization failed")
    )
    runtime = Mock(
        initialize_storages=AsyncMock(side_effect=original if stage == "storage" else None),
        finalize_storages=AsyncMock(
            side_effect=RuntimeError("storage close failed") if close_error else None
        ),
    )
    factory = Mock(return_value=runtime)
    import lightrag
    from lightrag.kg import shared_storage

    monkeypatch.setattr(lightrag, "LightRAG", factory)
    monkeypatch.setattr(
        shared_storage,
        "initialize_pipeline_status",
        AsyncMock(side_effect=original if stage != "storage" else None),
    )
    service = lightrag_service.LightRAGService(working_dir=str(tmp_path))
    for attempt in range(2):
        with pytest.raises(type(original)) as failure:
            await service.initialize()
        assert failure.value is original
        assert service.rag is None
        assert service.initialized is False
        assert runtime.finalize_storages.await_count == attempt + 1
    assert factory.call_count == 2


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
    from gustobot.application.services.llm_client import LLMClient
    from openai import AuthenticationError, InternalServerError

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
    from gustobot.application.services.llm_client import LLMClient
    from openai import BadRequestError

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
@pytest.mark.parametrize("cancel", [False, True])
async def test_manual_lightrag_owner_preserves_operation_failure(monkeypatch, cancel):
    path = Path(__file__).with_name("test_lightrag_node.py")
    spec = importlib.util.spec_from_file_location("manual_lightrag_node", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failure = (
        asyncio.CancelledError("embedding cancelled") if cancel else ValueError("embedding failed")
    )
    cleanup = AsyncMock(side_effect=RuntimeError("resource close failed"))
    api = SimpleNamespace(
        rag=SimpleNamespace(embedding_func=AsyncMock(side_effect=failure)), cleanup=cleanup
    )
    monkeypatch.setattr(module, "test_initialization", AsyncMock(return_value=api))
    with pytest.raises(type(failure)) as raised:
        await module.test_embedding()
    assert raised.value is failure
    cleanup.assert_awaited_once()


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
    with pytest.raises(ValueError) as caught:
        vector_store.VectorStore()
    assert caught.value is failure


def test_reranker_keeps_unranked_documents_with_duplicate_or_missing_ids():
    from gustobot.infrastructure.knowledge.reranker import Reranker

    documents: List[Dict[str, Union[int, str]]] = [
        {"id": 0, "content": "first"},
        {"id": 0, "content": "second"},
        {"content": "third"},
    ]
    reranker = Reranker.__new__(Reranker)
    result = reranker._process_rerank_results([{"index": 1, "score": 0.0}], documents, 3)
    assert [item["content"] for item in result] == ["second", "first", "third"]


def test_recipe_mapping_preserves_explicit_zero_values():
    from gustobot.infrastructure.knowledge.recipe_import import recipe_json_entry_to_recipe
    from gustobot.infrastructure.knowledge.recipe_kg.recipe_json_parser import _clean_name

    recipe = recipe_json_entry_to_recipe("test", {"类型": 0, "耗时": 0})
    assert recipe["category"] == 0
    assert recipe["time"] == 0
    assert _clean_name(0) == "0"


def test_csv_recovery_requires_content_and_preserves_zero_identifiers(
    ingest_types, monkeypatch, tmp_path
):
    import logging
    from kb_service.services.processor import DataProcessor

    source = tmp_path / "data.csv"
    source.write_text(
        "source_table,source_id,rewritten_content,company_name,report_year,original_data\n"
        "reports,0,answer,,0,{}\n",
        encoding="utf-8",
    )
    processor = DataProcessor.__new__(DataProcessor)
    processor.csv_path = str(source)
    processor.logger = logging.getLogger(__name__)
    writer = Mock()
    processor.vector_writer = writer
    processor.reembed_from_csv()
    item = writer.upsert.call_args.args[0][0]
    assert item["source_id"] == "0"
    assert item["report_year"] == "0"
    assert item["company_name"] == ""
    source.write_text("source_table,source_id\nreports,0\n", encoding="utf-8")
    with pytest.raises(KeyError, match="rewritten_content"):
        processor.reembed_from_csv()


@pytest.mark.parametrize("field,value", [("RERANK_TOP_N", 0), ("RERANK_MODEL", "")])
def test_enabled_reranker_rejects_invalid_required_configuration(monkeypatch, field, value):
    from gustobot.infrastructure.knowledge import reranker

    monkeypatch.setattr(reranker.settings, "RERANK_ENABLED", True)
    monkeypatch.setattr(reranker.settings, field, value)
    with pytest.raises(ValueError):
        reranker.Reranker()
