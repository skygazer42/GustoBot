# 数据来源与血缘

本文说明仓库内置知识数据的来源、用途和可追溯性。这里的“数据来源”与“检索后端”是两个不同概念：

- **数据来源**：内容最初来自哪个文件、网页或数据集。
- **检索后端**：本次回答从 Neo4j 事实图或 Milvus 原文索引中的哪一个取回。

当前响应分别返回 `source` 和 `backend`。MySQL 记录来源版本、作业和会话，不因为存储了元数据而成为内容的原始出处。

## 仓库内置数据

| 文件或目录 | 已知来源与规模 | 主要用途 | 可追溯性与限制 |
|---|---|---|---|
| `data/recipe.json` | 仓库已登记为 [OpenKG RecipeGraph](http://openkg.cn/dataset/recipegraph) 的 `recipe.json`，快照共 19,669 条菜谱 | 显式、确定性映射到 Neo4j；不在启动时导入 | 使用或再分发前应核对上游数据集当前的许可和署名要求；仓库的 Apache-2.0 代码许可证不会自动覆盖第三方数据 |
| `data/excipients.json` | 对应 OpenKG RecipeGraph 的食材营养/功效数据，共 1,234 条 | 保留的离线图谱 CSV 导出 | 含营养及食用功效描述，只用于检索演示，不应作为医疗或营养建议；许可要求同上 |
| `data/kb/data.txt` | 2025-10-29 作为历史饮食知识示例加入仓库 | 可显式导入文档索引的演示语料 | Git 历史未记录原始 URL、作者或数据许可，内容也没有逐条引用；只能视为演示数据，生产使用前应替换为可授权、可核验的资料 |
| `data/kb/历史菜谱源头.xlsx` | 8 条历史菜谱示例记录 | 已退役服务的历史演示资料，保留原文件 | Git 历史未记录上游出处，表内也没有逐条文献引用；历史说法未经权威校验，不作为当前知识事实。已核对旧服务目录中的副本与本文件 SHA-256 相同 |
| `data/reference/legacy_mysql/` | 旧 `recipe_db` 结构与 SQL 样例，包含 70 组菜谱 INSERT | 仅作历史来源参考，启动和迁移不执行 | 来源未核验，不能作为当前事实；其中包含旧建库／删表语句 |

旧 `data/lightrag/`、`data/neo4j/graph.json`、tokenizer 缓存及导入标记已删除。它们属于派生索引、导出或缓存，不是独立原始资料。

## 默认检索链路

所有内置领域使用同一套本体约束服务。Neo4j 返回事实及其来源和引文；Milvus 返回已发布来源版本中的原文分块，按领域、本体版本和 embedding 模型过滤。关联回答可用实体 ID 把图中对象与原文对齐。LightRAG 和 pgvector 不参与当前主链。

当前知识响应中的来源对象示例：

```json
{
  "backend": "milvus",
  "source": "data.txt",
  "document_id": "<稳定分块 ID>"
}
```

`backend` 表示本次真正命中的检索后端；`source` 表示被索引内容的来源文件。回答正文不会再由模型自行猜测或生成数据库来源标签。

## 替换演示数据

- 原文：通过 `scripts/import_knowledge.py documents --path <文件>`，或受管上传后显式调用 `/api/v1/knowledge/documents`。
- 菜谱事实：通过 `scripts/import_knowledge.py recipes --path <JSON>`，或 `scripts/import_recipes.py --file <JSON>` 调用同一入库 API。
- 文档事实：先 `/api/v1/ontology/extract` 取得候选，审核后通过 `/api/v1/ontology/facts` 直接写图。
- `scripts/recipe_kg_to_csv.py` 只做离线 CSV 导出；旧文件与卷不会被自动转换为当前索引。

重新入库时建议在每条记录的 metadata 中保留 `source`、`url`、`author`、`license` 和采集日期，避免再次丢失血缘信息。
