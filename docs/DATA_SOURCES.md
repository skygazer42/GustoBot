# 数据来源与血缘

本文说明仓库内置知识数据的来源、用途和可追溯性。这里的“数据来源”与“检索后端”是两个不同概念：

- **数据来源**：内容最初来自哪个文件、网页或数据集。
- **检索后端**：本次回答从 Milvus、PostgreSQL pgvector 或外部检索中的哪一个取回。

聊天接口会分别返回 `source` 和 `backend`，因此“存储在 PostgreSQL”不代表内容原始来源是 PostgreSQL。

## 仓库内置数据

| 文件或目录 | 已知来源与规模 | 主要用途 | 可追溯性与限制 |
|---|---|---|---|
| `data/recipe.json` | 与 [OpenKG RecipeGraph](http://openkg.cn/dataset/recipegraph) 的 `recipe.json` 一致，共 19,669 条菜谱 | Neo4j、MySQL、LightRAG 及批量菜谱导入 | 使用或再分发前应核对上游数据集当前的许可和署名要求；仓库的 Apache-2.0 代码许可证不会自动覆盖第三方数据 |
| `data/excipients.json` | 对应 OpenKG RecipeGraph 的食材营养/功效数据，共 1,234 条 | Neo4j 图谱构建 | 含营养及食用功效描述，只用于检索演示，不应作为医疗或营养建议；许可要求同上 |
| `data/neo4j/graph.json` | 从菜谱/食材数据转换出的示例图，共 69 个节点、50 条关系 | 小规模 Neo4j 初始化与演示 | 派生数据，不是新的独立来源 |
| `data/kb/data.txt` | 2025-10-29 作为历史饮食知识示例加入仓库 | Milvus 启动时的非结构化知识库 | Git 历史未记录原始 URL、作者或数据许可，内容也没有逐条引用；只能视为演示数据，生产使用前应替换为可授权、可核验的资料 |
| `data/kb/历史菜谱源头.xlsx`、`kb_ingest/data/历史菜谱源头.xlsx` | 8 条历史菜谱示例记录 | PostgreSQL pgvector 启动数据 | Git 历史未记录上游出处，表内也没有逐条文献引用；历史说法未经权威校验，仅用于验证 pgvector 链路 |
| `data/lightrag/` | 由仓库内菜谱文本生成的索引/缓存产物 | LightRAG 启动和查询 | 派生数据；其来源取决于生成索引时使用的输入文件和参数 |

此外，`gustobot.crawler` 支持通过 MediaWiki API 导入 Wikipedia 摘要。该流程会保留页面 URL；导入内容仍受对应 Wikipedia 页面及其许可证约束。

## 默认检索链路

知识文化类问题默认按以下顺序检索：

1. PostgreSQL pgvector：由 Excel 接入服务写入的结构化记录。
2. Milvus：当 PostgreSQL 没有合格结果时，检索 `data/kb/data.txt` 等非结构化文档。
3. 外部检索：仅在显式启用且配置服务地址时使用。

Agent 确实接入了 pgvector：它根据 `INGEST_SERVICE_URL` 调用 `kb_ingest` 的 `/api/v1/knowledge/search`。Docker Compose 默认地址是 `http://kb_ingest:8000/api/v1/knowledge/search`。只有 PostgreSQL 结果通过相似度/重排阈值时，响应来源才会标为 `backend: "postgres"`；无合格结果时会继续使用 Milvus。

响应中的来源对象示例：

```json
{
  "backend": "milvus",
  "source": "data.txt",
  "document_id": "data.txt_1"
}
```

`backend` 表示本次真正命中的检索后端；`source` 表示被索引内容的来源文件。回答正文不会再由模型自行猜测或生成数据库来源标签。

## 替换演示数据

- Milvus：将 `KB_DATA_FILE` 指向有明确授权和引用信息的文本，再重新执行 `scripts/init_kb_milvus.py`。
- PostgreSQL pgvector：将 `KB_EXCEL_PATH` 指向自己的 Excel，通过 `kb_ingest` 重新导入。
- 菜谱图谱：使用 `scripts/import_recipes.py`、`scripts/recipe_kg_to_csv.py` 或 Wikipedia 导入工具生成自己的数据。

重新入库时建议在每条记录的 metadata 中保留 `source`、`url`、`author`、`license` 和采集日期，避免再次丢失血缘信息。
