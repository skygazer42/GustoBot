"""
SQL execution node.
"""

import asyncio
from typing import Any, Callable, Coroutine, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from gustobot.infrastructure.core.logger import get_logger

logger = get_logger(service="text2sql.sql_execution")


def create_sql_execution_node(
    connection_string: Optional[str] = None,
) -> Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]:
    """
    Build a LangGraph node that executes read-only SQL statements.
    """

    async def execute_sql(state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("-----开始执行 SQL 查询-----")

        sql_statement = (state.get("sql_statement") or "").strip()
        connection_id = state.get("connection_id")
        row_limit = state.get("max_rows")
        max_rows = 1000 if row_limit is None else int(row_limit)
        if max_rows <= 0:
            return {
                "execution_results": None,
                "execution_error": "max_rows 必须大于 0",
                "steps": ["sql_execution_failed"],
            }

        if not sql_statement:
            logger.warning("SQL 语句为空，跳过执行")
            return {
                "execution_results": None,
                "execution_error": "SQL 语句为空",
                "steps": ["sql_execution_skipped"],
            }

        if not _is_read_only_query(sql_statement):
            logger.warning("检测到非只读查询，已阻止执行")
            return {
                "execution_results": None,
                "execution_error": "仅支持只读 SELECT 查询",
                "steps": ["sql_execution_blocked"],
            }

        if not state.get("is_valid"):
            logger.warning("SQL 验证未通过，跳过执行")
            return {
                "execution_results": None,
                "execution_error": "SQL 验证未通过",
                "steps": ["sql_execution_skipped_invalid"],
            }

        effective_connection_string = connection_string
        if not effective_connection_string:
            logger.error("无法获取数据库连接信息 connection_id={}", connection_id)
            return {
                "execution_results": None,
                "execution_error": "无法获取数据库连接信息",
                "steps": ["sql_execution_failed"],
            }

        try:
            results = await _execute_sql_query(
                effective_connection_string, sql_statement, max_rows=max_rows
            )
            logger.info("SQL 执行成功，返回 {} 行结果", len(results))
            return {
                "execution_results": results,
                "execution_error": None,
                "steps": ["sql_execution"],
            }
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("SQL 执行失败: {}", exc)
            return {
                "execution_results": None,
                "execution_error": str(exc),
                "steps": ["sql_execution_failed"],
            }

    return execute_sql


async def _execute_sql_query(
    connection_string: str,
    sql: str,
    max_rows: int = 1000,
) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_run_query_sync, connection_string, sql, max_rows)


def _run_query_sync(
    connection_string: str,
    sql: str,
    max_rows: int,
) -> List[Dict[str, Any]]:
    engine: Engine = create_engine(connection_string, future=True)
    try:
        with engine.connect() as connection:
            result = connection.execution_options(stream_results=True).execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchmany(max_rows)
            return [{column: row[idx] for idx, column in enumerate(columns)} for row in rows]
    finally:
        engine.dispose()


def _is_read_only_query(sql: str) -> bool:
    """
    检查 SQL 是否为只读查询（SELECT、WITH、EXPLAIN）

    Returns:
        True if query is read-only, False otherwise
    """
    statement = sql.strip()
    if not statement:
        return False

    # 检查是否包含多条语句（;分隔）
    if ";" in statement.rstrip(";"):
        return False

    upper = statement.upper()

    # 允许的只读关键词
    readonly_keywords = ["SELECT ", "WITH ", "EXPLAIN ", "SHOW "]
    starts_with_readonly = any(upper.startswith(kw) for kw in readonly_keywords)

    # 危险关键词（即使在SELECT中也不允许）
    dangerous_keywords = [
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "DROP ",
        "CREATE ",
        "ALTER ",
        "TRUNCATE ",
        "REPLACE ",
        "MERGE ",
        "GRANT ",
        "REVOKE ",
        "EXEC ",
        "EXECUTE ",
        "CALL ",
    ]
    contains_dangerous = any(kw in upper for kw in dangerous_keywords)

    return starts_with_readonly and not contains_dangerous
