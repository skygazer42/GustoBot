# 语义候选索引、发布与恢复

当前候选协议为 `semantic_candidates_v2`。来源目录保存有限样本、完整计数和摘要，避免共享节点来源列表超出 Milvus 字段大小。升级后重建新集合及 generation；v1 指针不能作为 v2 就绪依据。完整证据保留在事实图。

在线 ANN 使用 `SEMANTIC_ANN_TIMEOUT=1`；离线构建使用独立连接和 `SEMANTIC_BUILD_OPERATION_TIMEOUT=30`。集合首次加载使用 `SEMANTIC_INITIALIZATION_TIMEOUT=30`，候选 embedding 默认 3 秒，文档／构建 embedding 默认 60 秒，SDK 不自动重试。构建与在线客户端的 timeout 不能合并。

Compose worker 显式使用 `SEMANTIC_INDEX_BATCH_SIZE=512`；embedding SDK 仍以最多 64 条文本拆批。离线两万条实验中，批次 512 的单条变更重建约 270 秒，批次 128 约 401 秒；共享机器上非同时对照的结果用于选择起点，不作为固定提速承诺。直接使用构建 CLI 时可加 `--batch-size 512`，根据部署内存与提供方批量限制调整。

当前正式菜谱模型为 `2026-11-17.1`，数值投影为 `exact_numeric_v1`。Neo4j 是事实与图修订权威，MySQL 保存应用／来源发布和候选 generation 指针，Milvus 保存可重建的文档与候选向量。跨三个存储的切换不是一个事务。

## 首次启动与迁移

先复制 `.env.example` 并配置部署凭据。模型 key 不进入镜像、备份清单或日志。以下命令中的 `.env` 是操作者显式指定的运行配置；快照核验工具不读取它。

```powershell
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build
docker compose --env-file .env exec backend python scripts/migrate_database.py --check
```

Compose 等待一次性 `migrate` 任务成功后启动应用。后端和 worker 入口均执行 `--check`。Redis 仍使用可选 `cache` profile，候选索引通过后续发布流程建立。

## 建立当前事实范围

保持 `SEMANTIC_LINKING_MODE=off`，配置明确的 `SEMANTIC_EMBEDDING_REVISION`；同一模型别名的部署内容改变时也要修改修订。它与提供方、模型、维度和序列化契约共同确定 embedding 指纹，不包含 key。

1. 停止旧写入者、批量导入任务和候选 worker，排空在途写入。
2. 保存匹配的模型、MySQL、Neo4j、原始资料／上传资产与文档发布范围快照。
3. 只读审计当前事实及身份、引文、版本。违规或来源不明时先处理报告，不回填当前指纹。

```powershell
docker compose --env-file .env exec backend python scripts/build_semantic_index.py bootstrap --audit
```

审计通过且仍处于停写窗口时，明确建立 scope：

```powershell
docker compose --env-file .env exec backend python scripts/build_semantic_index.py bootstrap --apply-scope
```

同模型可核验的旧事实可通过这一步建立 fingerprint/revision 范围。真正空图在审计确认无待处理事实后以 revision 0 初始化；存在有效旧事实时从 revision 1 起步。未初始化范围不能以空实体 generation 冒充就绪。

正式模型从旧版本升级到 `2026-11-17.1` 时，先恢复／导入与当前模型匹配的明确来源。不能给未知或旧版本事实直接贴新版本标签。审计不代替模型迁移。

## 数值投影与候选构建

先检查当前正式范围的投影：

```powershell
docker compose --env-file .env exec backend python scripts/rebuild_numeric_projection.py --dry-run --batch-size 100
```

核对实际处理数量、来源、未知／不兼容项后，显式发布派生值：

```powershell
docker compose --env-file .env exec backend python scripts/rebuild_numeric_projection.py --publish --batch-size 100
```

发布会推进图 revision；应在这一步之后建立实体候选。单项投料、做法合计和 reported/prep/cook/total 时长各有正式口径；定性量、未知来源和不兼容单位不补成零。

预构建默认不切换指针：

