"""
Text2SQL State Definitions

文本到 SQL 工作流使用到的 TypedDict 定义。
"""

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    """Workflow state tracked across Text2SQL LangGraph nodes."""

    # 输入
    question: str
    connection_id: Optional[int]
    db_type: Optional[str]
    max_rows: int

    # Schema 检索
    schema_context: Dict[str, Any]
    value_mappings: Dict[str, Dict[str, str]]
    mappings_str: str

    # 查询分析
    analysis: Optional[Dict[str, Any]]
    analysis_text: Optional[str]

    # SQL 生成与验证
    sql_statement: str
    is_valid: bool
    validation_errors: Annotated[List[str], operator.add]

    # 执行阶段
    execution_results: Optional[List[Dict[str, Any]]]
    execution_error: Optional[str]

    # 可视化与解释
    visualization: Optional[Dict[str, Any]]
    explanation: Optional[str]

    # 工作流控制
    steps: Annotated[List[str], operator.add]
    retry_count: int
    max_retries: int

    # 最终输出
    answer: str
    visualization_config: Optional[Dict[str, Any]]


class Text2SQLInputState(TypedDict):
    """Input payload for the Text2SQL workflow."""

    question: str
    connection_id: Optional[int]
    max_retries: Optional[int]
    db_type: Optional[str]
    max_rows: Optional[int]


class Text2SQLOutputState(TypedDict):
    """Workflow output returned to callers."""

    answer: str
    sql_statement: Optional[str]
    execution_results: Optional[List[Dict[str, Any]]]
    execution_error: Optional[str]
    explanation: Optional[str]
    visualization: Optional[Dict[str, Any]]
    visualization_config: Optional[Dict[str, Any]]
    steps: List[str]
