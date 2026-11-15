> 历史文档：下文保留旧部署与接口说明。2026-11-15 已将图查询统一至 LightRAG，移除 Cypher/Neo4j 运行链路；当前配置、接口和部署请以 [领域知识服务](DOMAIN_KNOWLEDGE.md) 与 [快速启动](QUICK_START.md) 为准。

# LightRAG 问答检索服务使用指南

## 概述

LightRAG 服务基于 Docker build 时预生成的索引文件提供高效的问答检索功能。

### 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Build 时                           │
│  data/recipe.json → LightRAG.ainsert() → 生成索引文件        │
│                                                              │
│  生成的文件:                                                  │
│  - graph_chunk_entity_relation.graphml  (~15MB)             │
│  - kv_store_doc_status.json             (~100KB)            │
│  - kv_store_full_docs.json              (~25MB)             │
│  - kv_store_text_chunks.json            (~5MB)              │
│  - vdb_chunks.json                      (~2MB)              │
│  - vdb_entities.json                    (~1.5MB)            │
│  - vdb_relationships.json               (~1MB)              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    运行时                                     │
│  LightRAGService → 加载索引文件 → 提供问答检索              │
│                                                              │
│  支持的检索模式:                                              │
│  - naive:   直接语义搜索                                     │
│  - local:   局部图谱检索                                     │
│  - global:  全局图谱检索                                     │
│  - hybrid:  混合检索（推荐）                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 1. Docker 构建（自动生成索引）

```bash
# 确保 .env 配置正确
cp .env.example .env
nano .env  # 填写 OPENAI_API_KEY

# 一键启动（自动构建并初始化 LightRAG）
docker-compose up -d

# 查看构建日志
docker-compose logs -f server
```

### 2. 验证索引文件

```bash
# 检查索引文件是否存在
docker-compose exec server ls -lh /app/data/lightrag/

# 预期输出：
# graph_chunk_entity_relation.graphml  (~15MB)
# kv_store_doc_status.json              (~100KB)
# kv_store_full_docs.json               (~25MB)
# kv_store_text_chunks.json             (~5MB)
# vdb_chunks.json                       (~2MB)
# vdb_entities.json                     (~1.5MB)
# vdb_relationships.json                (~1MB)
```

### 3. 测试查询

```bash
# 方法 1: 使用 API
curl -X POST "http://localhost:8000/api/v1/lightrag/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "红烧肉怎么做？",
    "mode": "hybrid",
    "top_k": 10,
    "stream": false
  }'

# 方法 2: 使用测试脚本
docker-compose exec server python scripts/test_lightrag_service.py
```

---

## API 端点

### 1. 非流式查询

**Endpoint**: `POST /api/v1/lightrag/query`

**请求体**:
```json
{
  "query": "红烧肉怎么做？",
  "mode": "hybrid",
  "top_k": 10,
  "stream": false
}
```

**响应**:
```json
{
  "query": "红烧肉怎么做？",
  "response": "红烧肉的做法如下...",
  "mode": "hybrid",
  "metadata": {
    "top_k": 10,
    "working_dir": "/app/data/lightrag"
  }
}
```

### 2. 流式查询

**Endpoint**: `POST /api/v1/lightrag/query-stream`

**请求体**:
```json
{
  "query": "宫保鸡丁怎么做？",
  "mode": "hybrid",
  "top_k": 10
}
```

**响应**: Server-Sent Events (SSE) 流

```
data: 宫保鸡丁
data: 是一道
data: 经典川菜
...
data: [DONE]
```

**示例代码**:
```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/lightrag/query-stream",
    json={"query": "宫保鸡丁怎么做？", "mode": "hybrid"},
    stream=True
)

for line in response.iter_lines():
    if line:
        print(line.decode('utf-8'))
```

### 3. 增量插入文档

**Endpoint**: `POST /api/v1/lightrag/insert`

**请求体**:
```json
{
  "documents": [
    "红烧肉是一道经典的中华料理，主要原料为五花肉...",
    "宫保鸡丁起源于四川，是一道家喻户晓的传统名菜..."
  ]
}
```

**响应**:
```json
{
  "total": 2,
  "success": 2,
  "failed": 0,
  "errors": []
}
```

### 4. 获取索引统计

**Endpoint**: `GET /api/v1/lightrag/stats`

