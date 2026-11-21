# 领域、事实与原文知识服务

默认菜谱领域使用正式 OWL/RDFS 定义、SHACL 形状及存储/查询绑定，由 RDFLib、OWL-RL 和 pySHACL 实际执行。定义与验收依据见[案例复核](ONTOLOGY_CASE_REVIEW.md)。支持范围是明确的本地片段，不提供完整 OWL DL 或任意规则语言。

## 权威定义与存储

`KNOWLEDGE_DOMAIN_FILE` 选择领域。默认 `config/domains/recipes.yaml` 只是 `format: rdf`、本体和形状两个路径的加载清单。菜谱语义的维护来源为 `config/ontologies/recipes.ttl`、`recipes.shacl.ttl` 及本地 Schema.org 子集；数据源字段映射位于 `config/mappings/recipes.yaml`。设备与通用领域保留明确的旧 YAML 契约，不在正式模型失败时回退。

| 正式定义或编译结果 | 作用 |
| --- | --- |
| `id`、`version`、模型 fingerprint | 领域及正式语义版本，约束事实、文档与候选检索范围 |
| OWL 类与属性 | 业务概念、类型层次、关系域值域与被支持的关系公理 |
| SHACL 形状 | 入库断言、关系属性、数量类型和问题专属证据约束；违规返回实际报告 |
| 身份绑定 | 类上的策略、主键与前缀驱动实例 ID；同名食材可共享，来源做法及步骤独立 |
| 业务属性绑定 | `ingredientQuantity/steps/reportedTime` 等业务请求映射到本体关系、物理投影、返回属性和答案形状 |
| 单位声明 | 量纲、别称及比例驱动精确数值/区间换算，定性量和未知单位不伪算 |
| `classes/allowed_edges/lexicon` | 编译产生的原生存储/抽取契约与词汇目录，不另行手写一份菜谱 Schema |
| `vocabularies/external_refs` | 来源和参考映射；实际 Schema.org 层次来自加载的本地标准子集，URI 注释不当作公理 |
| `document_scope`、`interpretation_notes` | 资料边界、未知值含义和统计粒度等解释约定 |

加载器执行命名类/属性的 OWL-RL 闭包，编译身份、SHACL 原生约束与业务属性；未知构件、任意 SPARQL/JS 规则及远程 imports 明确拒绝。输入先按原始断言校验，再推导，避免域/值域推断掩盖原始错误。答案只验证当前对象与业务请求的证据形状，保留嵌套形状执行，不把任意投影当完整对象。编译模型不可变，返回的领域及 RDF 图副本隔离；修改正式定义须升级版本并重启进程。

这一区分参考青皮书第 123–129 页的映射、粒度和口径，以及第 319–323 页知识检索场景的类、允许边、规则与子图形状。没有把财务指标模型原样移植到菜谱，也没有仅将类型 Schema 改名为本体。

现成词汇及本地映射的核查见[菜谱本体复用](ONTOLOGY_REUSE.md)：优先裁剪 Schema.org Recipe/HowTo，参考 WhatToMake 的业务关系，按需对齐 FoodOn 食材术语。复用对照保留外部 IRI、发布版本与转换条件；本地定义继续执行做法版本、原始用量与证据约束。

本地 Schema.org 30.1 子集实际参与类继承推导；WhatToMake 当前仍是参考对照，不声称加载其全部语义。糖类及其细分类是有限的本地受控定义，FoodOn 的中文食材词义需明确后再接入。原始耗时不被强行等同烹饪时间或总时间。

语义图表达为“具体做法 → 食材使用项 → 食材/数量/证据”；原生 Neo4j 食材关系的稳定 ID 投影为使用项身份。一个共享食材不会携带某份做法的全局用量。数量分为精确数值、范围与定性表达；例如 `1000 mg → 1 g` 由本体单位比例和确定算法计算，保留原值、前提、规则及模型指纹。红糖属于糖类时，范围由实际类型闭包展开；白糖不会因此与红糖等同。

## 接入与来源

结构化菜谱使用 `recipe_to_facts(name, record, domain=...)` 按来源映射确定取值，通过模型身份声明生成对象 ID，不调用 LLM。普通文档候选抽取使用编译出的类型枚举，一次模型调用后统一绑定身份、检查引文并执行 SHACL；显式事实写入同样验证，不重新抽取。

食材用量在 `HAS_MAIN_INGREDIENT`、`HAS_AUX_INGREDIENT` 关系上保留 `amount_text`、`unit` 和 `role`。原始“适量”“半小时”“数天”保持原文；缺失用量、耗时或食材关系不变成零，也不证明“不含”。

