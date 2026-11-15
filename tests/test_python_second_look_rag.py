"""Offline behavior regressions from the independent Agent/RAG review."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
import pytest


@pytest.mark.asyncio
async def test_missing_knowledge_question_does_not_acquire_clients(monkeypatch):
    from gustobot.application.agents.kb_tools import node as module

    service = Mock(side_effect=AssertionError("must validate before resource acquisition"))
    client = Mock(side_effect=AssertionError("must validate before resource acquisition"))
    monkeypatch.setattr(module, "KnowledgeService", service)
    monkeypatch.setattr(module, "LLMClient", client)
    result = await module.create_knowledge_query_node()({"steps": ["router"]})
    assert result["metadata"]["reason"] == "missing_question"
    assert result["steps"] == ["router", "knowledge_query"]
    service.assert_not_called()
    client.assert_not_called()


@pytest.mark.asyncio
async def test_knowledge_result_requires_content_instead_of_fabricating_context():
    from gustobot.application.agents.kb_tools import node as module

    class Service:
        async def search(self, query, *, top_k=None, similarity_threshold=None, filter_expr=None):
            return [{"id": "broken", "score": 0.5}]

    class Client:
        async def chat(self, *, system_prompt, user_message, temperature=0.2):
            raise AssertionError("invalid internal document must fail before generation")

    with pytest.raises(KeyError, match="content"):
        await module.create_knowledge_query_node(Service(), Client())({"task": "recipe"})


@pytest.mark.asyncio
async def test_schema_retrieval_preserves_database_failure(monkeypatch):
    module = importlib.import_module(
        "gustobot.application.agents.text2sql.components.schema_retrieval.node"
    )

    failure = RuntimeError("database unavailable")

    def unavailable(connection_string):
        raise failure

    monkeypatch.setattr(module, "_retrieve_schema", unavailable)
    with pytest.raises(RuntimeError) as caught:
        await module.create_schema_retrieval_node("sqlite://")({"question": "recipes"})
    assert caught.value is failure


@pytest.mark.asyncio
async def test_sql_generation_preserves_provider_failure():
    module = importlib.import_module(
        "gustobot.application.agents.text2sql.components.sql_generation.node"
    )

    failure = RuntimeError("model unavailable")

    async def unavailable(prompt):
        raise failure

    llm = Mock()
    llm.with_config.return_value = RunnableLambda(unavailable)
    with pytest.raises(RuntimeError) as caught:
        await module.create_sql_generation_node(llm)(
            {
                "question": "recipes",
                "schema_context": {"tables": [{"table_name": "recipes", "columns": []}]},
            }
        )
    assert caught.value is failure


@pytest.mark.asyncio
async def test_sql_validation_does_not_turn_internal_failure_into_retry(monkeypatch):
    module = importlib.import_module(
        "gustobot.application.agents.text2sql.components.sql_validation.node"
    )

    failure = RuntimeError("validator implementation failure")
    monkeypatch.setattr(module, "validate_sql_syntax", Mock(side_effect=failure))
    with pytest.raises(RuntimeError) as caught:
        await module.create_sql_validation_node()({"sql_statement": "SELECT 1"})
    assert caught.value is failure


@pytest.fixture
def kb_workflow(monkeypatch):
    module = importlib.import_module("gustobot.application.agents.kb_tools.workflow")
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            KB_TOP_K=1,
            KB_SIMILARITY_THRESHOLD=0.0,
            KB_ENABLE_EXTERNAL_SEARCH=False,
            INGEST_SERVICE_URL="http://ingest",
            KB_EXTERNAL_SEARCH_URL="http://external/search",
            KB_EXTERNAL_SEARCH_TIMEOUT=5,
            KB_POSTGRES_SIMILARITY_THRESHOLD=0.1,
            KB_POSTGRES_RERANK_THRESHOLD=0.0,
        ),
    )

    def build(service, *, tools=("milvus",), route="local", allow_external=False):
        class Model:
            def with_structured_output(self, schema, *, method):
                if schema is module.KBGuardrailsDecision:
                    return RunnableLambda(lambda _: schema(decision="proceed"))
                return RunnableLambda(
                    lambda _: schema(route=route, rationale="lookup", tools=list(tools))
                )

            async def ainvoke(self, messages):
                return AIMessage(content="retrieved fact")

        return module.create_kb_multi_tool_workflow(Model(), service, allow_external=allow_external)

    return module, build


@pytest.fixture
def search_response(monkeypatch, kb_workflow):
    module, _ = kb_workflow

    def configure(status, body):
        class Response:
            def __init__(self):
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def json(self):
                return body

            async def text(self):
                return "search unavailable"

        response = Response()

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def post(self, url, *, json):
                return response

        monkeypatch.setattr(module.aiohttp, "ClientSession", lambda **_: Session())

    return configure


@pytest.mark.asyncio
async def test_kb_all_search_failures_are_visible(kb_workflow):
    _, build = kb_workflow

    class Service:
        reranker = SimpleNamespace(enabled=False)

        async def search(self, **kwargs):
            raise RuntimeError("milvus unavailable")

    with pytest.raises(RuntimeError, match="milvus unavailable"):
        await build(Service()).ainvoke({"question": "dish history", "history": []})


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["postgres", "external"])
@pytest.mark.parametrize("status,body", [(503, {}), (200, {"results": None}), (200, {})])
async def test_kb_failed_http_search_is_not_a_normal_empty_result(
    kb_workflow, search_response, tool, status, body
):
    _, build = kb_workflow
    search_response(status, body)
    service = SimpleNamespace(reranker=SimpleNamespace(enabled=False))
    workflow = build(
        service,
        tools=("postgres",),
        route="external" if tool == "external" else "local",
        allow_external=tool == "external",
    )
    with pytest.raises(RuntimeError, match="(?i)postgres|external"):
        await workflow.ainvoke({"question": "dish history", "history": []})


@pytest.mark.asyncio
async def test_kb_postgres_failure_keeps_successful_milvus_results(kb_workflow, search_response):
    _, build = kb_workflow
    search_response(503, {})

    class Service:
        reranker = SimpleNamespace(enabled=False)

        async def search(self, **kwargs):
            return [{"content": "retrieved fact", "source": "recipes.csv"}]

    result = await build(Service(), tools=("postgres", "milvus")).ainvoke(
        {"question": "dish history", "history": []}
    )
    assert result["answer"] == "retrieved fact"
    assert result["sources"][0]["source"] == "recipes.csv"


@pytest.mark.asyncio
async def test_kb_successful_zero_matches_remains_a_normal_result(kb_workflow):
    _, build = kb_workflow

    class Service:
        reranker = SimpleNamespace(enabled=False)

        async def search(self, **kwargs):
            return []

    result = await build(Service()).ainvoke({"question": "dish history", "history": []})
    assert "暂未找到相关记载" in result["answer"]
    assert result["sources"] == []


@pytest.mark.asyncio
async def test_kb_internal_document_requires_content(kb_workflow):
    _, build = kb_workflow

    class Service:
        reranker = SimpleNamespace(enabled=False)

        async def search(self, **kwargs):
            return [{"id": "broken", "score": 0.5}]

    with pytest.raises(KeyError, match="content"):
        await build(Service()).ainvoke({"question": "dish history", "history": []})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document", [{"content": "fact"}, {"content": "fact", "similarity": "bad"}]
)
async def test_kb_postgres_requires_real_numeric_similarity(kb_workflow, search_response, document):
    _, build = kb_workflow
    search_response(200, {"results": [document]})
    service = SimpleNamespace(reranker=SimpleNamespace(enabled=False))
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        await build(service, tools=("postgres",)).ainvoke(
            {"question": "dish history", "history": []}
        )


@pytest.mark.asyncio
async def test_kb_reranker_fallback_preserves_real_similarity(kb_workflow, search_response):
    module, build = kb_workflow
    module.settings.KB_POSTGRES_RERANK_THRESHOLD = 0.8
    search_response(200, {"results": [{"content": "fact", "similarity": 0.9}]})

    class Reranker:
        enabled = True

        async def rerank(self, question, documents, top_k):
            return documents[:top_k]

    service = SimpleNamespace(reranker=Reranker())
    result = await build(service, tools=("postgres",)).ainvoke(
        {"question": "dish history", "history": []}
    )
    assert result["answer"] == "retrieved fact"


@pytest.mark.asyncio
async def test_image_encoding_failure_closes_all_owned_images(monkeypatch, tmp_path):
    module = importlib.import_module("gustobot.application.agents.lg_builder")
    image_path = tmp_path / "image.png"
    image_path.touch()
    source, resized, converted = MagicMock(), MagicMock(), MagicMock()
    for image in (source, resized, converted):
        image.__enter__.return_value = image
    source.size = (2048, 1024)
    source.resize.return_value = resized
    resized.mode = "RGBA"
    resized.convert.return_value = converted
    converted.save.side_effect = RuntimeError("encoder failed")
    monkeypatch.setattr(module.Image, "open", Mock(return_value=source))
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            VISION_API_KEY="test-key", VISION_BASE_URL="http://vision", VISION_MODEL="test"
        ),
    )

    result = await module.create_image_query(
        SimpleNamespace(messages=[]), config={"configurable": {"image_path": str(image_path)}}
    )

    assert "无法查看" in result["messages"][0].content
    for image in (source, resized, converted):
        image.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_knowledge_reranker_fallback_uses_measured_vector_score(monkeypatch):
    module = importlib.import_module("gustobot.infrastructure.knowledge.knowledge_service")
    documents = [
        {"content": "vector match", "score": 0.9},
        {"content": "weak vector match", "score": 0.1},
        {"content": "low rerank score", "score": 0.9, "rerank_score": 0.1},
    ]
    service = module.KnowledgeService.__new__(module.KnowledgeService)
    service.embedder = SimpleNamespace(embed_query=Mock(return_value=[1.0]))
    service.vector_store = SimpleNamespace(search=Mock(return_value=documents))
    service.reranker = SimpleNamespace(enabled=True, rerank=AsyncMock(return_value=documents))
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(RERANK_MAX_CANDIDATES=3, KB_RERANK_SCORE_THRESHOLD=0.5),
    )

    result = await service.search(
        "recipe", top_k=3, similarity_threshold=0.5, filter_by_similarity=False
    )

    assert result == [documents[0]]


@pytest.mark.asyncio
@pytest.mark.parametrize("class_name", ["RedisSemanticCache", "RedisConversationHistory"])
@pytest.mark.parametrize("borrowed", [True, False])
async def test_redis_adapters_close_only_owned_clients(monkeypatch, class_name, borrowed):
    module = importlib.import_module("gustobot.application.services.redis_cache")
    client = MagicMock()
    client.__bool__.return_value = False
    client.aclose = AsyncMock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(module.Redis, "from_url", factory)

    adapter = getattr(module, class_name)(redis_client=client if borrowed else None)
    await adapter.close()

    if borrowed:
        factory.assert_not_called()
        client.aclose.assert_not_awaited()
    else:
        factory.assert_called_once()
        client.aclose.assert_awaited_once()
