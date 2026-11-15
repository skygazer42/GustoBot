# 最小 RAG 核心与可选图检索方案

更新说明：用户随后明确希望保留现有图分支与 LightRAG 回答职责。因此本文“普通 RAG 默认、LightRAG 默认关闭”仅作为备选方案，不是当前实施前提。最新的合并边界、现有能力与本体约束缺口见 [现有图分支合并与轻量本体约束](2026-11-15-ontology-guided-knowledge-service.md)。

日期：2026-11-15。状态：供审阅的后续实施方案；本轮只完成方案文档，未实施以下架构变化、数据迁移或索引重建。LangChain 1.x 迁移及其兼容修复单独验证，不把依赖升级视为本方案已经落地。

建议保留一个普通 RAG 主流程：问题分类 → 检索证据 → 按证据生成一次最终回答。已有 Neo4j 用于需要结构化关系与精确条件的查询；LightRAG 作为显式启用的文档图检索补充。继续使用现有 LangChain、LangGraph 和存储代码，不增加新的 RAG 框架、ProviderFactory、后端注册表或通用适配层。

## 1. 现状与必须一起处理的边界

| 现有位置 | 已核实行为 | 对最小化方案的影响 |
| --- | --- | --- |
| `gustobot/application/agents/lg_prompts.py`、`lg_builder.py::_heuristic_router` | 做法、步骤、食材问题被分到 `graphrag-query`；历史文化进入 `kb-query` | 默认普通 RAG 必须修改提示和启发式规则，不能只加 LightRAG 开关 |
| `lg_builder.py::route_query`、`create_research_plan` | `graphrag-query`、`text2sql-query` 都进入多工具流程 | 关闭 LightRAG 不能连带关闭 Neo4j Cypher 和 SQL |
| `.../workflows/multi_agent/multi_tool.py::create_kb_multi_tool_workflow` | 默认 scope 只允许历史文化，明确排除烹饪步骤；拒绝和未命中文案也限于文化 | 需要同步扩大真实知识库范围并调整文案，否则新路由仍会拒绝做法问题 |
| `.../components/tool_selection/node.py` | 描述词快路径直接进入 `customer_tools`；其他未逐一识别的工具也进入该节点 | 两条路径都必须改成明确、受可用性约束的工具分支 |
| `.../components/customer_tools/node.py` | `LightRAGAPI` 自行维护模型、embedding、初始化、入库、查询与关闭；节点每次请求创建并关闭实例 | 与公共 `LightRAGService` 重复，且请求级资源所有权不适合共享服务 |
| `gustobot/application/services/lightrag_service.py` | HTTP 使用另一套 LightRAG 封装；模块顶层导入第三方包；初始化只有布尔判断 | 可选安装需要延迟导入，并补足并发首次初始化的生命周期 |
| `KnowledgeService.__init__` 与 KB `local_search` | `KnowledgeService` 默认构造 Milvus 连接；KB 工作流还可访问 PostgreSQL | 移除 LightRAG 核心依赖不等于普通检索已经不需要 Milvus，也不等于数据库已经统一 |

当前图流程中的 `summarize` 是确定性格式化，`final_answer` 直接取 `summary`，并未再次调用 LLM。现有 LightRAG `aquery` 本身会生成答案。后续改成证据检索时，必须接入真正的统一回答步骤，不能把原始检索上下文当成最终答案直接展示。

## 2. 目标路由与产品行为

首阶段保留现有对外路由类型，减少客户端和历史记录的变更；`graphrag-query` 暂时仍是结构化关系/可选图检索入口，不把这个旧名称等同于 LightRAG。