普通文档可以只保存原文分块，也可以显式请求事实抽取。事实抽取使用一次结构化模型调用，随后由代码校验类型、端点、属性和逐字引文。已校验的事实直接写入 Neo4j，不再转成文本重新抽取。

显式入库 API 前缀为 `/api/v1/knowledge`：

| 接口 | 输入与结果 |
| --- | --- |
| `POST /documents` | `text` 或受管 `asset_id` 二选一；可附 `source_id/uri/entity_ids/metadata`，返回 201 入库回执 |
| `POST /recipes` | `{name, record}` 原始菜谱记录；直接映射到图，返回 201 回执 |
| `POST /recipes/batch` | `{name, record}` 数组；失败时保留已完成项与失败任务信息 |
| `POST /query` | `{question}`，返回无会话的统一答案、来源与调用信息 |
| `GET /jobs/{job_id}` | 查询任务、来源版本、状态、错误与详细结果 |
| `DELETE /sources/{source_id}` | 撤回该原文来源的所有文档版本，保留历史与证据；图事实来源不可用此接口撤回 |

回执包含 `job_id/domain_id/source_id/version/ontology_version/kind/status/details/error`。文档成功状态为 `ready`，菜谱事实成功状态为 `graph_ready`。上传结果中的 `asset_id` 对应受管资产身份，入库请求不接收客户端提供的服务器路径。文档入库不自动抽取图事实；需要时先调用 `/ontology/extract`，再显式提交 `/ontology/facts`。

`entity_ids` 省略或为 `null` 表示保留已有实体链接，显式 `[]` 才清空。作业终态与知识发布状态分开：已发布内容在同版本重试期间仍可检索，失败、取消或并发迟到失败不能撤销已成功发布的版本。新内容导入失败不会代替旧的有效版本。

图事实的 `SourceDocument` 保存完整 `text` 和可选 `uri`；每个实体与关系必须有 `source_id`、`quote`。引文必须存在于输入原文。相同事实 ID 重复写入更新明确给出的属性，并保留已有来源引文；图内同一来源 ID 的原文和 URI 不可悄然替换，变化来源使用新 ID。文档入库则通过 `source_id` 与内容 `version` 区分来源更新，回执保留实际版本。

## 本体 API

路径前缀为 `/api/v1/ontology`：

| 接口 | 行为 |
| --- | --- |
| `GET /domain` | 返回当前领域定义 |
| `POST /extract` | 来源原文 → 一次模型抽取 → 校验 → 返回候选，不自动持久化 |
| `POST /validate` | 校验实体、关系、属性和引文，返回数量，不访问图数据库 |
| `POST /facts` | 校验并事务写入 Neo4j，返回处理的实体、关系、来源数量 |
| `POST /query` | 执行受控的结构化事实查询，返回事实、完整来源和数量信息 |

抽取请求示例：

```json
{"sources":[{"id":"manual-v1","text":"泵 A 包含轴承 B。","uri":"manual.pdf"}]}
```

图查询示例：

```json
{
  "entity_type": "RecipeVariant",
  "anchor_names": ["佛跳墙"],
  "relation_types": ["HAS_MAIN_INGREDIENT", "HAS_AUX_INGREDIENT"],
  "target_names": ["糖"],
  "operation": "lookup",
  "max_hops": 1,
  "limit": 20
}
```

图 API 可查看多个版本的候选做法事实；聊天层在对象不明确时先澄清。`anchor_ids` 是明确身份列表；`anchor_names` 对规范名称或已批准别名精确匹配，多个名称按 OR 筛选，最多 10 个。名称范围直接在数据库中执行，不把最多 10 条实体候选当成完整计数范围。

`target_names` 是对每个锚点的 AND 条件：每个名称都必须沿允许的有向路径可达。返回路径只指向请求的目标。`filters` 作用于锚点属性，必须同时声明 `entity_type`，支持 `eq/ne/lt/lte/gt/gte/in`；有序比较仅支持数值属性。属性缺失不会满足 `ne`。

`max_hops` 为 1–3，`limit` 为 1–100；标签、关系和属性名按本体校验，用户文字作为 Cypher 参数。接口不接收任意 Cypher 或 SQL，也不支持未经完整性证明的关系排除条件。

## 结果范围与版本

结果包含 `entities`、`relations`、`sources`、`total`、`truncated`、`ontology_version`。