```powershell
docker compose --env-file .env exec backend python scripts/build_semantic_index.py build --kind all --batch-size 64
docker compose --env-file .env exec backend python scripts/build_semantic_index.py status --kind all
```

正式发布需要明确的 `--publish`：

```powershell
docker compose --env-file .env exec backend python scripts/build_semantic_index.py build --kind concept --batch-size 64 --publish
docker compose --env-file .env exec backend python scripts/build_semantic_index.py build --kind entity --batch-size 64 --publish
docker compose --env-file .env exec backend python scripts/build_semantic_index.py status --kind all
```

回执保留 generation、graph revision、导出／embedding／复用数和错误。状态为 `building/ready/active/retired/failed/superseded`。实体构建读取 R0、keyset 导出、按文本 hash 复用向量、实际核验数量和 checksum，再核对 R1；R0≠R1 标为 superseded。概念不依赖实例图 revision。

MySQL 在短事务内锁定 scope，以预期旧指针 CAS 发布并退役旧 active。外部 I/O 不持有该事务。失败、取消、旧 revision 或竞争发布不覆盖 active；SDK retries 固定为 0，下一次构建是明确的新尝试。同一 scope/revision 重试可复用已写向量。

## 校准、shadow 与 on

首次发布没有自动附带校准。校准 ID 必须绑定相同正式模型、embedding 空间、generation 和受审数据集。策略字段仅接受 `min_cosine/margin/dataset_hash`，数值必须是实际验证所得；不能用示例中的固定阈值宣称语义质量已验收。

评测保留集和校准集分开。先将冻结夹具绑定当前正式 ID，再运行实际提供方召回／问答：

```powershell
python scripts/evaluate_knowledge.py --mode protocol --dataset eval/knowledge/questions.jsonl --output docs/evaluation/materialized --scope recipes --materialize
python scripts/evaluate_knowledge.py --mode retrieval --dataset docs/evaluation/materialized/calibration.jsonl --output docs/evaluation/calibration --scope recipes --linking-mode shadow --calibrate
```

评测命令的 `--linking-mode` 必须与明确配置的运行模式一致。生成候选策略不代表自动通过保留集或批准发布；协议夹具、实际 embedding 和实际生成模型的报告分别统计。实际 key 与价格由部署者显式配置，缺失 token／价格保持未知。

对同一冻结问题集依次保留 `off` baseline、`shadow` 对照与 `on` 报告。`shadow` 必须保持原计划、选中对象和回答结构；检索质量、条件保留、来源证据及 provider 故障门禁通过后才进入 `on`。报告 hash、模型／embedding 指纹和人工核对记录一并归档。实际提供方延迟与吞吐需要 concurrency 1/5/20 的测量，不从协议测试推断。

保留集测量在隔离评测 runtime 内应用候选策略，不提前修改生产 MySQL 指针。校准集和保留集必须是不同问题与 hash；保留集至少 200 条，并包含由人核对的真实来源问题。冻结数据、真实 HTTP 计数、源文／定量答案人工核对、条件与证据门禁、off→shadow→on 对照链缺失时，不能导出可发布报告。

在隔离评测配置中分别设置实际 `SEMANTIC_LINKING_MODE`，依次运行：

```powershell
python scripts/evaluate_knowledge.py --mode qa --dataset docs/evaluation/materialized/questions.jsonl --output docs/evaluation/baseline-off --scope recipes --linking-mode off
python scripts/evaluate_knowledge.py --mode qa --dataset docs/evaluation/materialized/questions.jsonl --output docs/evaluation/heldout-shadow --scope recipes --linking-mode shadow --compare-baseline docs/evaluation/baseline-off/report.json
python scripts/evaluate_knowledge.py --mode qa --dataset docs/evaluation/materialized/questions.jsonl --output docs/evaluation/heldout-on --scope recipes --linking-mode on --runtime-factory eval.knowledge.runtime_factory:create_runtime --candidate-calibration-report docs/evaluation/calibration/report.json --compare-baseline docs/evaluation/heldout-shadow/report.json --human-verification REVIEW/human-verification.json
```

