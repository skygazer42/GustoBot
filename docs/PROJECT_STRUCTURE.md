# 项目代码导航

先读 `gustobot/main.py` 的路由装配，再按要修改的能力进入对应模块。知识入库统一由主应用负责，运行数据不参与源码整理。

## 主应用

```text
gustobot/
├── main.py                         FastAPI 装配、启动检查与资源关闭
├── application/
│   ├── messages.py                 共享的模型消息正文读取
│   ├── agents/
│   │   ├── workflow.py             LangGraph 工作流与专属状态
│   │   └── main.py                 交互式终端
│   └── services/
│       ├── knowledge_query.py      统一问答：规划、绑定、检索、求值、展示
│       ├── entity_linking.py       概念／实体候选、权威回读与消歧
│       ├── semantic_indexing.py    候选代次构建、校验、发布与校准
│       ├── knowledge_ingestion.py  来源入库任务与发布状态
│       ├── ontology_service.py     文档事实抽取与正式校验入口
│       ├── knowledge_runtime.py    应用拥有的客户端装配与关闭
│       └── multimodal.py           图片阅读和生成
├── domain/
│   ├── knowledge.py               领域、事实、来源与证据契约
│   ├── formal_ontology.py         正式本体加载与业务属性编译
│   ├── linking.py                 候选身份、范围、索引代次契约
│   └── numeric.py                 精确数值、量纲与比较粒度
├── config/
│   ├── settings.py                环境配置
│   ├── domain.py                  当前领域选择与加载
│   ├── domains/                   领域资源清单
│   ├── mappings/                  结构化来源字段映射
│   └── ontologies/                OWL/RDFS、SHACL 与本地标准子集
├── infrastructure/
│   ├── core/                     数据库会话、资源、安全与日志
│   ├── knowledge/                Neo4j／Milvus／embedding 等适配器
│   │   ├── graph_store.py         事实存储和受控查询编译
│   │   ├── semantic_runtime.py    正式推导、SHACL 与数量求值
│   │   ├── recipe_facts.py        来源菜谱到事实图的确定映射
│   │   └── recipe_catalog.py      CSV 导出工具使用的离线目录解析
│   └── persistence/
│       ├── db/models/chat.py      会话、消息与会话快照 ORM
│       ├── crud/chat.py           对应聊天数据操作
│       └── .../knowledge.py       来源、任务及资产持久化
└── interfaces/http/
    ├── v1/chat.py                 聊天、流式回答与历史
    ├── v1/sessions.py             会话资源接口
    ├── v1/upload.py               受管上传
    ├── models/session.py          会话／消息请求与响应契约
    ├── knowledge_router.py        显式知识入库与查询
    └── ontology_router.py         抽取、校验和事实接口
```

问答主线在 `KnowledgeQueryService._prepare` 中按阶段顺序排列。查询编译与数据库 I/O、正式语义求值仍分开，保留各自的数据和资源边界；不能只因文件较长把它们混进通用 `utils.py`。

聊天 ORM 位于 `infrastructure/persistence/db/models`，HTTP 数据契约位于 `interfaces/http`；代码直接从实际定义模块导入。没有调用方的旧 `domain/models` 聚合入口和旧聊天 schema 已删除。

## 统一入库

`application/services/knowledge_ingestion.py` 负责来源解析、入库任务和发布状态；文档切块及向量写入由 `infrastructure/knowledge/knowledge_service.py` 完成，菜谱结构化记录通过 `recipe_facts.py` 映射、校验并写入 Neo4j。对外接口在 `interfaces/http/knowledge_router.py`。

旧独立 Excel／MySQL→pgvector 服务已退役。原始历史样例保留在 `data/kb/`，不再维护另一套服务入口、配置和向量检索。当前文档格式支持以统一解析入口为准，未把旧表格服务自动迁入新主链。

删除范围、资料保留和回归结果见 [旧服务退役记录](evaluation/KB_INGEST_RETIREMENT_2026-11-17.md)。

## 资料、历史文档和生成物

| 位置 | 当前用途 |
| --- | --- |
| `data/recipe.json`、`data/excipients.json`、`data/kb/` | 保留的原始菜谱、食材和原文资料 |
| `data/reference/legacy_mysql/` | 旧 SQL 样例的资料归档，不参与初始化和迁移 |
| `docs/archive/legacy/` | 已退役的 LightRAG、Text2SQL、pgvector 和旧启动指南 |
| `.venv/`、`*.egg-info/`、工具缓存 | 当前本地开发环境或可再生元数据，已按各自用途忽略 |

旧 LightRAG 索引、旧示例图、tokenizer 缓存、导入哨兵、pgvector 初始化、旧 APOC 插件和带废弃模块的 `build/` 副本已清理。旧交互式 `start-dev.sh/.bat` 已移除；使用快速启动文档或当前 `run.py`／`Makefile` 入口。

## 命令、测试和数据

| 位置 | 维护内容 |
| --- | --- |
| `scripts/import_knowledge.py` | 当前主应用的文档／菜谱导入 |
| `scripts/build_semantic_index.py` | 候选构建、状态、worker、校准与退役 |
| `scripts/rebuild_numeric_projection.py` | 明确范围的数值投影重建 |
| `scripts/evaluate_knowledge.py` | 冻结问题、提供方与准入工件评测 |
| `scripts/verify_knowledge_snapshot.py` | 快照文件和范围一致性核验 |
| `scripts/run_backend_tests.py` | 禁用开发者 dotenv 的测试入口 |
| `scripts/recipe_kg_to_csv.py` | 独立的菜谱目录 CSV 导出工具 |
| `migrations/` | 只追加的应用数据库迁移 |
| `tests/` | 按被测能力命名的行为与集成测试；共享 fixture 使用 `tests.test_*` 明确导入 |
| `eval/` | 冻结题集、来源快照、待人工核对草稿 |
| `web/` | 前端页面与交互，Python 整理仅同步必要的 API 引用 |
| `data/`、`uploads/` | 来源及运行数据，不能当无用代码清理 |

增加模块前先检查现有职责是否能承接。同一能力的契约和专属校验应放在一起；有独立连接、可选依赖或安全边界的适配器继续单独维护。公开 HTTP 字段、模型版本与已存数据的变化需要独立业务决定，不能作为命名整理顺手修改。

逐文件、逐函数和逐类的规约核查范围及验证结果见 [Python 开发规约审查](evaluation/PYTHON_GUIDELINES_AUDIT.md)。

DeepSeek Flash 与 BGE 嵌入／重排的本地配置、协议和真实调用验证见 [模型联调记录](evaluation/MODEL_INTEGRATION_2026-11-17.md)。

当前服务地址、真实接口／浏览器验收、修复内容及复测命令见 [运行验收记录](evaluation/LIVE_ACCEPTANCE.md)。

本机并发分档、P50／P95、模型调用耗时与当前步骤回答瓶颈见 [接口压测记录](evaluation/LOAD_TEST_2026-11-18.md)。

本体如何参与精确计数、用量筛选和单位换算，以及自然语言计划的适用边界，见 [问数验证](evaluation/ONTOLOGY_NUMERIC_VERIFICATION.md)。