- `operation=count`：`total` 是完整匹配范围内的不同锚点数量；实体和来源只是受 `limit` 限制的样本。
- 属性 lookup：`total` 是不同锚点数量。
- 关系 lookup：`total` 是不同有向路径数量，先计数再应用展示限制；实体和关系在返回样本内去重。
- `truncated=true` 表示展示样本被截断。计数仍以完整范围计算，不从样本长度推断总数。

候选实体、查询锚点以及路径中的每个节点和关系都必须属于当前领域与本体版本。切换本体版本后，旧事实不会被标为新版本返回；需要显式重新导入或发布。来源原文作为不可变证据保留，不能通过改版本号自动迁移历史知识。

## 概念、实体候选与发布

概念目录来自已编译的正式类与业务属性；实体目录只覆盖当前版本的 RecipeVariant、Ingredient、CuisineStyle、CookingMethod、DishType、Flavor。步骤、证据和量值不逐项生成候选 embedding。原文分块继续使用独立的文档集合。

候选 scope 包含 `domain_id/ontology_version/ontology_fingerprint/embedding_fingerprint/index_schema_version/kind`。Neo4j 事实和图修订是权威，MySQL 只发布经过验证的 generation，Milvus 候选可以重建。构建前后图 revision 不一致时结果为 `superseded`；失败、取消或 CAS 竞争不会覆盖当前 active 指针。概念 generation 不随实例 revision 失效。

完整 ID、规范名称和批准别名优先；全文与 ANN 只提供真实 ID 候选，必须回读当前图、检查记录 hash 并恢复完整同名族。向量分数不会成为事实、同义词裁决或答案依据。来源做法有多个版本时仍需澄清，候选 top-k 不代表全库查询范围。

`off` 使用现有受控路径；`shadow` 记录候选差异而不改变当前选中对象或答案；`on` 使用已发布范围和匹配的校准策略。缺少校准不会采用任意余弦阈值自动绑定。图 stale、provider 错误、空记录和未初始化 scope 分开报告，不能伪装为“数据库没有记录”。上线步骤见 [运行手册](RUNBOOK_SEMANTIC_INDEX.md)。

## 统一聊天与附件

聊天使用一个轻量问题计划，引用正式模型允许的业务属性和已经回读的对象，可同时读取事实和原文。一次计划可以选择糖的用量和做法耗时，程序校验引用、方向和深度再编译为参数化 Cypher。简单问题可走确定路径；复杂知识问题最多一次规划和一次最终答案生成。embedding 与 rerank 单独计数，候选召回不增加一轮生成模型调用。未支持的条件需要澄清，不悄悄丢弃。

正式菜谱的模型输出业务请求列表，例如 `requests=[{property: ingredientQuantity, target: 糖类, unit: g}, {property: reportedTime}]`。引擎读取正式属性绑定，展开类型和子属性范围，生成原生查询；LLM 不输出物理字段或关系清单。空业务 lookup 会澄清，计数只能使用条件，不能悄悄忽略属性请求。非数量属性不能接受单位，标量耗时也不能接受一个食材目标。

正向条件使用 AND 名称组／组内 OR 候选，可为每组限制所属关系。属性投影与条件分别编译，缺少一种属性不会消除已经匹配的做法；投影的目标筛选在展示 limit 之前执行。`include_anchors` 保留锚点属性，`truncated` 同时反映锚点和路径证据的截断，不把局部样本作为全量依据。

取回事实后，稳定关系投影为语义使用项，执行本体推导、数量求值与当前问题的 SHACL 形状。`metadata.semantic_evaluation` 保留结果、违规诊断、asserted 事实与 inferred/converted 的规则、前提和模型指纹。数量来源只取当前做法/用料断言的证据，不因共享食材附带其他做法来源；步骤按正式顺序属性排列。校验失败不会走旧格式化器或把错误事实交给模型补齐。

正式求值一旦含有违规或不支持计算的诊断，程序直接返回其确定裁决，最终生成模型不再调用，也不引用已检索但未使用的原文。部分事实有效时只保留其已验证结果和缺口。单纯无记录且没有校验违规时，仍可按明确来源范围查询原文。

### 正式语义支持边界

本轮支持本地命名类的继承、命名子属性、声明的逆属性及有界属性链的 OWL-RL 物化。业务查询的存储投影必须能确定地编译为支持的正向原生关系；反向或复杂链若无对应投影会明确拒绝，不宣称任意 OWL 查询规划。SHACL 支持本地类型/基数、数据类型、数量范围、嵌套形状与受控步骤唯一约束；不执行任意 SPARQL、SWRL、JS 或网络 imports。普通文档语义质量、别名裁决、食材外部对齐仍依赖业务与来源，不由推理补造。