最后一条使用进程内只读策略覆盖，校验候选校准的真实 scope、generation 和 revision；不修改生产发布表。人工核对文件必须绑定实际 dataset 和 fixtures hash、reviewer、reviewed_at 及定量／证据裁决，不能用占位内容通过验收。

已有匹配证据后，导出明确的批准工件，再把它附到当前 active generation：

```powershell
python scripts/evaluate_knowledge.py --mode qa --scope recipes --output docs/evaluation/approved-entity --approve-calibration docs/evaluation/calibration/report.json --heldout-report docs/evaluation/heldout-on/report.json --kind entity --generation ACTIVE_ENTITY_GENERATION_ID
docker compose --env-file .env exec backend python scripts/build_semantic_index.py calibrate --generation ACTIVE_ENTITY_GENERATION_ID --report /app/data/approved-calibration.json --expected-active-generation ACTIVE_ENTITY_GENERATION_ID
```

将导出的 `approved-calibration.json` 放入受控、只读可访问的部署路径；示例使用 `data/` 挂载。概念策略用相同流程对 `--kind concept` 与其真实 generation 单独验收和附加，不能用实体策略代替概念验收。

CLI 重新验证工件内嵌的实际报告、冻结 hash、模型／embedding、generation、revision、拆分与门禁。之后在短 MySQL 事务中 CAS 核对 active 指针。失败保留旧策略，成功不重算 embedding 或改写候选向量。数据库的 `calibration_id` 保存批准文件**实际字节**的 SHA-256，原 evaluator calibration ID 保留在该文件中；改变格式也会得到新的不可变工件 ID。

## worker、状态与清理

```powershell
docker compose --env-file .env --profile semantic up --build -d semantic-indexer
docker compose --env-file .env exec backend python scripts/build_semantic_index.py watch --kind all --poll-seconds 5 --quiet-seconds 5
```

两种启动方式任选一种；不要为了每条导入重复启动 worker。它等待安静窗口后执行同一个 build，并使用 MySQL scope 租约竞争。失败有可见终态并限制下一次尝试。worker healthcheck 只证明 PID 存活；索引可用性须读 `status` 并核对当前图 revision。图 stale 时不能复用旧实体向量作当前事实候选。

确认 generation 不再是 active、无在途查询依赖且已有恢复资料后，才执行明确退役：

```powershell
docker compose --env-file .env exec backend python scripts/build_semantic_index.py retire --generation RETIRED_GENERATION_ID
```

active 和有效构建租约受到保护。CLI 不提供任意 collection drop；不要用删除原始资料替代索引清理。

## 一致快照清单

快照前先关闭语义候选并停止所有写入者，排空在途任务。在同一个停写窗口取得 MySQL、Neo4j、原文／上传文件和向量备份。数据库 dump、文件复制和存储恢复由部署者或已有备份系统执行，本工具不执行这些操作。

把已有工件放入同一个独立目录，并创建 `snapshot-input.json`。下列路径均相对该目录，不接受跨目录路径或 `.env`：

```json
{
  "snapshot_id": "capture-20261117-a",
  "model": {
    "ontology": "model/recipes.ttl",
    "shapes": "model/recipes.shacl.ttl",
    "resources": ["model/schema-recipe-subset.ttl"]
  },
  "mysql": {"dump": "mysql.sql", "metadata": "mysql-scope.json"},
  "neo4j": {"dump": "neo4j.dump", "metadata": "graph-scope.json"},
  "sources": [{"source_id": "source-a", "version": "SOURCE_VERSION", "asset_id": "asset-a", "path": "sources/source-a.txt"}],
  "assets": [],
  "documents": "documents.json",
  "candidates": "candidates.json",
  "vector_backups": {"documents": "documents.export", "candidates": "candidates.export"}
}
```

`scope` 在下列元数据中均为 `domain_id/ontology_version/ontology_fingerprint`。工具从保存的 ontology、SHACL 和本地词汇文件实际编译 fingerprint，不接受操作者任意声明模型身份。

