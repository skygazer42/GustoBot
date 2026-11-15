"""
Prompt utilities for query analysis.
"""

from langchain_core.prompts import ChatPromptTemplate


def create_query_analysis_prompt() -> ChatPromptTemplate:
    """
    Build the prompt used for analysing the natural language question against
    the available schema before SQL generation.
    """
    system_message = """
你是一名资深的数据库查询分析专家，负责在生成 SQL 之前对用户的问题进行结构化分析。

请根据提供的数据库 Schema、值映射信息以及用户问题，输出一个 JSON 对象，包含以下字段：
{{
  "query_intent": "字符串，描述用户的核心诉求",
  "required_tables": ["表名列表"],
  "required_columns": ["字段列表", "..."],
  "join_conditions": "如需联结，请描述连接逻辑，否则留空字符串",
  "filter_conditions": "筛选条件说明，允许为空字符串",
  "aggregation": "聚合或统计需求，允许为空字符串",
  "order_by": "排序需求，允许为空字符串",
  "notes": "任何需要澄清的问题或额外说明，可为空字符串"
}}

输出必须是有效的 JSON，严禁添加额外说明。
"""

    human_message = """
## 数据库类型
{db_type}

## 数据库 Schema
```sql
{schema}
```

## 值映射信息
{value_mappings}

## 用户问题
{question}

请返回结构化 JSON 分析。
"""

    return ChatPromptTemplate.from_messages(
        [
            ("system", system_message.strip()),
            ("human", human_message.strip()),
        ]
    )
