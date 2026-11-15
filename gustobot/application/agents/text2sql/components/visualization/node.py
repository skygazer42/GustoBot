"""
Visualization recommendation node.
"""

import json
from typing import Any, Callable, Coroutine, Dict, List

from langchain_core.language_models import BaseChatModel

from ...models import VisualizationRecommendation
from gustobot.infrastructure.core.logger import get_logger

from ..sql_generation.prompts import format_schema_as_text
from .prompts import create_visualization_prompt

logger = get_logger(service="text2sql.visualization")


def create_visualization_node(
    llm: BaseChatModel,
) -> Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]:
    """
    Build a LangGraph node that recommends a visualization configuration based
    on the SQL query results.
    """
    prompt = create_visualization_prompt()
    viz_llm = llm.with_structured_output(VisualizationRecommendation, method="function_calling")

    async def recommend(state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("-----开始生成可视化建议-----")

        results: List[Dict[str, Any]] = state.get("execution_results") or []
        if not results:
            logger.info("查询结果为空，默认返回表格展示")
            return {
                "visualization": VisualizationRecommendation(
                    chart_type="table",
                    title="查询结果",
                ).model_dump(),
                "steps": ["visualization_default"],
            }

        sample_rows = json.dumps(results[:10], ensure_ascii=False, indent=2)
        question = state["question"]
        analysis_summary = state.get("analysis_text") or ""
        sql_statement = state["sql_statement"]

        schema_text = format_schema_as_text(state["schema_context"])

        inputs = {
            "question": question,
            "analysis_summary": analysis_summary or schema_text,
            "sql_statement": sql_statement,
            "sample_rows": sample_rows,
        }

        try:
            recommendation = VisualizationRecommendation.model_validate(
                await viz_llm.ainvoke(prompt.format_messages(**inputs))
            )
            logger.info("可视化推荐完成: {}", recommendation.chart_type)
            return {
                "visualization": recommendation.model_dump(),
                "steps": ["visualization"],
            }
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("可视化推荐失败: {}", exc)
            return {
                "visualization": VisualizationRecommendation(
                    chart_type="table",
                    title="查询结果",
                ).model_dump(),
                "steps": ["visualization_failed"],
            }

    return recommend
