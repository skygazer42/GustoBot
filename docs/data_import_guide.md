> 当前导入接口以 [领域知识服务](DOMAIN_KNOWLEDGE.md) 为准；部署步骤见 [快速启动](QUICK_START.md)。

# JSON 菜谱批量导入指南

菜谱事实的基本单位是一份具体来源做法及其内容版本。使用 `scripts/import_recipes.py` 将 `data/recipe.json` 或同格式的 JSON 文件通过 HTTP 映射入 Neo4j；这条链路不向量化，也不调用 LLM。

脚本通过 **HTTP API** 写入知识库，因此实际导入前请先确保后端已启动并可访问。`--dry-run` 只转换并预览，不写入知识库。

---

## 前置条件

- 启动服务（推荐 Docker Compose）：

```bash
docker compose up -d
```

- 确认 API 可访问：

```bash
curl -s http://localhost:8000/docs >/dev/null && echo "OK"
```

如使用了非默认端口/域名，请在命令中通过 `--api-base-url` 指定。

---

## 从 JSON 文件批量导入

项目内置的 `data/recipe.json` 是一个 **以菜名为 key 的 dict**，每条数据字段大致为：
`主食材 / 辅料 / 耗时 / 口味 / 工艺 / 做法 / 类型`。

导入脚本保留完整原始记录，以 `{name, record}` 提交 `/api/v1/knowledge/recipes/batch`。后端按 `gustobot/config/mappings/recipes.yaml` 映射，再用 `domains/recipes.yaml` 校验，逐项返回作业回执。

### 1) 仅转换预览（不写入 KB）

```bash
python scripts/import_recipes.py --file data/recipe.json --batch-size 100 --dry-run
```

### 2) 写入 KB（可先小批量验证）

```bash
python scripts/import_recipes.py --file data/recipe.json --batch-size 100 --limit 200
```

### 3) 全量写入（耗时较长）

```bash
python scripts/import_recipes.py --file data/recipe.json --batch-size 100
```

如后端不在 `http://localhost:8000`，可指定后端地址：

```bash
python scripts/import_recipes.py \
  --file data/recipe.json \
  --batch-size 100 \
  --api-base-url "http://localhost:8000"
```

---

## 常见问题

- **报错：无法连接到 `http://localhost:8000`**
  - 确认 `docker-compose up -d` 已启动
  - 或通过 `--api-base-url` 指向正确地址

- **后端返回 5xx / 写入失败**
  - 批量写入会校验本体并写入事实图。错误响应含已完成项和失败作业信息，可通过 `/api/v1/knowledge/jobs/{job_id}` 核对；查看日志：`docker compose logs -f backend`。

原文向量入库使用 `python scripts/import_knowledge.py documents --path <文件>`。直接导入本地菜谱也可使用 `python scripts/import_knowledge.py recipes --path data/recipe.json --limit 10`。

