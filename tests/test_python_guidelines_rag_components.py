"""Offline regressions for graph state and query contracts."""

import asyncio
import importlib


PREFIX = "gustobot.application.agents.text2sql.components"


def test_sql_execution_rejects_nonpositive_row_limit_without_query(monkeypatch):
    module = importlib.import_module(f"{PREFIX}.sql_execution.node")
    calls = []

    async def query(*args, **kwargs):
        calls.append(args)
        return []

    monkeypatch.setattr(module, "_execute_sql_query", query)
    state = {"sql_statement": "SELECT 1", "is_valid": True, "max_rows": 0}
    result = asyncio.run(module.create_sql_execution_node("sqlite://")(state))
    assert result["execution_error"]
    assert not calls


def test_lightrag_history_is_fresh_for_each_call(monkeypatch):
    module = importlib.import_module("gustobot.application.services.lightrag_service")
    lengths = []

    async def complete(**kwargs):
        history = kwargs["history_messages"]
        lengths.append(len(history))
        history.append({"role": "user", "content": "test"})
        return "answer"

    monkeypatch.setattr(
        importlib.import_module("lightrag.llm.openai"), "openai_complete_if_cache", complete
    )
    client = module.LightRAGService()
    asyncio.run(client._llm_model_func("first"))
    asyncio.run(client._llm_model_func("second"))
    assert lengths == [0, 0]


def test_lightrag_cleanup_finalizes_storage_once():
    module = importlib.import_module("gustobot.application.services.lightrag_service")
    calls = []

    class Storage:
        async def finalize_storages(self):
            calls.append("finalize")

    client = module.LightRAGService()
    client.rag = Storage()
    client.initialized = True
    asyncio.run(client.cleanup())
    asyncio.run(client.cleanup())
    assert calls == ["finalize"]
    assert client.rag is None
    assert client.initialized is False
