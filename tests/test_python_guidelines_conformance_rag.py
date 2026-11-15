"""Offline contracts for the second Agent/RAG conformance pass."""

import asyncio
import importlib

import pytest


@pytest.mark.parametrize("response", [None, {"decision": "unknown"}])
def test_additional_guardrails_rejects_invalid_llm_response(monkeypatch, response):
    from types import SimpleNamespace

    from langchain_core.runnables import RunnableLambda
    from pydantic import ValidationError

    module = importlib.import_module("gustobot.application.agents.lg_builder")

    class Model:
        def with_structured_output(self, schema, *, method):
            return RunnableLambda(lambda _: response)

        async def ainvoke(self, messages):
            pytest.fail("Invalid guardrails must not allow answer generation")

    monkeypatch.setattr(module, "ChatOpenAI", lambda **_: Model())
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(OPENAI_API_KEY="key", OPENAI_MODEL="model", OPENAI_API_BASE=None),
    )
    state = module.AgentState(messages=[])
    with pytest.raises(ValidationError):
        asyncio.run(module.get_additional_info(state, config={}))


@pytest.mark.parametrize(
    ("path_key", "expected"),
    [("image_path", "create_image_query"), ("file_path", "create_file_query")],
)
def test_route_query_uses_actual_runnable_attachment_config(path_key, expected):
    module = importlib.import_module("gustobot.application.agents.lg_builder")
    state = module.AgentState(messages=[])
    assert module.route_query(state, config={"configurable": {path_key: "upload"}}) == expected


def test_kb_workflow_preserves_multimodal_answer_text(monkeypatch):
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    module = importlib.import_module("gustobot.application.agents.kb_tools.workflow")

    class Model:
        def with_structured_output(self, schema, *, method):
            if schema is module.KBGuardrailsDecision:
                return RunnableLambda(lambda _: schema(decision="proceed"))
            return RunnableLambda(
                lambda _: schema(route="local", rationale="lookup", tools=["milvus"])
            )

        async def ainvoke(self, messages):
            return AIMessage(content=[{"type": "text", "text": "retrieved fact"}])

    class Service:
        reranker = SimpleNamespace(enabled=False)

        async def search(self, **kwargs):
            return [{"content": "retrieved fact", "source": "recipes.csv"}]

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            KB_TOP_K=1,
            KB_SIMILARITY_THRESHOLD=0.0,
            KB_ENABLE_EXTERNAL_SEARCH=False,
            INGEST_SERVICE_URL=None,
            KB_EXTERNAL_SEARCH_URL=None,
            KB_EXTERNAL_SEARCH_TIMEOUT=5,
        ),
    )
    workflow = module.create_kb_multi_tool_workflow(Model(), Service())
    result = asyncio.run(workflow.ainvoke({"question": "dish history", "history": []}))
    assert result["answer"] == "retrieved fact"


def test_light_rag_completion_rejects_nontext_provider_response(monkeypatch):
    module = importlib.import_module("gustobot.application.services.lightrag_service")

    async def complete(**kwargs):
        return 0

    monkeypatch.setattr(
        importlib.import_module("lightrag.llm.openai"), "openai_complete_if_cache", complete
    )
    client = module.LightRAGService()
    with pytest.raises(ValueError, match="text"):
        asyncio.run(client._llm_model_func("question"))


def test_multimodal_user_message_preserves_text_blocks():
    from langchain_core.messages import HumanMessage

    from gustobot.application.agents.utils import message_text

    message = HumanMessage(
        content=[
            {"type": "text", "text": "How to cook "},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            {"type": "text", "text": "this dish?"},
        ]
    )
    assert message_text(message) == "How to cook this dish?"


@pytest.mark.parametrize(
    ("table", "missing"),
    [
        ({"columns": []}, "table_name"),
        ({"table_name": "recipes", "columns": [{"data_type": "INTEGER"}]}, "column_name"),
        ({"table_name": "recipes", "columns": [{"column_name": "id"}]}, "data_type"),
    ],
)
def test_sql_prompt_requires_real_schema_identifiers(table, missing):
    module = importlib.import_module(
        "gustobot.application.agents.text2sql.components." "sql_generation.prompts"
    )
    with pytest.raises(KeyError, match=missing):
        module.format_schema_as_text({"tables": [table]})


@pytest.mark.parametrize(
    ("phase", "error_type", "close_fails"),
    [
        ("storage", RuntimeError, False),
        ("pipeline", RuntimeError, False),
        ("pipeline", asyncio.CancelledError, False),
        ("pipeline", asyncio.CancelledError, True),
    ],
)
@pytest.mark.asyncio
async def test_light_rag_partial_initialization_releases_runtime(
    monkeypatch, tmp_path, phase, error_type, close_fails
):
    module = importlib.import_module("gustobot.application.services.lightrag_service")
    released = []

    class Storage:
        def __init__(self, **kwargs):
            pass

        async def initialize_storages(self):
            if phase == "storage":
                raise error_type("setup failed")

        async def finalize_storages(self):
            released.append(True)
            if close_fails:
                raise RuntimeError("close failed")

    async def pipeline():
        raise error_type("setup failed")

    monkeypatch.setattr(importlib.import_module("lightrag"), "LightRAG", Storage)
    monkeypatch.setattr(
        importlib.import_module("lightrag.kg.shared_storage"),
        "initialize_pipeline_status",
        pipeline,
    )
    client = module.LightRAGService(working_dir=str(tmp_path))
    with pytest.raises(error_type, match="setup failed"):
        await client.initialize()
    assert released == [True]
    assert client.rag is None
    assert client.initialized is False