| 用户问题或入口 | 默认处理 | LightRAG 启用后的处理 |
| --- | --- | --- |
| 问候、无需内部事实的轻量对话 | `general-query` | 相同 |
| 缺少菜名、关键条件等必要信息 | `additional-query` | 相同 |
| “红烧肉怎么做”“宫保鸡丁需要哪些食材”“川菜的历史” | `kb-query` → 普通向量检索 → 统一回答 | 仍默认普通 RAG；开启图能力本身不改变这类问题的默认路径 |
| “筛选同时使用鸡肉和花生的菜”“精确查询某菜某食材的用量” | `graphrag-query` → 已有预定义 Cypher / Text2Cypher → 结构化证据 | 相同；Neo4j 不依赖 LightRAG 开关 |
| “数据库有多少道菜”“各菜系数量排名” | `text2sql-query` → SQL → 结构化结果 | 相同；不交给向量相似度或 LightRAG估算 |
| 明确要求综合文档中的实体联系、跨文档图关系 | 未启用时只公开普通文档检索及已有 Neo4j 工具；明确要求不可用的 LightRAG 能力时说明不可用 | 可进入 `graphrag-query` 并选择 LightRAG 文档证据检索；关系数据库事实仍由 Cypher / SQL 负责 |
| 图片、文件入口 | 保留 `image-query`、`file-query` 及附件优先级 | 相同 |

部署设置 `LIGHTRAG_ENABLED=False` 为默认值。显式启用指安装 extra 并在部署配置中设为 `True`；直接调用 `/lightrag/...` 也是明确选择该能力。暂不增加聊天请求字段或全套每请求后端选择协议。

落地时同时修改以下四处，作为同一批可回退变更：

1. 顶层路由提示与 `_heuristic_router`：普通做法、步骤、一般食材介绍进入 `kb-query`；精确结构化筛选/关联仍可进入 Cypher；统计仍优先 SQL。不能继续用“出现食材二字就图查询”的规则。
2. KB scope、guardrails 提示、拒绝和未命中文案：允许已入库的做法、步骤、食材及文化资料。保留原有权限、内容范围和来源约束，不把范围扩大解释成允许无依据的医疗结论。
3. 多工具装配：禁用时不公开 `MicrosoftGraphRagQuery` schema，不构造或挂载 LightRAG 查询节点；Cypher、预定义 Cypher、SQL 继续可用。同步限制 `Command` 目标和图边，避免禁用后仍能向不存在节点发送任务。
4. 工具选择：删除描述词强制 LightRAG 快路径；只将明确的图检索工具名送到该节点。未知工具保留可见错误，不默认路由到 LightRAG，不因缺包异常静默改为普通检索成功。

保留已发布工具名 `microsoft_graphrag_query` 的兼容窗口，同时将工具说明改成实际的 LightRAG 文档证据能力，避免仍向模型宣称使用 Microsoft GraphRAG。旧别名只有查明真实调用方并迁移后才移除。

## 3. 一个证据汇总与最终回答步骤

沿用已有检索结果、`sources`、查询错误和消息契约，不建立新的多实现框架。普通检索提供文档片段；Neo4j / SQL 提供有界记录；LightRAG 提供实体、关系和原文片段。它们在现有工作流中汇总后，只调用一次最终回答模型。这里的“一次”指回答生成；路由、查询生成、图关键词提取仍可能使用模型。

后续实施时，将当前 KB `finalize` 中真实共用的证据整理、来源处理和回答调用提取为一个直接函数，放在现有回答职责模块；KB、图流程复用它。只提取已有两个调用方需要的逻辑，不新建包、服务类或接口体系。保留必要的确定性 SQL 数值/表格格式化。

内部证据继续采用项目已有的结果结构，必需内容直接按约定读取；来源至少保留已知的文档/片段标识、标题或来源地址、检索来源。关系记录需包含实体标识、关系类型及可追溯的记录/文档引用。不存在的来源不捏造，物理工作目录不伪造成用户可打开的引用。

本轮锁定的 `lightrag-hku==1.4.9.8` 已有 `aquery_data()`，无需升级才能只检索证据。独立 Python 3.10 环境已核对包版本和源码：返回包含 `status`、`data`、`metadata`；`data` 中包含 `entities`、`relationships`、`chunks`、`references`。`QueryParam` 也已有 `only_need_context`，但结构化数据入口更方便保留来源，无需自行解析上下文字符串。

