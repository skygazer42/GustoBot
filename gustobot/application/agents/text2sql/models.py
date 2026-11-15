"""
Text2SQL Pydantic Models

定义用于结构化输出的 Pydantic 模型
"""

from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class SQLAnalysis(BaseModel):
    """SQL 分析报告模型（类似 ChatDB 的 QueryAnalyzerAgent 输出）"""

    query_intent: str = Field(description="查询意图描述")
    required_tables: List[str] = Field(description="需要的表名列表")
    required_columns: List[str] = Field(description="需要的字段列表")
    join_conditions: Optional[str] = Field(default=None, description="表连接条件描述")
    filter_conditions: Optional[str] = Field(default=None, description="筛选条件描述")
    aggregation: Optional[str] = Field(default=None, description="聚合操作描述")
    order_by: Optional[str] = Field(default=None, description="排序要求")
    notes: Optional[str] = Field(default=None, description="额外注意事项")


class SQLValidationResult(BaseModel):
    """SQL 验证结果"""

    is_valid: bool = Field(description="SQL 是否有效")
    errors: List[str] = Field(default_factory=list, description="验证错误列表")
    warnings: List[str] = Field(default_factory=list, description="警告信息")
    corrected_sql: Optional[str] = Field(default=None, description="修正后的 SQL（如果需要）")


class VisualizationRecommendation(BaseModel):
    """可视化推荐（类似 ChatDB 的 VisualizationRecommenderAgent 输出）"""

    chart_type: Literal["bar", "line", "pie", "scatter", "table"] = Field(
        description="推荐的图表类型"
    )
    title: str = Field(description="图表标题")
    x_axis: Optional[str] = Field(default=None, description="X 轴字段")
    y_axis: Optional[str] = Field(default=None, description="Y 轴字段")
    series: Optional[List[str]] = Field(default=None, description="系列字段列表")
    config: Optional[Dict] = Field(default=None, description="额外配置参数")


class SchemaTable(BaseModel):
    """表结构模型"""

    table_name: str
    description: Optional[str] = None
    columns: List["SchemaColumn"]


class SchemaColumn(BaseModel):
    """字段结构模型"""

    column_name: str
    data_type: str
    description: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_unique: bool = False


class SchemaRelationship(BaseModel):
    """表关系模型"""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relationship_type: Optional[str] = None  # "1-to-1", "1-to-N", "N-to-M"