def test_light_rag_cleanup_completes_inside_cancelled_scope():
    import anyio

    module = importlib.import_module("gustobot.application.services.lightrag_service")
    released = []

    class Storage:
        async def finalize_storages(self):
            await anyio.sleep(0)
            released.append(True)

    client = module.LightRAGService()
    client.rag = Storage()
    client.initialized = True

    async def run():
        with anyio.CancelScope() as scope:
            scope.cancel()
            await client.cleanup()

    asyncio.run(run())
    assert released == [True]
    assert client.rag is None
    assert client.initialized is False


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("close_fails", [False, True])
@pytest.mark.asyncio
async def test_owned_knowledge_client_keeps_query_failure(monkeypatch, error_type, close_fails):
    from types import SimpleNamespace

    import anyio

    module = importlib.import_module("gustobot.application.agents.kb_tools.node")
    released = []

    class Service:
        async def search(self, **kwargs):
            raise error_type("query failed")

        async def close(self):
            await anyio.sleep(0)
            released.append(True)
            if close_fails:
                raise RuntimeError("close failed")

    monkeypatch.setattr(module, "KnowledgeService", Service)
    monkeypatch.setattr(module, "settings", SimpleNamespace(OPENAI_API_KEY=None))
    node = module.create_knowledge_query_node()
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError, match="query failed"):
            await node({"task": "recipe"})
    else:
        result = await node({"task": "recipe"})
        assert result["metadata"]["reason"] == "search_failure"
        assert result["metadata"]["error"] == "query failed"
    assert released == [True]


@pytest.mark.parametrize("response", [None, []])
def test_light_rag_query_requires_text_response(response):
    module = importlib.import_module("gustobot.application.services.lightrag_service")

    class Storage:
        async def aquery(self, query, **kwargs):
            return response

    client = module.LightRAGService()
    client.rag = Storage()
    client.initialized = True
    client.default_mode = "hybrid"
    client.default_top_k = 1
    with pytest.raises(RuntimeError, match="text"):
        asyncio.run(client.query("recipe"))


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_light_rag_node_leaves_shared_service_open_on_query_error(monkeypatch, error_type):
    module = importlib.import_module("gustobot.application.agents.lg_builder")
    released = []

    class Client:
        async def query(self, query, *, stream=False):
            raise error_type("query failed")

        async def cleanup(self):
            released.append(True)
            raise RuntimeError("close failed")

    monkeypatch.setattr(module, "get_lightrag_service", Client)
    from langchain_core.messages import HumanMessage

    state = module.AgentState(
        messages=[HumanMessage(content="recipe")], router=module.Router(type="graphrag-query")
    )
    with pytest.raises(error_type, match="query failed"):
        await module.create_research_plan(state, config={})
    assert released == []


@pytest.mark.parametrize("entrypoint", ["create_file_query", "create_kb_query"])
@pytest.mark.asyncio
async def test_knowledge_entrypoints_keep_cancellation_when_owned_close_fails(
    monkeypatch, tmp_path, entrypoint
):
    from types import SimpleNamespace

    import anyio
    from langchain_core.messages import HumanMessage

    module = importlib.import_module("gustobot.application.agents.lg_builder")
    monkeypatch.setattr(
        module,
        "get_domain_definition",
        lambda: SimpleNamespace(document_backend="legacy_kb", document_scope="test documents"),
    )
    released = []

    class Service:
        async def add_document(self, **kwargs):
            raise asyncio.CancelledError("operation cancelled")

        async def close(self):
            await anyio.sleep(0)
            released.append(True)
            raise RuntimeError("close failed")

    def cancel(**kwargs):
        raise asyncio.CancelledError("operation cancelled")

    monkeypatch.setattr(module, "KnowledgeService", Service)
    monkeypatch.setattr(module, "ChatOpenAI", lambda **_: object())
    monkeypatch.setattr(module, "create_kb_multi_tool_workflow", cancel)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            INGEST_SERVICE_URL=None,
            FILE_UPLOAD_MAX_MB=1,
            OPENAI_API_KEY="key",
            OPENAI_MODEL="model",
            OPENAI_API_BASE=None,
            KB_TOP_K=1,
            KB_SIMILARITY_THRESHOLD=0.0,
            KB_EXTERNAL_SEARCH_URL=None,
            KB_ENABLE_EXTERNAL_SEARCH=False,
        ),
    )
    file_path = tmp_path / "recipe.txt"
    file_path.write_text("recipe", encoding="utf-8")
    config = {"configurable": {"file_path": str(file_path)}}
    state = SimpleNamespace(messages=[HumanMessage(content="recipe")])
    with pytest.raises(asyncio.CancelledError, match="operation cancelled"):
        await getattr(module, entrypoint)(state, config=config)
    assert released == [True]
