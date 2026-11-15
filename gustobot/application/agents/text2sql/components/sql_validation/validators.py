"""
SQL validation helpers.
"""

from typing import List, Tuple


def validate_sql_syntax(sql: str, db_type: str = "MySQL") -> Tuple[bool, List[str]]:
    """
    Perform lightweight syntax checks suitable for LLM-generated SQL.
    """
    errors: List[str] = []

    if not sql or not sql.strip():
        errors.append("SQL 语句为空")
        return False, errors

    sql_upper = sql.upper()
    leading_sql = sql_upper.lstrip()
    if not (leading_sql.startswith("SELECT") or leading_sql.startswith("WITH")):
        errors.append("仅支持以 SELECT 或 WITH 开头的只读查询")

    if sql.count("(") != sql.count(")"):
        errors.append("括号不匹配")
    if sql.count("'") % 2 != 0:
        errors.append("单引号不匹配")
    if sql.count('"') % 2 != 0:
        errors.append("双引号不匹配")

    return len(errors) == 0, errors


def validate_sql_security(sql: str) -> Tuple[bool, List[str]]:
    """
    Detect obviously destructive SQL patterns.
    """
    warnings: List[str] = []
    sql_upper = sql.upper()

    dangerous_keywords = [
        "DROP TABLE",
        "DROP DATABASE",
        "TRUNCATE",
        "DELETE FROM",
        "INSERT INTO",
        "UPDATE ",
        "MERGE ",
        "ALTER TABLE",
        "CREATE TABLE",
        "CREATE DATABASE",
        "GRANT",
        "REVOKE",
        "CALL ",
        "EXEC ",
    ]

    for keyword in dangerous_keywords:
        if keyword in sql_upper:
            warnings.append(f"检测到危险操作: {keyword}")

    if "DELETE FROM" in sql_upper or "UPDATE" in sql_upper:
        if "WHERE" not in sql_upper:
            warnings.append("UPDATE/DELETE 语句缺少 WHERE 子句，可能影响所有行")

    return len(warnings) == 0, warnings
