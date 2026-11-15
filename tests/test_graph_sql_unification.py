"""Graph retrieval shares LightRAG; SQL uses its own explicit database metadata."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import create_engine, text

from gustobot.application.agents import lg_builder, lg_prompts
from gustobot.application.agents.lg_states import AgentState, Router
from gustobot.application.agents.text2sql.components.schema_retrieval import node as schema
from gustobot.application.agents.text2sql import create_text2sql_workflow
from gustobot.domain.knowledge import DomainDefinition


@pytest.mark.parametrize("profile", ["recipes", "equipment"])
@pytest.mark.asyncio
async def test_every_domain_graph_route_uses_shared_lightrag(profile, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    domain = DomainDefinition.model_validate_json(
        (root / "gustobot/config/domains" / f"{profile}.json").read_text(encoding="utf-8")
    )
    monkeypatch.setattr(lg_builder, "get_domain_definition", lambda: domain)
    service = SimpleNamespace(query=AsyncMock(return_value="来自共享索引的实体关系"))
    monkeypatch.setattr(lg_builder, "get_lightrag_service", lambda: service)
    monkeypatch.setattr(lg_builder, "ChatOpenAI", Mock(side_effect=AssertionError("旧图模型")))
    state = AgentState(
        messages=[HumanMessage(content="对象之间有什么关系？")],
        router=Router(type="graphrag-query"),
    )
    result = await lg_builder.create_research_plan(state, config={})
    assert result["messages"][0].content == "来自共享索引的实体关系"
    service.query.assert_awaited_once_with("对象之间有什么关系？", stream=False)


@pytest.mark.parametrize("enabled,url", [(False, None), (True, None), (False, "sqlite://")])
@pytest.mark.asyncio
async def test_sql_route_requires_domain_and_explicit_database(enabled, url, monkeypatch):
    domain = SimpleNamespace(
        sql_enabled=enabled, sql_keywords=["统计"], graph_keywords=[], document_keywords=[]
    )
    monkeypatch.setattr(lg_builder, "get_domain_definition", lambda: domain)
    monkeypatch.setattr(lg_builder.settings, "SQL_DATABASE_URL", url, raising=False)
    monkeypatch.setattr(lg_builder, "get_lightrag_service", Mock(side_effect=AssertionError("SQL")))
    assert lg_builder._heuristic_router("统计数量") is None
    state = AgentState(
        messages=[HumanMessage(content="统计数量")], router=Router(type="text2sql-query")
    )
    with pytest.raises(RuntimeError, match="SQL"):
        await lg_builder.create_research_plan(state, config={})


@pytest.mark.parametrize(
    "enabled,url", [(False, None), (True, None), (False, "sqlite://"), (True, "sqlite://")]
)
@pytest.mark.parametrize(
    "question,fallback", [("统计设备数量", "kb-query"), ("统计部件数量", "graphrag-query")]
)
@pytest.mark.asyncio
async def test_model_sql_route_respects_both_configuration_switches(
    enabled, url, question, fallback, monkeypatch
):
    root = Path(__file__).resolve().parents[1]
    domain = DomainDefinition.model_validate_json(
        (root / "gustobot/config/domains/equipment.json").read_text(encoding="utf-8")
    ).model_copy(
        update={
            "sql_enabled": enabled,
            "sql_keywords": ["统计"],
            "graph_keywords": ["部件"],
            "document_keywords": [],
        }
    )
    monkeypatch.setattr(lg_builder, "get_domain_definition", lambda: domain)
    monkeypatch.setattr(lg_prompts, "get_domain_definition", lambda: domain)
    settings = SimpleNamespace(
        SQL_DATABASE_URL=url,
        OPENAI_API_KEY="test-key",
        OPENAI_MODEL="test-model",
        OPENAI_API_BASE=None,
    )
    monkeypatch.setattr(lg_builder, "settings", settings)
    monkeypatch.setattr(lg_prompts, "settings", settings)
    structured = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value={
                "type": "text2sql-query",
                "question": "模型改写的问题",
                "logic": "SQL aggregation",
            }
        )
    )
    model = SimpleNamespace(with_structured_output=Mock(return_value=structured))
    monkeypatch.setattr(lg_builder, "ChatOpenAI", lambda **_: model)
    state = AgentState(messages=[HumanMessage(content=question)])
    result = await lg_builder.analyze_and_route_query(state, config={})
    route = result["router"]
    if enabled and url:
        assert route.type == "text2sql-query"
    else:
        assert route.type == fallback
        assert route.question == question
    model.with_structured_output.assert_called_once_with(Router, method="function_calling")
    structured.ainvoke.assert_awaited_once()


def test_sql_schema_uses_database_metadata_without_recipe_assumptions(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'equipment.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT)"))
            connection.execute(
                text(
                    "CREATE TABLE parts (id INTEGER PRIMARY KEY, device_id INTEGER "
                    "REFERENCES devices(id))"
                )
            )
    finally:
        engine.dispose()
    result = asyncio.run(
        schema.create_schema_retrieval_node(database_url)({"question": "所有对象"})
    )
    metadata = result["schema_context"]
    assert {table["table_name"] for table in metadata["tables"]} == {"devices", "parts"}
    assert metadata["relationships"][0]["source_table"] == "parts"
    assert metadata["relationships"][0]["target_table"] == "devices"
    assert "recipe" not in str(metadata).lower()


def test_sql_components_import_without_neo4j():
    root = Path(__file__).resolve().parents[1] / "gustobot/application/agents/text2sql"
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "neo4j" not in source.lower(), path
        assert "kg_sub_graph" not in source, path


@pytest.mark.asyncio
async def test_enabled_sql_route_uses_configured_database_and_keeps_url_private(monkeypatch):
    domain = SimpleNamespace(
        sql_enabled=True,
        sql_db_type="SQLite",
        sql_keywords=["统计"],
        name="设备",
        description="设备记录",
        document_scope="设备资料",
        assistant_instructions="",
        graph_keywords=[],
        document_keywords=[],
    )
    database_url = "sqlite:///private-sql-database.db"
    monkeypatch.setattr(lg_builder, "get_domain_definition", lambda: domain)
    monkeypatch.setattr(lg_prompts, "get_domain_definition", lambda: domain)
    settings = SimpleNamespace(
        SQL_DATABASE_URL=database_url,
        OPENAI_API_KEY="test-key",
        OPENAI_API_BASE=None,
        OPENAI_MODEL="test-model",
    )
    monkeypatch.setattr(lg_builder, "settings", settings)
    monkeypatch.setattr(lg_prompts, "settings", settings)
    model = object()
    monkeypatch.setattr(lg_builder, "ChatOpenAI", lambda **_: model)
    workflow = SimpleNamespace(ainvoke=AsyncMock(return_value={"answer": "设备共0台"}))
    factory = Mock(return_value=workflow)
    monkeypatch.setattr(lg_builder, "create_text2sql_workflow", factory)
    monkeypatch.setattr(lg_builder, "get_lightrag_service", Mock(side_effect=AssertionError("SQL")))
    assert database_url not in lg_prompts.domain_prompt(lg_prompts.ROUTER_SYSTEM_PROMPT)
    route = lg_builder._heuristic_router("统计数量")
    assert route is not None and route.type == "text2sql-query"
    state = AgentState(
        messages=[HumanMessage(content="统计数量")], router=Router(type="text2sql-query")
    )
    result = await lg_builder.create_research_plan(state, config={})
    factory.assert_called_once_with(model, database_url, db_type="SQLite")
    workflow.ainvoke.assert_awaited_once_with({"question": "统计数量"})
    assert result["messages"][0].content == "设备共0台"


@pytest.mark.asyncio
async def test_sql_workflow_keeps_zero_results_and_visualization_without_graph(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'statistics.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE devices (id INTEGER PRIMARY KEY)"))
    finally:
        engine.dispose()

    prompts = []

    class Model:
        def with_structured_output(self, model, *, method):
            def invoke(prompt):
                if model.__name__ == "SQLAnalysis":
                    prompts.append(prompt.to_string())
                    return model(
                        query_intent="count devices",
                        required_tables=["devices"],
                        required_columns=["id"],
                    )
                return model(chart_type="table", title="Device count", config={"columns": ["n"]})

            return RunnableLambda(invoke)

        def with_config(self, **kwargs):
            return RunnableLambda(lambda _: "SELECT COUNT(*) AS n FROM devices")

    workflow = create_text2sql_workflow(
        cast(BaseChatModel, Model()), database_url, db_type="SQLite"
    )
    result = await workflow.ainvoke({"question": "How many devices?"})
    assert result["execution_results"] == [{"n": 0}]
    assert result["execution_error"] is None
    assert result["visualization_config"] == {"columns": ["n"]}
    assert "devices" in prompts[0]
    assert "recipes" not in prompts[0]


def test_schema_failure_disposes_database_engine(monkeypatch):
    failure = RuntimeError("metadata unavailable")
    connection = Mock()
    engine = Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=connection)
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(schema, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(schema, "inspect", Mock(side_effect=failure))
    with pytest.raises(RuntimeError) as raised:
        schema._retrieve_schema("sqlite://")
    assert raised.value is failure
    engine.dispose.assert_called_once_with()
