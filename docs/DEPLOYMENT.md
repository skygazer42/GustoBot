# 部署与升级

## 默认服务

`docker-compose.yml` 默认包含后端、MySQL、Neo4j、Milvus。Milvus 的内嵌 etcd 与本地存储配置取自 [Milvus v2.5.12 官方单机脚本](https://github.com/milvus-io/milvus/blob/v2.5.12/scripts/standalone_embed.sh)，配置文件只读挂载，不另起 etcd 或 MinIO。

| 服务 | 镜像/运行时 | 默认宿主机端口 | 持久化 |
| --- | --- | --- | --- |
| backend | Python 3.11；项目支持 3.10–3.13 | 8000 | `uploads_data`；原始 `data/` 只读挂载 |
| mysql | `mysql:8.0.36` | 13306 | `application_mysql_data` |
| neo4j | `neo4j:5.26-community` | 7474、7687 | `facts_neo4j_data` |
| milvus | `milvusdb/milvus:v2.5.12` | 19530、9091 | `documents_milvus_data`，包含内嵌 etcd |
| redis | `redis:7.2-alpine`；仅 `cache` profile | 无默认宿主机端口 | `redis_data` |
| migrate | 后端镜像；仅 `setup` profile | 无 | 显式应用 MySQL 版本迁移后退出 |
| semantic-indexer | 后端镜像；仅 `semantic` profile | 无 | 复用 MySQL generation 与 Milvus 候选集合 |

Redis 不属于当前知识请求的必需依赖。旧 pgvector、KB ingest、LightRAG 索引初始化不在默认部署中。

默认菜谱模型由本地 RDF 清单加载，镜像必须包含 `gustobot/config/ontologies/*.ttl`、领域清单、来源映射和运维 CLI。RDFLib、OWL-RL 和 pySHACL 在应用进程中执行，不另起推理数据库或 JVM。当前模型版本为 `2026-11-17.1`，数值投影版本为 `exact_numeric_v1`。应用不自动把旧图事实、文档或候选标为新版本。设备与通用领域仍按其明确的 YAML 契约工作。

## 配置与启动

```powershell
Copy-Item .env.example .env
# 编辑密码和需要使用的模型服务配置。
docker compose --env-file .env config --quiet
docker compose --env-file .env --profile setup build backend migrate
docker compose --env-file .env up -d mysql neo4j milvus
docker compose --env-file .env --profile setup run --rm migrate
docker compose --env-file .env up -d backend
docker compose --env-file .env ps
```

`DATABASE_URL` 必须使用 `mysql+pymysql://`。示例连接 Compose 的 `mysql:3306`；宿主机程序通过 `localhost:13306` 连接。保持 `MYSQL_*` 与连接串一致，对连接串中的保留字符做 URL 编码。现有 MySQL/Neo4j 卷的账号密码不会因修改环境变量而自动更改。

模型凭据只在运行时通过环境配置提供，不作为镜像 build args。Dockerfile 安装依赖并复制代码和迁移文件；不打包历史知识索引，不执行模型调用或数据导入。`migrate` 使用空 entrypoint，只依赖 MySQL 健康，显式运行幂等迁移后退出。后端入口仅运行 `scripts/migrate_database.py --check`；缺表、缺少迁移或未知版本会阻止 API 启动，不在启动时静默建表。

已有部署必须先完成停写与一致备份，再运行上述显式迁移。单纯启动 `backend` 或 `semantic-indexer` 不等于批准 schema 更新。

## 候选 worker 与健康状态

`SEMANTIC_LINKING_MODE` 默认 `off`。候选索引使用独立集合，集合名由 schema 和 embedding 指纹派生；`MILVUS_COLLECTION` 仍用于原文集合。修改模型名、部署修订或维度后必须建立对应的新候选范围。

```powershell
docker compose --env-file .env exec backend python scripts/build_semantic_index.py status --kind all
docker compose --env-file .env --profile semantic up --build -d semantic-indexer
```

worker 与后端使用相同配置，等待后端健康后执行 `watch`。默认轮询和静默窗口均为 5 秒，同一 scope 的构建由 MySQL 租约竞争；构建与发布算法和手工 CLI 一致。worker healthcheck 的 `os.kill(1, 0)` 只检查进程存活，不代表 scope 已初始化、索引已发布或已经校准。

发布就绪需要检查 `status` 中的领域、本体版本、模型指纹、embedding 指纹、generation 与图 revision。图变化导致实体候选 stale 时，名称／ID 路径仍可工作；旧向量不会冒充当前图。完整审计、投影、发布和模式切换见 [运行手册](RUNBOOK_SEMANTIC_INDEX.md)。

## 显式知识导入

```powershell
docker compose --env-file .env exec backend python scripts/import_knowledge.py recipes --path data/recipe.json --limit 10
docker compose --env-file .env exec backend python scripts/import_knowledge.py documents --path data/kb/data.txt --source-id recipe-history
```

菜谱事实直接映射并校验，不调用抽取模型；原文入库需要 embedding。文档抽取与事实导入是显式操作，上传附件不会自动入库。完整命令选项通过 `--help` 查看。

同一输入重复导入应保持来源与事实身份，变更输入保留新的做法版本。首次导入先使用小范围样例核对单位、未知值、来源和版本，再导入全量。

## 升级现有部署

先备份 MySQL、图数据库、向量索引、上传文件及原始资料，再核对环境配置。当前 Compose 使用新的应用/事实/文档卷名，保留旧 `mysql_data`、`milvus_data`、`kb_pgdata`、`etcd_data`、`minio_data` 等历史卷，启动不会清理这些卷。

旧 SQLite 会话及外部 pgvector 数据不自动成为当前应用数据。按需要导出历史应用记录，或从原始资料重新显式入库。仓库中的 LightRAG 索引和旧图导出已清理；旧 SQL 样例归档在 `data/reference/legacy_mysql/`，不能挂入 MySQL 初始化目录。当前 schema 由版本迁移维护，不执行旧样例库的删除重建脚本。

候选 P0 的同模型旧事实可在停写与完整审计通过后建立 fingerprint/revision 范围，不要求无条件重新生成已核验的事实。正式模型从旧版本升级到 `2026-11-17.1` 时，需要匹配的事实版本、来源发布和数值投影；不能仅回填新 fingerprint 或修改 `ontology_version`。数值投影升级先 `--dry-run`，确认来源与范围后才 `--publish`；它会推进图 revision，随后重建实体 generation。

文档 embedding 模型或维度变化时使用新的 `MILVUS_COLLECTION` 并重新发布原文。候选 embedding 使用独立的 `SEMANTIC_EMBEDDING_REVISION` 与 scope；已有集合校验失败不会自动 drop 或复用错误空间。

模型／数据回退需要一起恢复匹配的模型文件、MySQL、Neo4j、原始资料／上传资产和文档发布范围。仅切换候选 generation 不能恢复被新模型写入替换的事实。先使用 `off`，再验证恢复后的范围与修订；可重建候选不等于可以删除原始证据。

`scripts/verify_knowledge_snapshot.py` 核验已有备份文件的 hash、实际编译模型及导出元数据的一致性。它不连接数据库，也不执行 dump、删除或 restore；`database_restore_verified` 始终为 `false`。备份清单格式、恢复门禁和两类回退的操作顺序见 [运行手册](RUNBOOK_SEMANTIC_INDEX.md)。

停止当前服务可执行 `docker compose --env-file .env down`，保留数据卷。仅在明确要删除当前数据并已完成备份时才考虑卷删除操作；升级不需要 `down -v`。

## 验证与诊断

```powershell
docker compose --env-file .env config --quiet
docker compose --env-file .env logs --tail 100 backend mysql neo4j milvus
python -m pip install -r requirements-dev.txt
python -m pytest tests/test_backend_deployment.py
```

部署回归会用独立临时环境文件渲染 Compose，并执行迁移成功/失败的入口脚本替身。它不会读取真实 `.env`，也不会启动或修改数据库。图集成测试需要显式设置 `GUSTOBOT_TEST_NEO4J_CONFIG`，其 JSON 包含隔离测试服务的 `uri/user/password/database`；测试仅清理自己生成的 UUID 领域。

配置可解析不等于外部服务已联通。发布前还需核对实际 MySQL 迁移、Neo4j 事实与来源、Milvus embedding 维度和检索，以及使用者配置的模型服务。完整知识接口见 [领域知识服务](DOMAIN_KNOWLEDGE.md)。
