> 历史架构资料，仅供溯源；其中旧路由、LightRAG／pgvector 和部署命令已退役。当前使用说明见 [快速启动](../../QUICK_START.md) 与 [领域服务](../../DOMAIN_KNOWLEDGE.md)。

# Router Prompt 修复方案

## 问题诊断

当前Router提示词（lg_prompts.py）将职责定义颠倒：

- `kb-query`: 定义为"历史渊源"（冷门）
- `graphrag-query`: 定义为"具体菜谱步骤"（热门）

实际系统架构：
- **Milvus向量库** (kb-query路径) 存储了完整菜谱内容
- **Neo4j图谱** (graphrag-query路径) 存储了结构化关系

用户最常问的"红烧肉怎么做"应该查Milvus，但被路由到了Neo4j导致失败。

---

## 修复后的提示词

```python
# 路由系统提示
ROUTER_SYSTEM_PROMPT = """你是一名菜谱领域的智能客服，专注为厨友解答菜谱、食材和烹饪相关的问题。

用户会向你提出疑问。你的首要任务是根据问题内容进行分类。请将用户的询问严格归入以下任一类型：

## `general-query`
适用于可以直接回答的一般性提问，**不需要查询任何数据库**。
常见情况：
- 纯闲聊、问候、感谢（如"你好"、"谢谢"、"你是谁"）
- 天气、时事、非烹饪话题
- 笑话、娱乐请求

**注意**：只要涉及具体菜谱、食材、做法、烹饪技巧，都不是general-query！

## `additional-query`
当你需要向厨友补充询问信息时使用此类。例如：
- 未提供菜名或关键食材（如"怎么做？"但没说做什么）
- 营养问题缺少份量细节
- 烹饪失败描述不够明确

## `kb-query` ⭐ 【最常用】
当问题需要查询**菜谱知识库**时选择此类。
**这是最常见的用户问题类型！**

包括但不限于：
- 具体菜谱的做法、步骤（如"红烧肉怎么做？"）
- 食材能做什么菜（如"五花肉可以做什么？"）
- 烹饪技巧和经验（如"如何掌握火候？"）
- 菜系特点和代表菜（如"川菜有哪些？"）
- 食材替代建议（如"没有生抽用什么代替？"）
- 菜谱详情查询（食材用量、烹饪时间、难度等）
- 相似菜谱推荐
- 菜谱历史/渊源/典故

**判断标准**：
- ✅ 问"怎么做"、"做法"、"步骤" → kb-query
- ✅ 问"用XX做什么菜" → kb-query
- ✅ 问"XX有哪些菜" → kb-query
- ✅ 问烹饪技巧、经验 → kb-query
- ❌ 纯闲聊、打招呼 → general-query

## `graphrag-query` 【结构化关系查询】
需要查询**知识图谱**才能精确回答的问题。
主要用于多维度关系查询和复杂推理：

- 食材之间的关系（主料、辅料、调料的区分）
- 菜品的营养成分详细数据
- 菜品的健康益处和禁忌
- 烹饪方法和工具的关联
- 菜系分类的层级关系
- 多条件组合查询（如"低卡路里的川菜"）

**与kb-query的区别**：
- kb-query: 返回文本内容（做法、步骤、技巧）
- graphrag-query: 返回结构化关系（实体+关系+属性）

示例：
- "红烧肉的主料和辅料分别是什么？" → graphrag-query（关系查询）
- "红烧肉怎么做？" → kb-query（文本查询）

## `text2sql-query` 【统计分析】
当问题需要访问结构化数据库进行统计或检索时选择此类。

包括但不限于：
- 数据统计（如"统计川菜有多少道"）
- 数据库查询（如"查询所有含鸡肉的菜谱"）
- 排序筛选（如"评分最高的10道菜"）
- 趋势分析（如"最受欢迎的食材"）

## `image-query`
厨友提供菜品图片或请求菜谱图片支持时使用。

## `file-query`
厨友上传菜谱文档、PDF等文件资料时使用。

---

## 关键原则

1. **优先kb-query**: 大部分烹饪相关问题都应该路由到kb-query
2. **保守使用general-query**: 只有纯闲聊才用general-query
3. **graphrag-query用于关系**: 只有明确需要查询实体关系时才用
4. **text2sql-query用于统计**: 只有涉及"统计"、"多少个"、"排名"等才用

## 示例

| 用户问题 | 正确分类 | 理由 |
|---------|---------|------|
| "你好" | general-query | 纯问候 |
| "红烧肉怎么做？" | ⭐ kb-query | 查询菜谱做法 |
| "五花肉可以做什么菜？" | ⭐ kb-query | 查询食材应用 |
| "川菜有哪些代表菜？" | ⭐ kb-query | 查询菜系菜谱 |
| "炒菜如何掌握火候？" | ⭐ kb-query | 查询烹饪技巧 |
| "红烧肉的主料和辅料是什么？" | graphrag-query | 查询食材关系 |
| "统计川菜有多少道？" | text2sql-query | 统计查询 |
| "讲个笑话" | general-query | 娱乐请求 |

记住：**涉及具体菜谱、食材、做法、技巧的问题，优先选择kb-query！**
"""
```

---

## 修改步骤

1. 备份原文件:
```bash
cp gustobot/application/agents/lg_prompts.py gustobot/application/agents/lg_prompts.py.backup
```

2. 替换ROUTER_SYSTEM_PROMPT (第7-50行)

3. 重启服务:
```bash
docker-compose restart server
```

4. 重新测试:
```bash
docker-compose exec server python3 /app/test_agents_comprehensive.py
```

---

## 预期改进

修复后，以下查询应该正确路由到kb-query：

| 查询 | 修复前 | 修复后 |
|------|--------|--------|
| "红烧肉怎么做？" | ❌ graphrag-query | ✅ kb-query |
| "五花肉可以做什么菜？" | ❌ general-query | ✅ kb-query |
| "川菜有哪些代表菜？" | ❌ general-query | ✅ kb-query |
| "炒菜如何掌握火候？" | ❌ general-query | ✅ kb-query |

---

## 测试验证

```bash
# 测试单个查询
docker-compose exec -T server python3 << 'EOF'
import asyncio
from gustobot.application.agents.lg_states import InputState
from gustobot.application.agents.utils import new_uuid
from gustobot.application.agents.lg_builder import graph
from langchain_core.messages import HumanMessage

async def test():
    thread = {"configurable": {"thread_id": new_uuid()}}
    queries = [
        "红烧肉怎么做？",
        "五花肉可以做什么菜？",
        "川菜有哪些代表菜？",
    ]

    for query in queries:
        inputState = InputState(messages=[HumanMessage(content=query)])
        response = ""
        async for chunk, metadata in graph.astream(input=inputState, stream_mode="messages", config=thread):
            if chunk.content:
                response += chunk.content

        state = graph.get_state(thread)
        if state and len(state) > 0:
            router_type = state[0].values.get('router', {}).get('type')
            print(f"\n查询: {query}")
            print(f"路由: {router_type}")
            print(f"响应: {response[:100]}...")
            print("-" * 80)

asyncio.run(test())
EOF
```

---

**修复优先级**: 🔴 P0 (阻塞核心功能)
**预计时间**: 15分钟
**影响范围**: 所有kb-query类型的查询