当前模型版本为 `2026-11-17.1`，精确数值投影版本为 `exact_numeric_v1`。原生实体身份及证据语义按正式声明生成，旧模型的数据不自动改版；旧事实与文档需按来源显式发布，不允许仅修改版本标签伪装兼容。代码和迁移命令的存在不表示真实数据已完成迁移。

数值筛选和排序覆盖单项投料 `ingredientUsageAmount`（`usage`）、每份做法合计 `ingredientTotalAmount`（`recipe_total`）以及 `reportedDuration`。原文笼统耗时属于 `reported_unspecified`，不会冒充 `prep/cook/total`。比较使用模型声明的精确整数 tick，在完整数据库范围内过滤、聚合、排序后再展示；并列按稳定 ID 排序。

`numeric_conditions` 保留业务属性、`target_ref`、粒度、单位、比较符和精确字符串／整数。`between` 使用 `minimum/maximum`。定性量、未知单位、范围跨阈值和未记载时长分别计入未知、不确定或不可比较，不转成零。单位不兼容、不能整除 tick 或 int64 溢出会明确拒绝比较。旧 projection version 必须经过显式审计与重建。

请求元数据按 document/candidate/build/analysis/generation/rerank 区分逻辑调用、provider batch、实际 HTTP 尝试、输入数量与时长。token 用量只有提供方实际返回时才记录，缺失保持未知；这些计数不等于已完成真实提供方的质量、成本或延迟验收。

确定路径只接受完整对象名、已确认别名或唯一 ID；带时间等限定的名称片段必须回到语义理解。普通原文可独立回答，不要求预先抽成图。普通单对象问题默认可同时使用事实和已发布原文，即使图谱已经命中，也能补充相关文章。文档范围可沿正式本体绑定和实际正向关系扩展到非拥有、非重化的规范概念；该辅助查询只选择文章范围，不把其他对象属性并入主事实。集合查询使用完整数据库范围，不以最多 10 个候选代替全量；集合的原文补充限定在实际返回的对象，样本截断会标记部分结果。

前台选择菜谱后，将完整的当前菜谱原文作为 `SelectedKnowledgeContext` 交给同一查询服务。菜谱适配器提供已确认的概念 ID、可惰性执行的概念事实查询和文档检索词；跨名称文章背景关联核对目录 ID 与版本。缺少具体图谱配方映射时，不按菜名猜测 `RecipeVariant`，概念事实和文章只补充背景，不能覆盖当前配方用量。明确的来源限制会跳过不请求的检索分支；检索故障保持可见，生成答案不自动写成新知识。首批文章见[来源说明](DATA_SOURCES.md#按菜品关联的文章)。

同名做法的澄清包含真实来源、耗时概要和唯一 ID，响应 `metadata.choices` 保留候选。HTTP 与终端历史保留该信息，可用“第 2 份”继续原查询，也可直接指定完整 ID。所选属性未记载时明确报告缺失，不改答其他属性。

HTTP 会话与消息存储在 MySQL；清空会话后不再继承旧上下文。聊天响应保留 `message`、`session_id`、`message_id`、`route`、`route_logic`、`sources`、`metadata` 和时间。SSE 接口为 `/api/v1/chat/stream`，流式文本来自模型输出生成器。

陶陶网页通过 `POST /api/v1/chat/ag-ui` 接收 AG-UI 事件。`STEP_STARTED` 和 `STEP_FINISHED` 对应实际执行阶段，`TEXT_MESSAGE_CONTENT` 传送回答片段。回答落库后，`RUN_FINISHED.result` 携带完整回答、会话 ID 和来源。食谱版本与附件由 `forwardedProps` 传递，会话历史以服务端记录为准。

上传返回的资产可用于本轮附件阅读，也可显式提交知识入库。文件路径必须来自受管上传资产。支持文本、Markdown、JSON、CSV、PDF 和 DOCX；扫描 PDF 需要先 OCR，旧二进制 Office 格式不会被静默转成空文本。

## 旧数据边界

当前主链移除了 LightRAG 和独立 Text2SQL/旧 KB 路由。旧 `/lightrag/*` 接口、`question/mode/top_k` 本体查询与 JSON 领域配置不再是当前契约。MySQL 只承担应用持久化；不会因问题包含“统计”进入模型生成 SQL 的子图。

历史文件与卷保持原样，不在启动阶段复制旧索引或自动导入。应从可核验的原始资料显式导入，并核对来源、做法版本和查询结果。操作步骤见 [部署](DEPLOYMENT.md)。
