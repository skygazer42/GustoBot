# 数据来源与血缘

本文说明仓库内置知识数据的来源、用途和可追溯性。这里的“数据来源”与“检索后端”是两个不同概念：

- **数据来源**：内容最初来自哪个文件、网页或数据集。
- **检索后端**：本次回答从 LightRAG、旧 Milvus/PostgreSQL pgvector 或外部检索中的哪一个取回。

旧 KB 聊天链路分别返回 `source` 和 `backend`；LightRAG 查询的检索上下文见响应 metadata。因此“存储在 PostgreSQL”不代表内容原始来源是 PostgreSQL。

## 仓库内置数据

| 文件或目录 | 已知来源与规模 | 主要用途 | 可追溯性与限制 |
|---|---|---|---|
| `data/recipe.json` | 与 [OpenKG RecipeGraph](http://openkg.cn/dataset/recipegraph) 的 `recipe.json` 一致，共 19,669 条菜谱 | LightRAG 菜谱导入；旧 SQL/向量数据工具 | 使用或再分发前应核对上游数据集当前的许可和署名要求；仓库的 Apache-2.0 代码许可证不会自动覆盖第三方数据 |
| `data/excipients.json` | 对应 OpenKG RecipeGraph 的食材营养/功效数据，共 1,234 条 | 保留的离线图谱 CSV 导出 | 含营养及食用功效描述，只用于检索演示，不应作为医疗或营养建议；许可要求同上 |
| `data/neo4j/graph.json` | 从菜谱/食材数据转换出的示例图，共 69 个节点、50 条关系 | 旧图谱演示文件，当前服务不自动导入 | 派生数据，不是新的独立来源 |
| `data/kb/data.txt` | 2025-10-29 作为历史饮食知识示例加入仓库 | 显式启用旧 KB 后的演示语料 | Git 历史未记录原始 URL、作者或数据许可，内容也没有逐条引用；只能视为演示数据，生产使用前应替换为可授权、可核验的资料 |
| `data/kb/历史菜谱源头.xlsx`、`kb_ingest/data/历史菜谱源头.xlsx` | 8 条历史菜谱示例记录 | 旧 KB ingest 的 pgvector 演示数据 | Git 历史未记录上游出处，表内也没有逐条文献引用；历史说法未经权威校验，仅用于验证 pgvector 链路 |
| `data/lightrag/` | 由仓库内菜谱文本生成的索引/缓存产物 | LightRAG 启动和查询 | 派生数据；其来源取决于生成索引时使用的输入文件和参数 |

## 默认检索链路

所有内置领域默认用同一 LightRAG 索引回答文档与关系问题，分别选择 naive 与 hybrid 等检索模式。领域索引目录彼此隔离。事实输入先校验类型与引文，再按来源序列化完整原文和事实，通过普通文档流程入库。

LightRAG 的 `/query` 与 `/ontology/query` 响应在 `metadata.data` 中保留其返回的检索上下文；其中 references 的 file_path 取自导入时提供的来源。文档上传或本体来源 URI 可用于追溯，不能把模型生成的关系解释成已经逐边证明的事实。

旧 PostgreSQL pgvector → Milvus → 可选外部搜索链路仅在领域显式配置 `document_backend=legacy_kb` 时使用。KB ingest 地址由 `INGEST_SERVICE_URL` 指定，Compose 中相应组件属于 `legacy-kb` profile。

旧 KB 响应中的来源对象示例：

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
- 当前 LightRAG：通过 `/api/v1/lightrag/insert` 导入文档，或用 `/api/v1/ontology/facts` 导入带引文的已校验事实。
- 菜谱数据：`scripts/init_lightrag.py --source json` 仅用于菜谱领域；`scripts/import_recipes.py` 是旧向量库工具，`scripts/recipe_kg_to_csv.py` 只做离线 CSV 导出。

重新入库时建议在每条记录的 metadata 中保留 `source`、`url`、`author`、`license` 和采集日期，避免再次丢失血缘信息。
