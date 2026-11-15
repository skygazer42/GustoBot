"""Offline regressions for orchestration state propagation."""

import asyncio
import importlib
from types import SimpleNamespace


def test_text2sql_factory_retry_budget_and_row_limit_reach_nodes(monkeypatch):
    module = importlib.import_module("gustobot.application.agents.text2sql.workflow")
    seen = []

    def node_factory(*args, **kwargs):
        async def node(state):
            seen.append(dict(state))
            return {
                "is_valid": False,
                "retry_count": 1,
                "validation_errors": ["invalid"],
                "steps": [],
            }

        return node

    for name in [
        "create_schema_retrieval_node",
        "create_query_analysis_node",
        "create_sql_generation_node",
        "create_sql_validation_node",
        "create_sql_execution_node",
        "create_visualization_node",
        "create_answer_formatter_node",
    ]:
        monkeypatch.setattr(module, name, node_factory)
    workflow = module.create_text2sql_workflow(object(), "sqlite://", max_retries=0)
    asyncio.run(workflow.ainvoke({"question": "count", "max_rows": 7, "max_retries": None}))
    assert len(seen) == 5
    assert seen[0]["max_rows"] == 7
    assert seen[0]["max_retries"] == 0


def test_text2sql_none_retry_values_use_defaults():
    module = importlib.import_module("gustobot.application.agents.text2sql.workflow")
    assert module._should_execute_or_retry({"retry_count": None, "max_retries": None}) == "retry"


def test_source_provenance_preserves_numeric_zero_identifier():
    from gustobot.application.agents.kb_tools.sources import build_source

    assert build_source({"id": 0, "source": "file.csv"}, "milvus")["document_id"] == "0"


def test_document_reducer_deduplicates_strings_and_preserves_metadata():
    from gustobot.application.agents.utils import reduce_docs

    first = reduce_docs(None, ["same"])
    result = reduce_docs(first, ["same", "new", "new"])
    assert [doc.page_content for doc in result] == ["same", "new"]
    assert len(first) == 1


def test_knowledge_node_closes_its_owned_clients_each_call(monkeypatch):
    module = importlib.import_module("gustobot.application.agents.kb_tools.node")
    calls = []

    class Service:
        async def search(self, **kwargs):
            return [{"id": 0, "content": "source", "score": 0.0}]

        async def close(self):
            calls.append("service_closed")

    class Client:
        async def chat(self, **kwargs):
            return "answer"

        async def close(self):
            calls.append("client_closed")

    monkeypatch.setattr(module, "KnowledgeService", Service)
    monkeypatch.setattr(module, "LLMClient", Client)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(OPENAI_API_KEY="test-key", KB_ENABLE_EXTERNAL_SEARCH=False),
    )
    node = module.create_knowledge_query_node()
    for _ in range(2):
        assert asyncio.run(node({"task": "question"}))["answer"] == "answer"
    assert calls == ["client_closed", "service_closed"] * 2


def test_kb_fallback_preserves_sources_and_closes_service(monkeypatch):
    module = importlib.import_module("gustobot.application.agents.lg_builder")
    monkeypatch.setattr(
        module,
        "get_domain_definition",
        lambda: SimpleNamespace(document_backend="legacy_kb", document_scope="test documents"),
    )
    calls = []
    sources = [{"document_id": "0", "source": "recipe.csv"}]

    class Service:
        async def close(self):
            calls.append("closed")

    def unavailable(**kwargs):
        raise RuntimeError("planner unavailable")

    def knowledge_node(**kwargs):
        async def query(state):
            return {"answer": "answer", "sources": sources}

        return query

    monkeypatch.setattr(module, "ChatOpenAI", lambda **_: object())
    monkeypatch.setattr(module, "KnowledgeService", Service)
    monkeypatch.setattr(module, "create_kb_multi_tool_workflow", unavailable)
    monkeypatch.setattr(module, "create_knowledge_query_node", knowledge_node)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            OPENAI_API_KEY="test-key",
            OPENAI_MODEL="test-model",
            OPENAI_API_BASE="https://example.test",
            KB_TOP_K=3,
            KB_SIMILARITY_THRESHOLD=0.0,
            KB_EXTERNAL_SEARCH_URL=None,
            INGEST_SERVICE_URL=None,
            KB_ENABLE_EXTERNAL_SEARCH=False,
        ),
    )
    state = SimpleNamespace(messages=[SimpleNamespace(content="question")])
    result = asyncio.run(module.create_kb_query(state, config={}))
    assert result["sources"] == sources
    assert result["messages"][0].additional_kwargs["sources"] == sources
    assert calls == ["closed"]