建议在唯一的 `LightRAGService` 增加一个确有用途的 `retrieve()` 方法，固定调用此版本的 `aquery_data()`，在服务边界校验并转换结果。Agent 只调用 `retrieve()`；原有 HTTP 查询继续调用 `query()`，保留已发布的答案语义。两个方法共享同一运行时、模型和存储生命周期，不能各维护一套实例。

LightRAG 返回 `metadata.failure_reason == "no_results"` 时可作为正常未命中；初始化失败、格式不正确、其他失败或抛出的异常继续作为错误。不能把所有 `status="failure"` 都转换成空证据。图检索无结果与图服务不可用需在工作流结果中区分；若允许普通检索证据继续回答，必须保留降级状态和来源，不声称已经完成图检索。

LightRAG 的图模式即使不生成最终答案，仍可能调用 LLM 提取关键词。`naive` 只改变查询方式，不跳过普通入库阶段的实体关系抽取。设置检索上下文上限时使用真实查询 token 参数；现有 `LIGHTRAG_MAX_TOKEN_SIZE` 传给 embedding 的 `max_token_size`，不是整次问答的 token 总预算。

## 4. 依赖与模块减法

| 文件 | 后续最小改动 |
| --- | --- |
| `requirements.txt`、`pyproject.toml` | 从核心依赖移除 `lightrag-hku`，新增 `lightrag = ["lightrag-hku==1.4.9.8"]` extra；本阶段不顺带升级 LightRAG |
| `gustobot/config/settings.py` | 新增默认关闭的 `LIGHTRAG_ENABLED`；构建默认关闭与 Docker ARG 对齐。已有 Neo4j/Milvus 的 LightRAG配置先核实实际引用，不能靠改名字声称更换了存储 |
| `gustobot/application/services/lightrag_service.py` | 保留唯一第三方封装；vendor 导入延迟到启用后的初始化/调用。请求响应模型和 `SearchMode` 保留在原文件，不为延迟导入拆出多层转发模块；类型注解使用 `TYPE_CHECKING` 或延迟求值，避免移除顶层导入后产生 `NameError` |
| `.../components/customer_tools/node.py` | 删除重复的完整 `LightRAGAPI` 实现；节点直接调用公共服务 `retrieve()`。保留工作流要求的输出字段和错误信息，按需将证据纳入现有状态，禁止请求结束关闭公共服务 |
| `.../components/customer_tools/__init__.py`、真实调用方 | 同步整理公开导出；不凭别名存在就长期保留第二套实现 |
| `lg_builder.py`、`lg_prompts.py`、`.../kg_tools_list.py`、`.../tool_selection/node.py`、`.../workflows/multi_agent/multi_tool.py` | 按路由表一次调整提示、scope、工具装配、选择和证据汇总；保留 SQL/Cypher 可达性 |
| `.../components/summarize/node.py`、`.../components/final_answer/node.py`、必要的现有回答模块 | 图查询输出先保留证据，再复用统一回答函数；不把 LightRAG 最终答案重新当数据库事实输入模型 |
| `gustobot/interfaces/http/lightrag_router.py` | 保留路径、成功模型和 SSE 协议；增加明确的不可用异常到 503 的转换 |
| `gustobot/main.py`、`gustobot/interfaces/http/__init__.py` | 保持路由注册和应用退出清理；模块轻量化后无需动态注销路由。未使用服务的 shutdown 不构造服务，也不触发第三方导入 |
| `scripts/init_lightrag.py`、`scripts/test_lightrag_service.py`、`tests/test_lightrag_node.py` 等直接调用方 | 同步使用唯一服务契约。原 `insert_documents` 返回字典与公共服务 Pydantic 返回值不同，需显式改调用方；CLI 自有实例自有关闭，不借用并关闭 Web singleton |
| `Dockerfile`、实际安装入口与文档 | 默认构建不装 extra、不建图；只有明确选择图功能的构建安装 extra 并初始化。记录核心安装与图安装两种经过验证的命令 |

