> 历史架构资料，仅供溯源；其中旧路由、LightRAG／pgvector 和部署命令已退役。当前使用说明见 [快速启动](../../QUICK_START.md) 与 [领域服务](../../DOMAIN_KNOWLEDGE.md)。

# Text2SQL 实现

SQL 统计是可选的独立能力，与 LightRAG 检索图分离。实现位于 `gustobot/application/agents/text2sql/`，不再依赖 Neo4j 元数据、关系映射图或旧 kg_sub_graph 包。

## 显式启用

领域 JSON 默认 `sql_enabled=false`。需要统计时设置：

```json
{"sql_enabled": true, "sql_db_type": "MySQL"}
```

这两项是现有领域 JSON 的局部配置，不是完整领域定义。连接串通过环境变量 `SQL_DATABASE_URL` 配置，不写入领域 JSON，避免被公开接口和抽取提示暴露。连接账号应限制为只读，模型 SQL 校验不能代替数据库权限。

仅当领域开关和连接配置同时存在时，聊天统计路由才启用。Compose 的 `sql` profile 提供示例 MySQL；启用 profile 本身不会启用聊天 SQL。

## 工作流

```mermaid
flowchart LR
    Q[统计问题] --> S[SQLAlchemy 读取表、列、外键]
    S --> A[模型分析问题]
    A --> G[生成 SQL]
    G --> V[校验只读语句及限制]
    V -->|有效| E[SQLAlchemy 执行]
    V -->|有剩余次数| G
    V -->|次数用尽| F[格式化结果或错误]
    E --> C[可视化配置建议]
    C --> F
```

schema 来自目标 SQL 数据库自身的 Inspector，包括表、列和外键。执行与元数据读取在线程中完成，各自关闭连接和 engine。查询结果中的零值和空结果保留；失败不会被当作零行成功。

```python
from gustobot.application.agents.text2sql import create_text2sql_workflow

workflow = create_text2sql_workflow(
    llm,
    connection_string=sql_database_url,
    db_type="MySQL",
    max_retries=3,
)
result = await workflow.ainvoke({"question": "各分类分别有多少条记录？"})
```

可视化步骤只生成推荐配置，没有 Streamlit 或 Matplotlib 渲染服务。SQL 验证使用原有规则，无法替代数据库只读权限或生产查询资源限制。

离线回归覆盖 SQLite 元数据/外键、完整查询与零值、失败清理、SQL 双开关及与图问答的隔离。真实业务数据库仍需部署环境联测。
