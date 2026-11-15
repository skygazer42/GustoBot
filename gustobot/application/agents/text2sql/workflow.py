"""
Text2SQL Workflow built on LangGraph.

The workflow mirrors the multi-agent responsibilities from ChatDB,
implemented as LangGraph nodes:
1. Schema retrieval from the configured SQL database
2. Query analysis
3. SQL generation
4. SQL validation / retry loop
5. SQL execution
6. Visualization recommendation
7. Answer formatting
"""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from gustobot.infrastructure.core.logger import get_logger

from .components import (
    create_answer_formatter_node,
    create_query_analysis_node,
    create_schema_retrieval_node,
    create_sql_execution_node,
    create_sql_generation_node,
    create_sql_validation_node,
    create_visualization_node,
)
from .state import Text2SQLInputState, Text2SQLState, Text2SQLOutputState

logger = get_logger(service="text2sql.workflow")


def create_text2sql_workflow(
    llm: BaseChatModel,
    connection_string: str,
    db_type: str = "MySQL",
    max_retries: int = 3,
) -> CompiledStateGraph:
    """
    Assemble the Text2SQL workflow.
    """
    logger.info("创建 Text2SQL 工作流")
    if max_retries < 0:
        raise ValueError("max_retries must be nonnegative")
    if not connection_string.strip():
        raise ValueError("SQL connection_string must be configured")

    def initialize(state: Text2SQLState) -> dict:
        retry_budget = state.get("max_retries")
        row_limit = state.get("max_rows")
        return {
            "max_retries": max_retries if retry_budget is None else retry_budget,
            "max_rows": 1000 if row_limit is None else row_limit,
            "retry_count": 0,
            "db_type": db_type if state.get("db_type") is None else state["db_type"],
        }

    retrieve_schema = create_schema_retrieval_node(connection_string)
    analyze_query = create_query_analysis_node(llm)
    generate_sql = create_sql_generation_node(llm, db_type)
    validate_sql = create_sql_validation_node(db_type)
    execute_sql = create_sql_execution_node(connection_string)
    recommend_viz = create_visualization_node(llm)
    format_answer = create_answer_formatter_node()

    builder = StateGraph(
        Text2SQLState,
        input_schema=Text2SQLInputState,
        output_schema=Text2SQLOutputState,
    )

    builder.add_node("initialize", initialize)
    builder.add_node("retrieve_schema", retrieve_schema)
    builder.add_node("analyze_query", analyze_query)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("validate_sql", validate_sql)
    builder.add_node("execute_sql", execute_sql)
    builder.add_node("visualization_node", recommend_viz)
    builder.add_node("format_answer_node", format_answer)

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "retrieve_schema")
    builder.add_edge("retrieve_schema", "analyze_query")
    builder.add_edge("analyze_query", "generate_sql")
    builder.add_edge("generate_sql", "validate_sql")

    builder.add_conditional_edges(
        "validate_sql",
        _should_execute_or_retry,
        {
            "execute": "execute_sql",
            "retry": "generate_sql",
            "end": "format_answer_node",
        },
    )

    builder.add_edge("execute_sql", "visualization_node")
    builder.add_edge("visualization_node", "format_answer_node")
    builder.add_edge("format_answer_node", END)

    compiled_graph = builder.compile()
    return compiled_graph


def _should_execute_or_retry(state: Text2SQLState) -> Literal["execute", "retry", "end"]:
    """
    Decide whether to execute the SQL, retry generation, or end the workflow.
    """
    is_valid = state.get("is_valid", False)
    retry_count = state.get("retry_count")
    max_retries = state.get("max_retries")
    if retry_count is None:
        retry_count = 0
    if max_retries is None:
        max_retries = 3

    if is_valid:
        return "execute"
    if retry_count < max_retries:
        logger.warning("SQL 验证失败，准备第 {} 次重试", retry_count + 1)
        return "retry"

    logger.error("达到最大重试次数，终止工作流")
    return "end"


__all__ = ["create_text2sql_workflow"]
