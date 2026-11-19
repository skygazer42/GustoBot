> 历史架构资料，仅供溯源；其中旧路由、LightRAG／pgvector 和部署命令已退役。当前使用说明见 [快速启动](../../QUICK_START.md) 与 [领域服务](../../DOMAIN_KNOWLEDGE.md)。

# GustoBot 配置总结

## 配置更新完成 ✅

已成功更新 `.env` 和 `gustobot/config/settings.py` 文件，添加了统一的服务配置格式。

### 1. LLM 服务配置

```bash
# 用于文本生成和问答
LLM_PROVIDER=openai
LLM_MODEL=Qwen3-30B-A3B
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=http://your-llm-host:8000/v1
```

**用途**: Multi-Agent系统中的LLM调用，包括路由分类、知识问答、对话生成等。

### 2. Embedding 服务配置

```bash
# 用于向量生成
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=bge-m3
EMBEDDING_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EMBEDDING_BASE_URL=http://your-embedding-host:9997/v1
EMBEDDING_DIMENSION=1024
```

**用途**: 
- 将文本转换为向量（1024维）
- 用于Milvus向量数据库检索
- 语义相似度计算

### 3. Reranker 服务配置

```bash
# 用于精排
RERANK_ENABLED=true
RERANK_PROVIDER=custom
RERANK_BASE_URL=http://your-rerank-host:9997/v1
RERANK_ENDPOINT=/rerank
RERANK_MODEL=bge-reranker-large
RERANK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RERANK_MAX_CANDIDATES=20
RERANK_TOP_N=6
RERANK_TIMEOUT=30
RERANK_SCORE_FUSION_ALPHA=0.5
```

**用途**: 
- 对初步检索结果进行精排
- 提高最终返回结果的相关性
- 工作流: Milvus召回20条 → Reranker精排 → 返回Top 6

## 兼容性说明

为了保持向后兼容，同时保留了旧的配置项：

### 旧配置（仍然有效）
```bash
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_API_BASE=http://your-llm-host:8000/v1
OPENAI_MODEL=Qwen3-30B-A3B

RERANKER_PROVIDER=custom
RERANKER_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RERANKER_MODEL=bge-reranker-large
RERANKER_API_URL=http://your-rerank-host:9997/v1
RERANKER_TOP_K=6
```

## 配置验证

运行以下命令验证配置是否正确加载：

```bash
python3 -c "
from gustobot.config.settings import settings
print('LLM Base URL:', settings.LLM_BASE_URL)
print('Embedding Base URL:', settings.EMBEDDING_BASE_URL)
print('Rerank Base URL:', settings.RERANK_BASE_URL)
"
```

**预期输出**:
```
LLM Base URL: http://your-llm-host:8000/v1
Embedding Base URL: http://your-embedding-host:9997/v1
Rerank Base URL: http://your-rerank-host:9997/v1
```

## Settings.py 更新内容

在 `gustobot/config/settings.py` 中添加了以下字段：

### 新增字段
1. **LLM_PROVIDER** - LLM服务提供商
2. **LLM_MODEL** - LLM模型名称
3. **LLM_API_KEY** - LLM API密钥
4. **LLM_BASE_URL** - LLM服务地址

5. **EMBEDDING_PROVIDER** - Embedding服务提供商
6. **EMBEDDING_API_KEY** - Embedding API密钥
7. **EMBEDDING_BASE_URL** - Embedding服务地址

8. **RERANK_ENABLED** - 是否启用Reranker
9. **RERANK_PROVIDER** - Reranker提供商
10. **RERANK_BASE_URL** - Reranker服务地址
11. **RERANK_ENDPOINT** - Reranker端点路径
12. **RERANK_MODEL** - Reranker模型名称
13. **RERANK_API_KEY** - Reranker API密钥
14. **RERANK_MAX_CANDIDATES** - 重排序候选数量
15. **RERANK_TOP_N** - 返回Top N结果
16. **RERANK_TIMEOUT** - API超时时间
17. **RERANK_SCORE_FUSION_ALPHA** - 分数融合参数

18. **OLLAMA_BASE_URL** - Ollama服务地址
19. **OLLAMA_EMBEDDING_MODEL** - Ollama Embedding模型

20. **INIT_LIGHTRAG_ON_BUILD** - Docker构建时初始化LightRAG
21. **LIGHTRAG_INIT_LIMIT** - 初始化菜谱数量限制

### 修改的字段
- **CORS_ORIGINS**: 从 Tuple 改为 str (逗号分隔)
- 添加了 `cors_origins_list` 属性方法解析字符串为列表

## 使用建议

### 1. 开发环境
直接修改 `.env` 文件中的配置项

### 2. Docker环境
配置会通过 docker-compose.yml 的 env_file 自动加载

### 3. 生产环境
建议使用环境变量或密钥管理服务，不要将敏感信息提交到代码仓库

## 检索工作流

完整的知识检索流程：

```
用户问题
    ↓
1. Embedding服务 (bge-m3) → 生成查询向量
    ↓
2. Milvus向量数据库 → 召回Top 20相似文档
    ↓
3. Reranker服务 (bge-reranker-large) → 精排
    ↓
4. 返回Top 6最相关文档
    ↓
5. LLM服务 (Qwen3-30B-A3B) → 基于文档生成答案
```

## 常见问题

### Q: 如何切换到不同的Embedding模型？
A: 修改 `.env` 中的 `EMBEDDING_MODEL` 和 `EMBEDDING_DIMENSION` 即可。

### Q: Reranker可以禁用吗？
A: 可以，设置 `RERANK_ENABLED=false` 即可跳过精排步骤。

### Q: 如何使用OpenAI官方服务？
A: 将对应的 `*_BASE_URL` 改为OpenAI官方地址，并提供有效的API密钥。

### Q: 旧代码会受影响吗？
A: 不会，保留了所有旧配置项，同时支持新旧两种配置方式。

## 下一步

1. 确认所有API服务可访问：
   - http://your-llm-host:8000/v1 (LLM)
   - http://your-embedding-host:9997/v1 (Embedding & Reranker)

2. 启动服务：
   ```bash
   docker-compose up -d
   ```

3. 访问API文档：
   http://localhost:8000/docs

4. 测试配置：
   ```bash
   curl -X POST "http://localhost:8000/api/v1/chat/" \
     -H "Content-Type: application/json" \
     -d '{"message": "如何做红烧肉？"}'
   ```

---

**配置更新完成时间**: $(date '+%Y-%m-%d %H:%M:%S')