**响应**:
```json
{
  "working_dir": "/app/data/lightrag",
  "total_size_mb": 48.5,
  "files": {
    "graph_chunk_entity_relation.graphml": {
      "exists": true,
      "size_bytes": 15728640,
      "size_mb": 15.0
    },
    ...
  },
  "initialized": true
}
```

### 5. 测试所有模式

**Endpoint**: `POST /api/v1/lightrag/test-modes?query=红烧肉怎么做？`

**响应**:
```json
{
  "query": "红烧肉怎么做？",
  "results": {
    "naive": {
      "success": true,
      "response": "...",
      "response_length": 1234
    },
    "local": { ... },
    "global": { ... },
    "hybrid": { ... }
  }
}
```

---

## 检索模式对比

| 模式 | 说明 | 适用场景 | 速度 | 准确度 |
|------|------|----------|------|--------|
| **naive** | 直接语义搜索 | 简单关键词查询 | ⚡⚡⚡ | ⭐⭐ |
| **local** | 局部图谱检索 | 关注特定实体和关系 | ⚡⚡ | ⭐⭐⭐ |
| **global** | 全局图谱检索 | 需要综合多个知识点 | ⚡ | ⭐⭐⭐⭐ |
| **hybrid** | 混合检索（推荐） | 平衡速度和准确度 | ⚡⚡ | ⭐⭐⭐⭐ |

**推荐使用 `hybrid` 模式**，它结合了语义搜索和图谱检索的优势。

---

## 使用示例

### Python SDK

```python
import asyncio
from gustobot.application.services.lightrag_service import get_lightrag_service, LightRAGQueryRequest

async def main():
    # 获取服务实例
    service = get_lightrag_service()

    # 初始化
    await service.initialize()

    # 1. 简单查询
    response = await service.query(
        query="红烧肉怎么做？",
        mode="hybrid",
        top_k=10,
        stream=False
    )
    print(response)

    # 2. 结构化查询
    request = LightRAGQueryRequest(
        query="麻婆豆腐怎么做？",
        mode="hybrid",
        top_k=5,
        stream=False
    )
    response = await service.query_structured(request)
    print(f"查询: {response.query}")
    print(f"回答: {response.response}")

    # 3. 流式查询
    stream = await service.query(
        query="宫保鸡丁怎么做？",
        mode="hybrid",
        stream=True
    )
    async for chunk in stream:
        print(chunk, end="", flush=True)

    # 4. 插入新文档
    result = await service.insert_documents([
        "鱼香肉丝是一道经典川菜...",
        "糖醋排骨是一道酸甜口味的菜肴..."
    ])
    print(f"插入成功: {result.success}/{result.total}")

    # 5. 获取统计信息
    stats = service.get_index_stats()
    print(f"索引总大小: {stats['total_size_mb']} MB")

    # 清理
    await service.cleanup()

asyncio.run(main())
```

### cURL 示例

```bash
# 1. 基本查询
curl -X POST "http://localhost:8000/api/v1/lightrag/query" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "红烧肉怎么做？",
    "mode": "hybrid",
    "top_k": 10,
    "stream": false
  }'

# 2. 流式查询
curl -X POST "http://localhost:8000/api/v1/lightrag/query-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "宫保鸡丁怎么做？",
    "mode": "hybrid"
  }'

# 3. 插入文档
curl -X POST "http://localhost:8000/api/v1/lightrag/insert" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      "鱼香肉丝是一道经典川菜...",
      "糖醋排骨是一道酸甜口味的菜肴..."
    ]
  }'

# 4. 获取统计
curl "http://localhost:8000/api/v1/lightrag/stats"

# 5. 测试所有模式
curl -X POST "http://localhost:8000/api/v1/lightrag/test-modes?query=红烧肉怎么做？"
```

### JavaScript / TypeScript

```typescript
// 非流式查询
async function queryLightRAG(query: string) {
  const response = await fetch('http://localhost:8000/api/v1/lightrag/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      mode: 'hybrid',
      top_k: 10,
      stream: false
    })
  });

  const result = await response.json();
  console.log(result.response);
}

// 流式查询
async function queryLightRAGStream(query: string) {
  const response = await fetch('http://localhost:8000/api/v1/lightrag/query-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, mode: 'hybrid' })
  });

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') return;
        console.log(data);
      }
    }
  }
}

// 使用
queryLightRAG('红烧肉怎么做？');
queryLightRAGStream('宫保鸡丁怎么做？');
```