| 文件 | 必需字段与来源 |
| --- | --- |
| `mysql-scope.json` | `capture_id/scope/graph_revision/schema_revisions/sources/asset_ids`；来源行包含 `source_id/version/ontology_version/status/asset_id`，仅列当前已发布范围 |
| `graph-scope.json` | `capture_id/scope/graph_revision/source_ids/sample_entity_ids/numeric_projection_version`；修订来自停写后的图控制记录 |
| `documents.json` | `capture_id/scope/collection/embedding_model/dimension/publications`；publication 为 `source_id/version/entity_ids` |
| `candidates.json` | `capture_id/publications/generations`；分别为 `IndexPublicationStatus` 与 `IndexGeneration` 的 JSON；需完整保留 scope、修订、状态、计数与 checksum |

MySQL 和图元数据可附 `graph_state`，默认 `ready`；未初始化时须明确 `uninitialized` 且 revision 为 null。`initializing` 不接受为静止快照。每个 MySQL `asset_id` 必须在来源行或 `assets` 中有明确已有文件；尚未发布的上传文件也应通过 `assets` 备份。原文和 dump 内容不打印到输出。

升级前尚无候选发布表时，保存实际 `schema_revisions`，并在 `candidates.json` 中提供空的 publications／generations。核心快照仍可保存；报告会要求 `publication_schema_missing`，候选不得复用。恢复旧版本应使用其匹配应用；推进到当前应用前，先在隔离副本显式执行所需迁移，不把启动的只读 check 当成迁移。

```powershell
python scripts/verify_knowledge_snapshot.py create --spec BACKUP/snapshot-input.json --output BACKUP/manifest.json
python scripts/verify_knowledge_snapshot.py verify --manifest BACKUP/manifest.json
python scripts/verify_knowledge_snapshot.py verify --manifest BACKUP/manifest.json --expect-scope BACKUP/expected-scope.json --require-candidates
```

`expected-scope.json` 是计划恢复运行的正式 scope，可附 `embedding_fingerprint/index_schema_version`。工具记录文件大小与 SHA-256，核对 capture ID、实际模型、图 revision、来源发布与资产完整性。已有 manifest 不覆盖；重新拍摄使用新目录和 capture ID。

没有向量备份时，核心快照仍可能有效，但 `candidate_compatible=false`，并输出保持 `off` 与重新构建的清单。candidate 的模型、embedding、schema、revision、发布指针或 generation 校验字段不兼容也要求重建。`--require-candidates` 对这种情况返回非零。文档向量缺失时，`document_rebuild_required=true`，先按保存的来源版本和 entity links 重新发布原文。

`valid=true` 仅表示文件 hash、编译模型和导出元数据一致；工具不解析数据库 dump 的内部语义、不证明导出时真正停写、不验证备份可恢复性或签名可信度，`database_restore_verified` 始终为 `false`。保留可信备份系统的签名／审计记录，并完成独立恢复演练。

## 两种回退与恢复门禁

**候选功能回退**：保持现有正式模型和事实版本，先将 `SEMANTIC_LINKING_MODE=off` 并重启相关进程。只有模型、embedding、schema 和当前图 revision 都匹配且已经验证的 generation 才能恢复使用。当前 CLI 不提供任意旧指针回退或 retired generation 重新激活选项；不兼容时按当前 scope 重建，不能伪造指针状态。

**本体／数据回退**：停止新旧写入者和 worker，恢复同一个 capture 的正式模型、Neo4j、MySQL 来源／任务／发布、原始资料／上传资产与文档发布范围，再核对身份、版本、计数和样例答案。新模型 upsert 可能替换同一 ID 的图属性，仅改候选指针不能撤销这些写入。禁止会写同一身份空间的新旧模型同时运行。

实际恢复应在隔离服务完成：验证 dump 可加载、来源文本和 entity IDs 一致、MySQL FK／发布指针正确、图 revision 和数值投影匹配、文档与候选可检索。先保留 `off`，缺少备份的索引按清单重建；故障注入覆盖 embedding 不可用、Milvus 重启、图更新、MySQL 发布失败和取消。最后完成真实提供方保留集、业务真值与证据对齐检查，才允许 `shadow`／`on` 切换。

清单核验、实际数据库恢复、真实提供方语义质量和正式发布是四个独立门禁；每次交付记录实际执行结果与未执行项。
