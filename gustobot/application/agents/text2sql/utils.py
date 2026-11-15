"""
Utility helpers for Text2SQL workflows.
"""

from typing import Any, Dict, Optional, Union

from .models import SQLAnalysis


def render_analysis_markdown(
    analysis: Optional[Union[SQLAnalysis, Dict[str, Any]]],
    fallback_text: Optional[str] = None,
) -> str:
    """
    Render a human-readable analysis summary. Falls back to the raw text
    if structured data is not available.
    """
    if analysis is None:
        return "" if fallback_text is None else fallback_text
    analysis_model: SQLAnalysis = (
        SQLAnalysis.model_validate(analysis) if isinstance(analysis, dict) else analysis
    )

    lines = ["## SQL 命令分析报告"]

    if analysis_model.query_intent:
        lines.append("\n### 1. 查询意图")
        lines.append(analysis_model.query_intent)

    if analysis_model.required_tables:
        lines.append("\n### 2. 涉及的表")
        for table in analysis_model.required_tables:
            lines.append(f"- {table}")

    if analysis_model.required_columns:
        lines.append("\n### 3. 关键字段")
        for column in analysis_model.required_columns:
            lines.append(f"- {column}")

    if analysis_model.join_conditions:
        lines.append("\n### 4. 连接关系")
        lines.append(analysis_model.join_conditions)

    if analysis_model.filter_conditions:
        lines.append("\n### 5. 筛选条件")
        lines.append(analysis_model.filter_conditions)

    if analysis_model.aggregation:
        lines.append("\n### 6. 聚合需求")
        lines.append(analysis_model.aggregation)

    if analysis_model.order_by:
        lines.append("\n### 7. 排序要求")
        lines.append(analysis_model.order_by)

    if analysis_model.notes:
        lines.append("\n### 8. 其它说明")
        lines.append(analysis_model.notes)

    return "\n".join(lines).strip()
