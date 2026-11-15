# 删除未使用的 Wikipedia 导入功能

用户已明确同意删除 `gustobot/crawler`。引用核查确认它只有手动命令入口，现有聊天、在线搜索和 JSON/Excel/文本导入不依赖它。

## 清理计划

1. 删除 crawler 的三个 Python 模块及专属缓存，不添加兼容包装。
2. 删除四个专属测试函数（七个参数化用例），保留 JSON 映射、在线搜索及其他回归覆盖。
3. 移除仅在 requirements.txt 声明、无第一方使用的 beautifulsoup4、lxml、fake-useragent 和 playwright 四个直接依赖。
4. 删除当前文档中的入口；将混合指南改为 JSON 菜谱导入指南，保留有用内容。历史审核记录保留并标明其快照性质。
5. 检查活动引用，执行格式、lint、类型检查、离线测试，以及保留导入脚本的 help 和 dry-run。

## 验证边界

不连接数据库、模型或真实外部服务；不更改现有数据、其他工作区修改和已暂存删除，不提交或推送。依赖清单的删除不代表卸载本机环境中的包，也不保证这些包不被其他依赖间接引入。

## 结果

已完成清理：

- 删除 `gustobot/crawler/__init__.py`、`cli.py`、`wikipedia.py`，清除三个生成的 pyc 文件及空目录。
- 从 `requirements.txt` 移除四个无第一方使用的直接依赖，保留现有 HTTP 客户端依赖。
- 从 `tests/test_recipe_import_mapping.py`、`tests/test_python_guidelines_knowledge_ingestion.py` 和 `tests/test_python_second_look_api.py` 删除四个专属函数（七个用例），并清除仅供它们使用的 Callable 导入。
- 更新 `docs/QUICK_START.md` 和 `docs/DATA_SOURCES.md`；将 `docs/crawler_guide.md` 改为 `docs/data_import_guide.md`，保留 JSON 导入说明。
- 在 `docs/audits/python/2026-11-15-function-review/INDEX.md` 标明旧审核为历史快照，保留其原始记录。`.gitignore` 对旧生成数据目录的忽略保护继续保留。

验证结果：

| 检查 | 实际结果 |
| --- | --- |
| Black 全配置源码范围 | 315 文件通过，无需重排 |
| Flake8 全配置源码范围 | 通过，退出码 0 |
| Ruff F/E9 全配置源码范围 | 通过，退出码 0 |
| Mypy 项目配置范围 | 315 源文件通过 |
| 离线 pytest | 349 passed、2 skipped、41 warnings，退出码 0 |
| JSON 导入 CLI | `--help` 通过；`--limit 1 --dry-run` 输出可解析的 UTF-8 JSON，单条名称与数据源一致，食材/步骤非空 |
| 文件与引用 | crawler 实体目录已不存在，活动源码和文档无已删除功能入口；历史审核与清理计划中的引用保留 |
| 工作区与暂存区 diff whitespace | 使用 `cr-at-eol` 识别已有 CRLF，两项均通过 |

命令与日志：

```text
python -m black --check gustobot kb_ingest scripts tests run.py start_chatbot.py
python -m flake8 gustobot kb_ingest scripts tests run.py start_chatbot.py
python -m ruff check --select F,E9 gustobot kb_ingest scripts tests run.py start_chatbot.py
python -m mypy
python -m pytest --ignore=tests/test_chat_api.py --ignore=tests/test_lightrag_node.py -q --tb=short
python scripts/import_recipes.py --help
python scripts/import_recipes.py --file data/recipe.json --limit 1 --dry-run
```

日志位于 `.omx/state/remove-crawler/`。pytest 沿用此前离线范围，排除上述两个真实服务集成测试文件；本次未连接外部服务。41 条警告及测试进程退出时 ascii_colors 对已关闭 stream 的 flush 报错仍存在，测试退出码为 0。首次 dry-run 的终端编码显示异常，随后通过子进程指定 UTF-8 输出并解析/断言内容，未修改应用代码或本机全局编码。
