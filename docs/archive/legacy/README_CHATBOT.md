> 历史架构资料，仅供溯源；其中旧路由、LightRAG／pgvector 和部署命令已退役。当前使用说明见 [快速启动](../../QUICK_START.md) 与 [领域服务](../../DOMAIN_KNOWLEDGE.md)。

# GustoBot 智能聊天系统

GustoBot 是一个基于多智能体架构的智能菜谱助手，能够自动理解用户意图并路由到相应的处理模块。

## 🚀 快速开始

### 1. 环境准备

确保已安装必要的依赖：

```bash
pip install -r requirements.txt
```

配置环境变量（`.env` 文件）：

```env
# 必需的 API 密钥（推荐使用 LLM_*，也兼容 OPENAI_*）
LLM_API_KEY=your_api_key_here

# 可选配置
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
MILVUS_HOST=localhost
MILVUS_PORT=19530
REDIS_URL=redis://localhost:6379
NEO4J_URI=bolt://localhost:7687
```

### 2. 启动系统

使用提供的启动脚本：

```bash
python start_chatbot.py
```

或者分别启动前后端：

```bash
# 启动后端（终端1）
python -m uvicorn gustobot.main:application --reload --host 0.0.0.0 --port 8000

# 启动前端（终端2）
cd web
npm install
npm run dev
```

### 3. 访问界面

- **聊天界面**: http://localhost:5174/（若 5174 被占用，Vite 会自动选择下一个空闲端口）
- **API 文档**: http://localhost:8000/docs

## 💬 使用说明

### 功能特点

1. **自动路由**：系统会根据您的问题自动选择合适的处理方式
2. **多模态支持**：支持文本、图片、文件上传
3. **实时响应**：支持流式输出，实时查看回复
4. **对话历史**：自动保存对话记录
5. **双重界面**：全屏模式和右下角小部件

### 路由类型

| 路由类型 | 说明 | 示例 |
|---------|------|------|
| general-query | 日常对话 | "你好"、"谢谢" |
| kb-query | 知识库查询 | "宫保鸡丁的历史"、"川菜特点" |
| graphrag-query | 图谱查询 | "红烧肉怎么做"、"需要什么食材" |
| text2sql-query | 统计查询 | "有多少道菜"、"最受欢迎的菜" |
| additional-query | 补充信息 | "我想做菜"、"推荐一道菜" |
| image-query | 图片处理 | "生成红烧肉图片" |
| file-query | 文件处理 | "分析这个菜谱文档" |

### 使用示例

1. **询问做法**：
   ```
   用户: 麻婆豆腐怎么做？
   系统: [自动路由到 graphrag-query]
       麻婆豆腐的做法是...
   ```

2. **了解历史**：
   ```
   用户: 佛跳墙有什么典故？
   系统: [自动路由到 kb-query]
       佛跳墙是福建名菜，传说...
   ```

3. **统计数据**：
   ```
   用户: 数据库里有多少道川菜？
   系统: [自动路由到 text2sql-query]
       数据库中共有156道川菜...
   ```

## 🔧 API 接口

### 统一聊天接口

**POST** `/api/v1/chat/`（推荐）

```json
{
  "message": "红烧肉怎么做？",
  "session_id": "optional-session-id",
  "user_id": "user-identifier",
  "stream": false,
  "file_path": "path/to/file",
  "image_path": "path/to/image"
}
```

**流式响应**

- **POST** `/api/v1/chat/stream`（推荐，SSE）
- **GET** `/api/v1/chat/chat/stream`（兼容旧版本，SSE）

GET 方式下参数通过 query string 传递；POST 方式使用 JSON body（与非流式一致）。

> 兼容旧接口：`POST /api/v1/chat/chat` 仍可用，但建议迁移到 `/api/v1/chat/`。

### 其他接口

- **GET** `/api/v1/chat/history/{session_id}` - 获取对话历史
- **DELETE** `/api/v1/chat/session/{session_id}` - 清空会话
- **GET** `/api/v1/chat/routes` - 获取路由信息

## 🧪 测试

运行测试脚本验证 API 功能：

```bash
python tests/test_chat_api.py
```

## 🏗️ 系统架构

```
用户提问
    ↓
统一聊天接口 (/api/v1/chat)
    ↓
Agent 路由系统 (LangGraph)
    ↓
┌─────────────┬─────────────┬─────────────┐
│  知识库查询  │   图谱查询   │   统计查询   │
│  (KB-Query) │(GraphRAG)   │(Text2SQL)   │
└─────────────┴─────────────┴─────────────┘
    ↓
统一回复（带路由信息和来源）
```

## 📁 项目结构

```
GustoBot/
├── gustobot/                # 后端代码
│   ├── interfaces/http/v1/  # API 路由
│   │   └── chat.py         # 聊天接口
│   ├── application/agents/  # 智能体系统
│   └── main.py             # FastAPI 应用
├── web/                     # 前端代码
│   ├── src/                 # Vue 代码
│   └── vite.config.ts       # Vite 配置
├── start_chatbot.py        # 启动脚本
├── tests/                  # 测试脚本
└── README_CHATBOT.md       # 本文档
```

## 🛠️ 开发指南

### 添加新的路由类型

1. 在 `lg_prompts.py` 中添加路由描述
2. 在 `lg_states.py` 中添加路由类型
3. 在 `lg_builder.py` 中添加处理逻辑
4. 更新前端显示名称

### 自定义前端

前端使用 Vue 3 + Vite 实现：

- 修改 `web/src/components/ChatWidget.vue` 调整聊天小部件
- 修改 `web/src/components/LandingPage.vue` 调整首页内容
- `web/vite.config.ts` 中配置代理，将 `/api` 与 `/uploads` 转发到后端

## 📝 注意事项

1. **API 密钥**：确保正确配置 `LLM_API_KEY`（或 `OPENAI_API_KEY`）
2. **依赖服务**：确保 Milvus、Redis、Neo4j等服务正常运行（如需要）
3. **文件上传**：文件保存在服务器，确保有足够的存储空间
4. **会话管理**：会话 ID 可保存在 localStorage 中

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

Apache-2.0 License
