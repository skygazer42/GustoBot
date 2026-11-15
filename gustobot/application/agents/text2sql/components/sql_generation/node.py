"""
SQL generation node.
"""

from typing import Any, Callable, Coroutine, Dict

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from ...utils import render_analysis_markdown
from gustobot.infrastructure.core.logger import get_logger

from .prompts import create_sql_generation_prompt, format_schema_as_text

logger = get_logger(service="text2sql.sql_generation")


def create_sql_generation_node(
    llm: BaseChatModel,
    db_type: str = "MySQL",
) -> Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]:
    """
    Build a LangGraph node that generates SQL statements from the analysed query.
    """
    prompt = create_sql_generation_prompt()
    sql_llm = llm.with_config(temperature=0.1)
    sql_chain = prompt | sql_llm | StrOutputParser()

    async def generate_sql(state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("-----开始生成 SQL 语句-----")

        schema_context = state["schema_context"]
        analysis_dict = state.get("analysis")
        analysis_text = state.get("analysis_text") or ""

        if not schema_context:
            logger.warning("缺少 Schema 信息，无法生成 SQL")
            return {
                "sql_statement": "",
                "steps": ["sql_generation_failed_no_schema"],
            }

        schema_text = format_schema_as_text(schema_context)
        # value_mappings 功能已简化移除
        analysis_summary = analysis_text or render_analysis_markdown(analysis_dict, "")

        question = state["question"]
        inputs = {
            "db_type": db_type,
            "schema": schema_text,
            "value_mappings": "无值映射信息",
            "analysis_summary": analysis_summary or "无分析信息",
            "question": question,
        }

        sql_raw = await sql_chain.ainvoke(inputs)
        sql_statement = _clean_sql_statement(sql_raw)
        logger.info("SQL 生成完成")
        return {
            "sql_statement": sql_statement,
            "steps": ["sql_generation"],
        }

    return generate_sql


def _clean_sql_statement(sql: str) -> str:
    """
    Remove Markdown code fences and normalise whitespace.
    """
    cleaned = sql.replace("```sql", "").replace("```", "").strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines)