模型、请求、响应可保留在现有文件；服务负责第三方依赖与资源，Agent 节点负责状态转换，HTTP 路由负责状态码和流协议。这些是实际边界，不以文件少为由合成大 `utils.py`，也不为目录对称添加新模块。

## 5. 并发初始化与关闭

公共服务按应用进程共享，初始化增加一个真实的异步生命周期锁。进入锁前可检查已完成状态，进入锁后再次检查；只在存储与 pipeline 都初始化成功后标记完成。两个并发首次请求仅构造、初始化一次运行时，不把整个查询串行化。

部分初始化失败时，持有资源的一层关闭已经取得的存储，清空运行时和完成标记，再传播原异常；取消保留取消语义。锁内失败清理不能调用会再次获取同一把非重入锁的公共 `cleanup()`，避免死锁。后续请求应可重试初始化，而非复用半初始化对象。

单次 Agent 请求和 SSE 连接只拥有本次调用及生成器，退出时只关闭本次生成器。应用 shutdown 在请求排空后关闭 singleton 存储一次。初始化锁不解决多进程共同写同一 NetworkX/JSON 目录的问题；若沿用文件后端，部署限制为同一索引单进程所有者。多 worker 共享写入或更换存储另行设计，不能声称进程内锁已覆盖。

## 6. 保留的 HTTP 契约

实际前缀为 `settings.API_V1_PREFIX + /lightrag`，通常是 `/api/v1/lightrag`。

| 路径 | 成功行为 | 禁用或缺少可选包 |
| --- | --- | --- |
| `POST /query` | 保留 `LightRAGQueryResponse` 的 `query/response/mode/metadata` 与答案语义 | 503 |
| `POST /query-stream` | 保留 `data: <文字>`、`[ERROR]` 和 `[DONE]` 的现有 SSE 成功/运行期错误协议 | 创建 `StreamingResponse` 之前返回普通 HTTP 503 |
| `POST /insert` | 保留 `total/success/failed/errors`，部分成功计数不能改成全部成功 | 503；不修改已有索引 |
| `GET /stats` | 继续返回现有文件统计模型；仅检查文件，不 import vendor、不初始化或写入索引 | 保留 200 文件统计，`initialized` 反映真实状态；不伪装为查询服务健康 |
| `POST /test-modes` | 保留各模式的成功/失败结果模型 | 在进入逐模式循环前统一返回503，不能包装成200下的所有模式失败 |

将“禁用”和“缺少 extra”转换为明确的服务不可用异常；HTTP 在宽泛的运行错误捕获之前单独转换为503。参数错误仍按当前400/422契约，正常查询运行失败仍是失败。缺可选顶层包与包内部依赖损坏需区分，不能捕获所有 `ImportError` 就宣称用户未安装。

当前 SSE 路由已在返回 `StreamingResponse` 前 `await service.query(stream=True)`；保留这个顺序，把可用性校验及初始化放在同一前置阶段即可。开始发送后发生的错误只能按既有 SSE 错误帧表达，不能再改 HTTP 状态。断开和取消时关闭本次生成器，不继续输出错误或完成帧，也不关闭共享索引。

## 7. Neo4j 与轻量关系表的边界

本阶段保留已有 Neo4j 及其数据、Cypher 模板和入口。LightRAG 当前两套封装实际使用 NetworkX/JSON 与默认向量存储；“去掉 LightRAG”与“去掉 Neo4j”是两件独立工作，不能根据配置字段名称推断已经共用图存储。

如果之后确认只需要固定一跳/少量关系与筛选，可评估现有关系库中的关系表，例如“菜谱—食材—用量”和“菜谱—有序步骤”，通过普通 SQL 读取。只有确定新需求时才设计具体表与索引，不预建另一套图框架。

从 Neo4j 改到关系表属于数据迁移：要保留实体稳定 ID、关系方向与类型、重复关系、用量单位、步骤顺序及来源，验证节点/边数量、属性和值、原查询结果，并安排切换和回退。在这些对账完成前，不删除 Neo4j 数据或连接，不以导出 CSV 等同于完整迁移。LightRAG 的文档抽取图也不能未经校验替代结构化菜谱事实。

