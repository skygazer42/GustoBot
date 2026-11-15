# GustoBot 快速启动

## 配置与运行

需要 Python 3.10–3.13。先复制示例配置，填写真实的 LLM 与 Embedding 服务参数：

```powershell
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python -m uvicorn gustobot.main:application --reload
```

默认会话数据库是 SQLite。LightRAG 首次使用时初始化，读取当前领域索引；导入资料需要模型和向量服务。完整 API 以 [OpenAPI](http://localhost:8000/docs) 为准。

前端独立启动：

```powershell
Set-Location web
npm install
npm run dev
```

前端 URL 以 Vite 输出为准；API 默认使用 `http://localhost:8000`。

## 容器部署

```powershell
docker compose up --build
docker compose logs -f backend
```

默认仅启动 backend，使用 SQLite 会话和本地 LightRAG 索引，不要求 Neo4j、Redis、Milvus 或 PostgreSQL。若已有 `.env` 显式配置 MySQL，须启动相应服务或自行改为 SQLite。

| Profile | 用途 |
| --- | --- |
| `sql` | 示例 MySQL，需要时另配 SQL_DATABASE_URL 与领域 sql_enabled |
| `legacy-kb` | 旧 Milvus、etcd、MinIO、PostgreSQL、KB ingest |
| `legacy-cache` | 保留的 Redis 服务 |

例如 `docker compose --profile legacy-kb up --build`。启用 profile 不会自动改领域的 document_backend 或注册旧 HTTP 路由。

## 选择领域

```powershell
$env:KNOWLEDGE_DOMAIN_FILE = "gustobot/config/domains/equipment.json"
python -m uvicorn gustobot.main:application --reload
```

内置 `recipes.json`、`equipment.json` 和 `generic.json` 均默认使用共享 LightRAG。新增领域需准备自己的配置和语料，无须添加行业专属 Cypher。不同领域使用独立索引目录；修改配置后重启进程。

## 导入与查询

以下示例以设备领域为例。普通文档从 `/api/v1/lightrag/insert` 导入：

```json
{"documents": ["设备手册：泵 A 包含轴承 B。轴承 B 的检查记录提示振动异常。"]}
```

向 `/api/v1/lightrag/query` 提交自然语言问题：

```json
{"query": "泵 A 的部件有什么异常？", "mode": "hybrid", "top_k": 10}
```

`naive` 用于文档向量问答，`hybrid` 结合实体和关系上下文；二者复用同一索引。关系问题无需手写 Cypher。

需要先约束事实类型时，用 `docs/examples/equipment-facts.json` 调用 `/api/v1/ontology/validate`；确认后显式提交 `/facts` 才会导入。也可以用 `/extract` 从带 URI 的来源原文抽取候选事实，返回后再提交。事实入库保留完整原文、来源及引文，再交 LightRAG 抽取合并。

| 接口 | 用途 |
| --- | --- |
| `GET /api/v1/ontology/domain` | 当前领域定义 |
| `POST /api/v1/ontology/extract` | 抽取并校验候选事实，不自动入库 |
| `POST /api/v1/ontology/validate` | 校验事实，不调用索引 |
| `POST /api/v1/ontology/facts` | 校验并导入共享索引，返回文档导入统计 |
| `POST /api/v1/ontology/query` | 以 question/mode/top_k 查询同一 LightRAG |
| `POST /api/v1/lightrag/query-stream` | 流式问答 |
| `POST /api/v1/chat/` | 完整聊天与路由 |

旧图路径参数 `anchor_ids/relation_types/max_hops/limit` 已移除。LightRAG 检索图不保证精确有向路径或逐边事实约束；旧 Neo4j 数据须显式导出并重新导入，本次代码调整不自动迁移数据。

SQL 统计默认关闭。需要时，在领域 JSON 设置 `sql_enabled=true`、`sql_db_type`，并在环境中设置 `SQL_DATABASE_URL`。连接串不放在会公开返回的领域 JSON 中，账号应限制为只读。

完整流程与 API 边界见 [领域知识服务](DOMAIN_KNOWLEDGE.md)，内置数据来源见 [数据血缘](DATA_SOURCES.md)。