---

## 配置说明

### 环境变量

在 `.env` 文件中配置：

```bash
# LightRAG 工作目录（存放索引文件）
LIGHTRAG_WORKING_DIR=./data/lightrag

# 默认检索模式
LIGHTRAG_RETRIEVAL_MODE=hybrid

# 默认返回结果数量
LIGHTRAG_TOP_K=10

# 文本单元最大 token 数
LIGHTRAG_MAX_TOKEN_SIZE=4096

# OpenAI 配置（必需）
OPENAI_API_KEY=sk-your-key-here
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-3.5-turbo
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

### Docker Build 配置

在 `.env` 中控制构建时行为：

```bash
# 是否在构建时初始化 LightRAG
INIT_LIGHTRAG_ON_BUILD=true

# 限制初始化的菜谱数量（留空=全部）
LIGHTRAG_INIT_LIMIT=
```

---

## 故障排查

### 1. 索引文件不存在

**症状**: 查询返回空结果或错误

**解决**:
```bash
# 检查索引文件
docker-compose exec server ls -lh /app/data/lightrag/

# 如果文件不存在，重新构建
docker-compose down
docker-compose build --no-cache server
docker-compose up -d
```

### 2. 查询失败

**症状**: API 返回 500 错误

**解决**:
```bash
# 查看日志
docker-compose logs -f server

# 检查配置
docker-compose exec server env | grep LIGHTRAG
docker-compose exec server env | grep OPENAI
```

### 3. 流式响应中断

**症状**: 流式查询没有完整返回

**解决**:
- 检查网络连接
- 增加客户端超时时间
- 查看服务器日志

### 4. 内存不足

**症状**: Docker 容器崩溃或 OOM

**解决**:
```bash
# 增加 Docker 内存限制
# 在 docker-compose.yml 中添加:
services:
  server:
    deploy:
      resources:
        limits:
          memory: 4G
```

---

## 性能优化

### 1. 索引文件预加载

索引文件在 Docker build 时生成，运行时直接加载，无需重建。

### 2. 缓存策略

LightRAG 内部实现了查询缓存，相同查询会直接返回缓存结果。

### 3. 批量插入

如果需要插入大量文档，使用批量插入接口：

```python
documents = [...]  # 1000+ 文档
result = await service.insert_documents(documents, batch_size=50)
```

### 4. 检索模式选择

- **快速查询**: 使用 `naive` 模式
- **准确查询**: 使用 `hybrid` 或 `global` 模式
- **平衡**: 使用 `hybrid` 模式（推荐）

---

## 与 Neo4j 知识图谱的对比

| 特性 | LightRAG | Neo4j KG |
|------|----------|----------|
| **数据类型** | 非结构化文本 | 结构化实体关系 |
| **查询方式** | 自然语言问答 | Cypher 查询 |
| **存储格式** | JSON + GraphML | 图数据库 |
| **初始化** | Docker build 时 | Docker build 时（CSV 导入） |
| **适用场景** | 语义搜索、问答 | 精确关系查询 |
| **更新方式** | 增量插入 | Cypher 更新 |

**两者是互补的**：
- **LightRAG**: 适合 "红烧肉怎么做？" 这类问答
- **Neo4j**: 适合 "找出所有包含五花肉的川菜" 这类关系查询

---

## 最佳实践

1. **使用 `hybrid` 模式**作为默认检索模式
2. **在 Docker build 时初始化索引**，减少运行时开销
3. **监控索引文件大小**，定期清理或重建
4. **使用流式响应**提升用户体验（实时反馈）
5. **合理设置 `top_k`**，平衡准确度和性能
6. **定期备份索引文件**（在 `data/lightrag/` 目录）

---

## 参考资源

- **LightRAG GitHub**: https://github.com/HKUDS/LightRAG
- **官方文档**: https://lightrag.readthedocs.io/
- **项目配置**: `gustobot/config/settings.py`
- **服务实现**: `gustobot/services/lightrag_service.py`
- **API 路由**: `gustobot/api/lightrag_router.py`
- **测试脚本**: `scripts/test_lightrag_service.py`
