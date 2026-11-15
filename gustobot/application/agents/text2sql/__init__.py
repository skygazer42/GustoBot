"""
Text2SQL Package

基于 LangGraph 的 Text2SQL 系统
参考 ChatDB 的 AutoGen 多智能体实现
"""

from .state import Text2SQLState, Text2SQLInputState, Text2SQLOutputState
from .models import (
    SQLAnalysis,
    SQLValidationResult,
    VisualizationRecommendation,
    SchemaTable,
    SchemaColumn,
    SchemaRelationship,
)
from .workflow import create_text2sql_workflow


__all__ = [
    "create_text2sql_workflow",
    "Text2SQLState",
    "Text2SQLInputState",
    "Text2SQLOutputState",
    "SQLAnalysis",
    "SQLValidationResult",
    "VisualizationRecommendation",
    "SchemaTable",
    "SchemaColumn",
    "SchemaRelationship",
]
