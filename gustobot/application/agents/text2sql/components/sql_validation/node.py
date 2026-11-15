"""
SQL validation node.
"""

from typing import Any, Callable, Coroutine, Dict, List

from gustobot.infrastructure.core.logger import get_logger

from .validators import validate_sql_security, validate_sql_syntax

logger = get_logger(service="text2sql.sql_validation")


def create_sql_validation_node(
    db_type: str = "MySQL",
) -> Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]:
    """
    Build a LangGraph node that validates SQL produced by upstream generators.
    """

    async def validate_sql(state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("-----开始验证 SQL 语句-----")

        sql_statement = state.get("sql_statement", "")
        current_retry = state.get("retry_count", 0)

        if not sql_statement:
            logger.warning("SQL 语句为空，跳过验证")
            return {
                "is_valid": False,
                "validation_errors": ["SQL 语句为空"],
                "retry_count": current_retry + 1,
                "steps": ["sql_validation_failed"],
            }

        errors: List[str] = []

        syntax_ok, syntax_errors = validate_sql_syntax(sql_statement, db_type)
        if not syntax_ok:
            errors.extend(syntax_errors)
            logger.warning("SQL 语法验证失败: {}", syntax_errors)

        security_ok, security_warnings = validate_sql_security(sql_statement)
        if not security_ok:
            errors.extend(security_warnings)
            logger.warning("SQL 安全检查警示: {}", security_warnings)

        is_valid = not errors
        next_retry = current_retry if is_valid else current_retry + 1

        if is_valid:
            logger.info("SQL 验证通过")
        else:
            logger.error("SQL 验证失败: {}", errors)

        return {
            "is_valid": is_valid,
            "validation_errors": errors,
            "retry_count": next_retry,
            "steps": ["sql_validation" if is_valid else "sql_validation_failed"],
        }

    return validate_sql
