# GustoBot 开发环境配置

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

一键启动后端 + 依赖服务（Neo4j / MySQL / Redis / Milvus / pgvector 等）：

```bash
# 启动所有服务（后端 + 数据库/向量库等）
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

访问地址：
- 后端 API： http://localhost:8000
- API 文档： http://localhost:8000/docs
- Neo4j Browser： http://localhost:17474

> 前端是 `web/` 下的 Vite 应用，需要单独启动（见下文“前端启动”）。

### 方式二：本地开发

#### 1. 后端启动

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动后端
python run.py start
```

#### 2. 前端启动

```bash
# 进入前端目录
cd web

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

默认访问：http://localhost:5174（可通过环境变量 `VITE_PORT` 修改端口；若 5174 被占用，Vite 会自动选择下一个空闲端口）

## 📁 项目结构

```
GustoBot/
├── gustobot/                 # 后端代码
│   ├── application/        # 业务逻辑
│   ├── interfaces/http/    # API 接口
│   └── main.py            # 应用入口
├── web/                    # 前端代码
│   ├── src/
│   │   ├── components/    # Vue 组件
│   │   └── App.vue        # 应用入口
│   ├── package.json       # 前端依赖
│   └── vite.config.ts     # Vite 配置
├── docker-compose.yml     # Docker Compose 配置
├── .env                    # 环境变量
└── requirements.txt        # Python 依赖
```

## 🔧 开发配置

### 环境变量

创建 `.env` 文件：

```env
# LLM 配置
LLM_PROVIDER=openai
LLM_MODEL=qwen3-max
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 数据库配置
DATABASE_URL=mysql+pymysql://recipe_user:recipepass@localhost:3306/recipe_db
REDIS_URL=redis://localhost:6379
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=recipepass

# 向量数据库
MILVUS_HOST=localhost
MILVUS_PORT=19530

# 应用配置
DEBUG=true
CORS_ORIGINS=http://localhost:5174
```

### 前端环境变量

在 `web` 目录下创建 `.env.local`：

```env
# 最小配置：固定前端开发端口
VITE_PORT=5174

# 可选：仅当后端不在默认的 http://localhost:8000 时再显式指定
# VITE_API_BASE_URL=http://localhost:18000
```

## 🛠️ 开发工作流

### 1. 修改后端 API

1. 在 `gustobot/interfaces/http/` 目录下修改 API
2. 后端会自动重启（开发模式）
3. 前端会自动刷新（热重载）

### 2. 修改前端组件

1. 在 `web/src/` 目录下修改组件
2. 保存后会自动刷新浏览器
3. 使用 Vue Devtools 调试

### 3. 调试技巧

#### 后端调试

```bash
# 查看详细日志
export DEBUG=true

# 使用调试器
python -m debugpy --listen 5678 run.py start
```

#### 前端调试

- 使用浏览器 DevTools
- React 组件使用 React DevTools
- API 请求在 Network 标签查看

## 📊 常用命令

### 后端

```bash
# 测试 API
python tests/test_router_smoke.py

# 代码格式化
black gustobot/

# 类型检查
mypy gustobot/

# 运行测试
pytest tests/ -v
```

### 前端

```bash
# 安装新依赖
npm install package-name

# 构建生产版本
npm run build

# 预览构建结果
npm run preview

# 代码检查
npm run lint
```

## 🐛 故障排除

### 后端问题

1. **端口占用**
   ```bash
   # 查看端口占用
   netstat -tulpn | grep :8000
   # Windows
   netstat -ano | findstr :8000
   ```

2. **依赖问题**
   ```bash
   # 重新安装依赖
   pip install -r requirements.txt --force-reinstall
   ```

3. **数据库连接失败**
   - 检查 MySQL/Redis/Neo4j 是否运行
   - 验证连接字符串
   - 查看服务日志

### 前端问题

1. **无法连接后端**
   - 检查后端是否在 8000 端口运行
   - 检查 Vite 代理配置
   - 查看 CORS 设置

2. **依赖安装失败**
   ```bash
   # 清除缓存
   npm cache clean --force
   rm -rf node_modules package-lock.json
   npm install
   ```

3. **热重载不工作**
   - 检查文件监听权限
   - 重启开发服务器

## 🚀 部署到生产环境

### 构建 Docker 镜像

```bash
# 构建后端镜像
docker build -t gustobot-backend .

# 构建前端镜像
cd web
docker build -t gustobot-frontend .
```

### 生产环境配置

```bash
# 使用生产配置
docker-compose -f docker-compose.yml up -d
```

## 📚 学习资源

- [React 官方文档](https://react.dev/)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Docker 官方文档](https://docs.docker.com/)
- [Tailwind CSS 文档](https://tailwindcss.com/)

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 创建 Pull Request

## 📞 支持

如有问题，请：
1. 查看本文档
2. 搜索 Issues
3. 创建新的 Issue
