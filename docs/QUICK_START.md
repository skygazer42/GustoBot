# GustoBot 快速启动

## Docker Compose

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：更换 `MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD`、`NEO4J_PASSWORD`，并同步 `DATABASE_URL` 中的应用账号和密码。连接串中的保留字符需要 URL 编码，`MYSQL_PASSWORD` 保留原密码。示例使用 Compose 内部主机名 `mysql`、`neo4j`、`milvus`。

聊天和 embedding 均使用 OpenAI-compatible 接口，无需填写模型商。将示例中的占位地址和模型 ID 替换为服务实际暴露的值；两种接口可使用同一网关，也可分别配置：

```dotenv
LLM_BASE_URL=https://your-api.example/v1
LLM_API_KEY=your-api-key
LLM_MODEL=your-chat-model
EMBEDDING_BASE_URL=https://your-api.example/v1
EMBEDDING_API_KEY=your-api-key
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_DIMENSION=1536
```

图事实导入和类型校验不调用模型；文档入库需要 embedding，文档事实抽取和一般答案生成需要聊天模型。`EMBEDDING_DIMENSION` 必须匹配实际模型输出。

```powershell
docker compose --env-file .env config --quiet
docker compose --env-file .env --profile setup build backend migrate
docker compose --env-file .env up -d mysql neo4j milvus
docker compose --env-file .env --profile setup run --rm migrate
docker compose --env-file .env up -d backend
docker compose --env-file .env logs -f backend
```

默认服务为后端、MySQL 8.0、Neo4j 5.26 和 Milvus 2.5。Milvus 使用内嵌 etcd 与本地对象存储。`setup` profile 的 `migrate` 服务显式应用迁移；后端等待存储健康后只执行 `scripts/migrate_database.py --check`，不补表、不修改 schema。首次启动缺少迁移时，先运行迁移命令再启动后端。构建和启动不导入数据、不调用模型。

| 地址 | 用途 |
| --- | --- |
| `http://localhost:8000/docs` | API 文档 |
| `http://localhost:8000/health` | 后端健康检查 |
| `http://localhost:7474` | Neo4j Browser |
| `localhost:13306` | MySQL 宿主机连接 |
| `localhost:19530` | Milvus 宿主机连接 |

端口可在 `.env` 中调整。Redis 不参与默认请求链；需要保留的可选服务时可执行 `docker compose --env-file .env --profile cache up -d redis`。

## 导入样例

先导入少量菜谱事实，核对领域、来源和做法版本：

```powershell
docker compose --env-file .env exec backend python scripts/import_knowledge.py recipes --path data/recipe.json --limit 10
```

去掉 `--limit` 可导入整个输入文件。相同源记录重复导入保留身份；内容变化产生新的来源与做法版本，不按同名覆盖其他做法。

原文导入是独立操作：

```powershell
docker compose --env-file .env exec backend python scripts/import_knowledge.py documents --path data/kb/data.txt --source-id recipe-history
```

CLI 支持的完整选项以 `python scripts/import_knowledge.py --help` 为准。容器将仓库 `data/` 只读挂载为 `/app/data`；其他文件先放入可读来源目录，或使用上传与知识入库 API。

## 本地 Python

Python 支持 3.10–3.13。可以仅用 Compose 启动存储，再在宿主机运行 Python：

```powershell
docker compose --env-file .env up -d mysql neo4j milvus
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "mysql+pymysql://gustobot:YOUR_URL_ENCODED_PASSWORD@localhost:13306/gustobot?charset=utf8mb4"
$env:NEO4J_URI = "bolt://localhost:7687"
$env:MILVUS_HOST = "localhost"
python scripts/migrate_database.py
python scripts/migrate_database.py --check
python -m uvicorn gustobot.main:application --reload
```

将示例密码替换为实际密码，使用调整后的宿主机端口。开发检查工具安装命令是 `python -m pip install -r requirements-dev.txt`。

## 前端与领域

另开终端执行：

```powershell
Set-Location web
npm install
npm run dev
```

要切换设备样板，在 `.env` 中设置 `KNOWLEDGE_DOMAIN_FILE=gustobot/config/domains/equipment.yaml` 后重启后端。另有 `generic.yaml`；每个领域需要自己的资料。默认菜谱的 YAML 是 RDF 加载清单，正式定义来自本地 OWL/RDFS 与 SHACL，当前版本为 `2026-11-17.1`。设备和通用样板使用 YAML 定义。修改定义后需要重启；版本升级还需要匹配的数据发布步骤。

## 可选语义候选

保持 `SEMANTIC_LINKING_MODE=off`，填写实际 embedding 部署修订 `SEMANTIC_EMBEDDING_REVISION`。审计不会把旧事实直接改标成当前模型：

```powershell
docker compose --env-file .env exec backend python scripts/build_semantic_index.py bootstrap --audit
docker compose --env-file .env exec backend python scripts/build_semantic_index.py status --kind all
```

只有在停写、备份和完整审计通过后，才显式运行 `bootstrap --apply-scope`。数值投影升级按 `scripts/rebuild_numeric_projection.py --dry-run`／`--publish` 处理，然后再构建候选。候选预构建命令是 `build --kind all`；发布需要明确加 `--publish`。

完成手工发布与核验后，可启动持续重建 worker：

```powershell
docker compose --env-file .env --profile semantic up --build -d semantic-indexer
```

worker 复用后端配置、等待后端健康，每 5 秒轮询并等待 5 秒静默窗口。其 healthcheck 仅检查 PID 存活。`ready` 状态、当前图 revision、校准和业务验收共同决定是否可从 `off` 进入 `shadow`／`on`，步骤见 [候选索引运行手册](RUNBOOK_SEMANTIC_INDEX.md)。

聊天入口为 `POST /api/v1/chat/`，事实 API 前缀为 `/api/v1/ontology`。同名做法有歧义时先选择具体版本。附件阅读不会自动持久化为知识；长期入库必须显式发起。

接口与结果完整性见 [领域知识服务](DOMAIN_KNOWLEDGE.md)。已有部署升级与旧卷保留见 [部署](DEPLOYMENT.md)。
