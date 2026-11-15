# 图检索统一至 LightRAG

用户要求合并 graph 与 LightRAG，停止维护 Cypher 查询，继续保持任意领域可用。用户已授权实现；不操作实际数据库或 data 索引，不提交/推送，也不覆盖此前未提交修改。

## 删除与保留

- 删除独立 Neo4j 事实存储、有界图遍历、Text2Cypher、固定菜谱 Cypher 和专属 Neo4j 问答入口。
- 保留领域实体/关系/属性/原文引证校验，以及可选的模型结构化抽取。已校验事实序列化为完整来源文档，交给现有 LightRAG 入库流程；不再维护第二套图。
- 不采用 LightRAG 1.4.9.8 的 ainsert_custom_kg：源码显示其直接 upsert 同名节点/同端点边，可能覆盖普通文档图的描述和来源。复用普通 ainsert 的抽取与合并，接受已抽取事实再次抽取的成本。
- 文档问答与图关系问答复用同一服务/索引，仅检索模式不同。默认菜谱配置也启用此链路，不再装配菜谱图工具。
- 统计 SQL 不等同 Cypher，保留独立流程；将真实 SQL 实现从旧 graph 目录迁至 text2sql，使其 schema 获取使用 SQL 数据库自身元数据，消除依赖 Neo4j 的特殊装配。
- 保留有现存调用的旧文档 KB，迁出其被旧 graph 模块包含的公共实现。本轮不做向量数据迁移，不宣称全部安装依赖均已最小化。

## 实施分工

1. 服务/API：LightRAG 源文档与事实入库、简化 OntologyService 和 HTTP，自有 ontology_store 删除；对应服务和 API 行为回归。
2. Agent：聊天图分支统一 LightRAG；SQL 归位/元数据读取；迁出保留 KB；删除旧 Cypher/图问答装配及其专属测试，保留无关 SQL/资源行为覆盖。
3. 主集成：配置默认值、Neo4j 入口清理、默认部署解除对图数据库的依赖、脚本/文档与新流程图；收集所有检查结果并修复整合问题。

## 契约与验证

- 修改前离线基线：534 passed、2 skipped。验证环境为 .omx/state/langchain-v1/venv310，测试通过 run_offline_tests.py 屏蔽真实 .env。
- /ontology/extract 和 /validate 保留。/facts 表示“校验后导入同一知识索引”，不再承诺 Neo4j 事务与事实 ID 不变性；失败和取消保持可见。
- /ontology/query 改为 question/mode/top_k 的自然语言检索；旧 anchor_ids/relation_types/max_hops/limit 不可悄悄忽略，必须校验拒绝。不再返回精确有向路径或强类型事实子图。
- LightRAG 的检索图不是强约束本体数据库；类型/证据保证在输入校验边界，不能虚称检索后仍满足方向、关系唯一性或属性约束。
- 新回归覆盖各领域均进入同一图服务、原文/URI 不丢失、非法事实在调用模型/索引前拒绝、导入失败/取消、旧路径查询参数拒绝、SQL 不连接 Neo4j、默认部署不强制图数据库。
- 跑完整离线测试、Black、Flake8、Ruff F/E9、Mypy、差异检查；用实际实现更新流程图。真实模型与数据库联测、旧图数据迁移明确列为未覆盖范围。


## 完成与验证（2026-11-15）

已完成三条实施切片，并由原两个子智能体交叉复核。发现并修复了 vendor completion 异步流返回类型、图查询无 raw_data 的固定无结果返回，以及 SQL 未启用时模型仍选择 SQL 的执行边界。上传文件名通过 file_paths 进入共享索引。

关键改动文件：

- `gustobot/application/services/lightrag_service.py`：共享 runtime、一次结构化回答及检索上下文、真实文档处理状态与来源、流式完成边界。
- `gustobot/application/services/ontology_service.py`、`gustobot/interfaces/http/ontology_router.py`：保留本体输入校验，统一文档入库与自然语言检索，拒绝退休的图路径参数。
- `gustobot/application/agents/lg_builder.py`、`agents/text2sql/`、`agents/kb_tools/workflow.py`：统一图检索，SQL/旧 KB 从退休目录迁出，数据库自身元数据与双开关。
- `gustobot/domain/knowledge.py`、`gustobot/config/domains/`、`gustobot/config/settings.py`：删除专属图工具装配与 Neo4j 配置，领域默认共用 LightRAG，SQL 连接不进入领域定义。
- `gustobot/main.py`、`gustobot/interfaces/http/knowledge_router.py`：移除第二套图生命周期与图 HTTP 问答入口。
- 删除 `gustobot/application/agents/kg_sub_graph/` 的源代码、自有 ontology_store，以及 recipe_kg 中在线图查询/图导入/意图词典实现；保留离线 CSV 导出。
- `docker-compose.yml`、`Dockerfile`、示例环境与启动脚本：默认 backend + SQLite + 本地索引；旧组件改 profiles，无 Neo4j service。
- `requirements.txt`、`pyproject.toml`：删除 Neo4j 专属依赖、退休 Streamlit extra 及无现存引用的 Matplotlib/Seaborn/pyahocorasick/scikit-learn 直接依赖；保留 Pillow、pandas 等实际业务依赖。
- `README.md`、`docs/DOMAIN_KNOWLEDGE.md`、快速启动、数据血缘、SQL 文档与前端架构说明同步。历史部署文档标注版本边界。
- 同时按既有全仓 Python 规范要求用 Black 统一此前 37 个文件的格式，没有因此改变业务逻辑；清除 hashing.py 的已有行尾空白。

最终验证：

| 检查 | 结果 |
| --- | --- |
| 离线完整回归 | 484 passed、2 skipped、23 warnings；真实 .env 读取被 wrapper 屏蔽 |
| Black | 178 个 Python 文件通过 |
| Flake8 | 全部 Python 源码与测试通过 |
| Ruff F/E9 | 全部 Python 源码与测试通过 |
| Mypy | 178 source files，无错误 |
| 前端 npm run build | Vue/TypeScript 类型检查与 Vite 构建通过；既有 Sass API 弃用提示 |
| Bash -n | backend_entrypoint.sh、docker_entrypoint.sh、start-dev.sh 通过 |
| 静态导入扫描 | 141 个生产/脚本 Python 文件无退休图模块或 Neo4j import |
| Compose YAML/profile/dependency | 默认仅 backend，所有可选服务依赖有效；未运行服务或读取真实 .env |
| git diff --check | 通过 |

额外运行 Bandit：0 个高等级、7 个中等级提示，未宣称全绿。4 项是服务/开发启动绑定 0.0.0.0；3 项在保留旧 KB 的 SQL 字符串构造中，已核对表名采用标识符白名单、筛选值采用绑定参数、动态表达式由固定分支选择。本轮不为消除提示添加 nosec 或改动这些业务策略。完整测试的警告来自既有兼容导入、PyMilvus/environs 和 FastAPI on_event 弃用。

未验证真实模型/数据库、容器构建与运行、生产性能、多进程写入或旧图数据迁移。标准文档入库会对已校验事实再次抽取，有模型成本且非事务；输入校验不能保证 LightRAG 合并后的检索图仍满足强类型/方向约束。不提供按事实 ID 更新或精确路径保证。Python 安装依赖仍含保留的旧 KB/SQL 能力，本轮不声称完整依赖集已经最小化。

本轮未提交、推送、执行数据迁移或删除实际 data/与卷。