## 8. 分阶段实施与验收

每阶段先补可观察行为回归，再做小范围修改；不要用仅检查源码字符串或“必须有某个类”的测试替代行为验证。

1. **完成当前 LangChain 1.x 迁移。** 核对 Python3.10依赖解析、StateGraph输入/输出、14处结构化输出的兼容方式；修复真实Router对象和消息内容块进入聊天API、恢复流工具增量的边界。此阶段不改变默认业务路由或图架构。
2. **建立可选依赖与唯一生命周期。** 先补缺包导入、并发初始化、失败清理和HTTP不可用行为测试，再延迟导入、移extra、合并封装、迁移真实调用方。不要让中间提交依赖已删除的类。
3. **普通RAG成为默认路径并统一回答。** 先核实普通知识库已有做法、食材等对应文本和来源；路由变更不能凭空补齐资料。若缺少语料，先单独安排已有菜谱文档的增量导入和验收，再切换默认路径。按路由表同时修改提示、启发式、KB范围、工具装配；LightRAG Agent调用改为证据检索，汇总后生成一次最终回答。旧HTTP接口维持答案语义。
4. **对比质量与成本。** 使用脱敏、固定的离线案例比较普通RAG、Neo4j补充和启用LightRAG后的来源、正确性、检索量、实际模型调用与token消耗。只有存在测量结果才能宣称更快、更省或答案更好。
5. **单独评估存储收敛。** 若普通核心也要去掉Milvus，需先处理 `KnowledgeService` 构造期连接与已有pgvector路径，再确定数据导入和回退。若增加PostgreSQL文本混合检索，必须用实际中文菜名、食材别称和长文本案例验证分词、召回与排序；不能宣称原生FTS开箱即等价中文BM25，也不在本轮未经授权安装分词扩展。若要换Neo4j，同样单列迁移，不合并进依赖升级。

必要验收案例：

- 新进程阻断 `lightrag` 导入时，核心Agent和FastAPI路由可加载；默认聊天不导入、不初始化LightRAG，不改动图数据目录。测试替换外部边界，不读取真实`.env`或调用模型。
- 开关默认关闭；未装extra但开关开启时，普通RAG仍可工作，明确的LightRAG HTTP请求返回503；`/query-stream` 状态不能先变200；`/stats` 不初始化或写数据。
- Agent与HTTP使用同一服务；两个并发首次请求只初始化一次；存储初始化或pipeline失败后清理一次，恢复后可重试；取消不吞掉，清理失败不覆盖原错误。
- SSE正常完成、运行中出错、主动关闭、断开和取消均释放本次生成器；单次请求不finalize共享存储；应用退出只finalize一次，未使用服务退出无副作用。
- 普通做法、食材介绍、历史文化进入KB且不被文化专用scope拒绝；精确关系筛选进入Neo4j；计数排名进入SQL；关闭LightRAG后这两类结构化能力继续可达。
- 禁用时图工具schema、描述词快路径和目标节点均不能被选到；启用后明确的文档图关系任务可达；未知工具返回可见错误。
- LightRAG Agent路径只调用 `aquery_data`，不调用 `aquery` 再二次生成；最终回答生成计数为一次。无结果、损坏结果和检索失败分开，返回证据的引用在合并后仍对应原文/记录。
- 既有HTTP五条路径、响应字段、SSE帧及入库部分成功行为有兼容回归；旧CLI使用新服务后计数、退出状态和资源关闭正确。
- Python3.10与项目主开发版本都执行相关检查。取消异常的原消息/对象断言在被测协程内部验证，避免把不同CPython版本越过 `asyncio.run` 后的表现误当业务回归。

本方案不执行数据库迁移、不删除索引、不重建LightRAG图、不切换向量库，也不以文档中的建议宣称代码已经完成可选化。后续实现应分别交付核心无LightRAG安装验证、启用图功能的兼容验证，以及真实存储/模型验证尚未覆盖的项目。
