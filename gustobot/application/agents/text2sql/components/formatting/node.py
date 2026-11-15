"""
Answer formatting node.
"""

import json
from typing import Any, Callable, Coroutine, Dict, List

from gustobot.infrastructure.core.logger import get_logger

logger = get_logger(service="text2sql.answer_formatter")


def create_answer_formatter_node() -> (
    Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]
):
    """Build a LangGraph node that composes the final answer for the user."""

    async def format_answer(state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("-----格式化最终回答-----")

        execution_error = state.get("execution_error")
        if not state.get("is_valid", True) and not execution_error:
            execution_error = "；".join(state.get("validation_errors", [])) or "SQL 验证未通过"
        sql_statement = state.get("sql_statement", "")
        results = state.get("execution_results") or []
        analysis_text = state.get("analysis_text") or ""
        visualization = state.get("visualization") or {}
        question = state.get("question", "")

        if execution_error:
            answer = f"抱歉，执行 SQL 时出现错误：{execution_error}"
        else:
            answer_lines: List[str] = []
            answer_lines.append(f"### 查询结果摘要\n问题：{question or '（未提供）'}")
            if analysis_text:
                answer_lines.append("\n---\n")
                answer_lines.append(analysis_text)
            if results:
                answer_lines.append("\n---\n### 结果预览")
                preview = json.dumps(results[:5], ensure_ascii=False, indent=2)
                answer_lines.append(f"```json\n{preview}\n```")
            if visualization:
                answer_lines.append("\n---\n### 可视化建议")
                answer_lines.append(
                    f"- 类型：{visualization.get('chart_type', 'table')}\n"
                    f"- 标题：{visualization.get('title', '查询结果')}"
                )
                config = visualization.get("config") if isinstance(visualization, dict) else None
                if config:
                    answer_lines.append("```json")
                    answer_lines.append(json.dumps(config, ensure_ascii=False, indent=2))
                    answer_lines.append("```")
            answer = "\n".join(answer_lines).strip()

        viz_config = None
        if isinstance(visualization, dict):
            viz_config = visualization.get("config")

        return {
            "answer": answer,
            "sql_statement": sql_statement,
            "execution_results": results,
            "execution_error": execution_error,
            "visualization": visualization if isinstance(visualization, dict) else None,
            "visualization_config": viz_config,
            "steps": ["format_answer"],
        }

    return format_answer
