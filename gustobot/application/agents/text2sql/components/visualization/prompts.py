"""
Prompt utilities for visualization recommendations.
"""

from langchain_core.prompts import ChatPromptTemplate


def create_visualization_prompt() -> ChatPromptTemplate:
    system_message = """
你是一名数据可视化顾问，需根据 SQL 查询的结果数据推荐最合适的图表类型。
请结合查询意图、结果结构和字段类型做出判断。
输出必须为 JSON，包含:
{{
  "chart_type": "table|bar|line|pie|scatter",
  "title": "简洁标题",
  "x_axis": "可选，x 轴字段",
  "y_axis": "可选，y 轴字段",
  "series": ["可选，系列字段列表"],
  "config": {{ "可选，额外配置" }}
}}
chart_type 若为 table，可省略 x_axis/y_axis。
"""

    human_message = """
## 用户问题
{question}

## 查询分析
{analysis_summary}

## SQL 语句
```sql
{sql_statement}
```

## 查询结果 (前 10 条)
```json
{sample_rows}
```

请返回 JSON 推荐。
"""

    return ChatPromptTemplate.from_messages(
        [
            ("system", system_message.strip()),
            ("human", human_message.strip()),
        ]
    )
