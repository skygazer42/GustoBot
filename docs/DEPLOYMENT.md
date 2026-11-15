> 历史文档：下文保留旧部署与接口说明。2026-11-15 已将图查询统一至 LightRAG，移除 Cypher/Neo4j 运行链路；当前配置、接口和部署请以 [领域知识服务](DOMAIN_KNOWLEDGE.md) 与 [快速启动](QUICK_START.md) 为准。

# GustoBot 部署文档

本指南详细说明如何部署 GustoBot 智能菜谱助手系统。

## 📋 目录

1. [系统要求](#系统要求)
2. [快速部署](#快速部署)
3. [详细配置](#详细配置)
4. [Docker 部署](#docker-部署)
5. [生产环境部署](#生产环境部署)
6. [故障排除](#故障排除)

## 🔧 系统要求

### 最低配置
- **Python**: 3.9+
- **内存**: 4GB RAM
- **存储**: 10GB 可用空间
- **网络**: 互联网连接（用于 API 调用）

### 推荐配置
- **Python**: 3.9+
- **内存**: 8GB RAM
- **存储**: 50GB 可用空间（SSD 推荐）
- **CPU**: 4 核心
- **网络**: 稳定的互联网连接

### 依赖服务（可选）
- **Milvus**: 向量数据库（用于知识检索）
- **Redis**: 缓存服务
- **Neo4j**: 图数据库（用于图谱查询）
- **MySQL**: 关系数据库（用于结构化数据）

## 🚀 快速部署

### 1. 克隆项目

```bash
git clone https://github.com/your-username/GustoBot.git
cd GustoBot
```

### 2. 创建虚拟环境

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

创建 `.env` 文件：

```env
# OpenAI API（必需）
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4

# 数据库配置
DATABASE_URL=sqlite:///./gustobot.db
REDIS_URL=redis://localhost:6379

# Milvus配置
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=gustobot_recipes

# Neo4j配置
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# 文件上传配置
FILE_UPLOAD_MAX_MB=50
UPLOAD_DIR=./uploads

# 应用配置
DEBUG=false
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=["*"]
```

### 5. 启动服务

```bash
# 使用启动脚本（推荐）
python start_chatbot.py

# 或手动启动
python -m uvicorn gustobot.main:application --reload --host 0.0.0.0 --port 8000
```

### 6. 访问系统

- **聊天界面**: http://localhost:8000/
- **API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

## 📝 详细配置

### 环境变量说明

| 变量名 | 必需 | 说明 | 示例 |
|--------|------|------|------|
| OPENAI_API_KEY | 是 | OpenAI API 密钥 | sk-... |
| OPENAI_MODEL | 否 | 使用的模型 | gpt-4, gpt-3.5-turbo |
| DATABASE_URL | 否 | 数据库连接字符串 | sqlite:///./gustobot.db |
| REDIS_URL | 否 | Redis 连接字符串 | redis://localhost:6379 |
| MILVUS_HOST | 否 | Milvus 主机地址 | localhost |
| NEO4J_URI | 否 | Neo4j 连接地址 | bolt://localhost:7687 |
| DEBUG | 否 | 调试模式 | true/false |
| FILE_UPLOAD_MAX_MB | 否 | 最大上传文件大小(MB) | 50 |

### 数据库初始化

如果使用 MySQL/PostgreSQL：

```bash
# 创建数据库
mysql -u root -p -e "CREATE DATABASE gustobot;"

# 运行迁移（如果有）
alembic upgrade head
```

### Milvus 设置

```bash
# 使用 Docker 启动 Milvus
docker-compose up -d milvus etcd minio

# 或使用 Python 客户端创建 collection
python -c "
from pymilvus import connections, CollectionSchema, FieldSchema, DataType, Collection
connections.connect('default', host='localhost', port='19530')
# 创建 collection...
"
```

### Neo4j 设置

```bash
# 使用 Docker 启动 Neo4j
docker-compose up -d neo4j

# 访问 Neo4j Browser: http://localhost:17474
# 用户名: neo4j
# 密码: 在 docker-compose.yml 中配置
```

## 🐳 Docker 部署

### 1. 使用 Docker Compose（推荐）

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  gustobot:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - REDIS_URL=redis://redis:6379
      - MILVUS_HOST=milvus
      - NEO4J_URI=bolt://neo4j:7687
    volumes:
      - ./uploads:/app/uploads
    depends_on:
      - redis
      - milvus
      - neo4j

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  milvus:
    image: milvusdb/milvus:v2.3.0
    ports:
      - "19530:19530"
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio:9000
    volumes:
      - milvus_data:/var/lib/milvus
    depends_on:
      - etcd
      - minio

  etcd:
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
    volumes:
      - etcd_data:/etcd

  minio:
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    volumes:
      - minio_data:/data
    command: server /data --console-address ":9001"

  neo4j:
    image: neo4j:5.12-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/password
      - NEO4J_PLUGINS=["apoc"]
    volumes:
      - neo4j_data:/data

volumes:
  milvus_data:
  etcd_data:
  minio_data:
  neo4j_data:
```

### 2. 构建和运行

```bash
# 构建镜像
docker build -t gustobot .

# 运行服务
docker-compose up -d

# 查看日志
docker-compose logs -f gustobot
```

### 3. Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY . .

# 创建上传目录
RUN mkdir -p uploads

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "uvicorn", "gustobot.main:application", "--host", "0.0.0.0", "--port", "8000"]
```

## 🌐 生产环境部署

### 1. 使用 Gunicorn（Linux）

```bash
# 安装 Gunicorn
pip install gunicorn

# 创建 gunicorn.conf.py
bind = "0.0.0.0:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
timeout = 60
keepalive = 2
max_requests = 1000
max_requests_jitter = 100
preload_app = True
```

启动服务：

```bash
gunicorn -c gunicorn.conf.py gustobot.main:application
```

### 2. 使用 Systemd（Linux 服务）

创建服务文件 `/etc/systemd/system/gustobot.service`：

```ini
[Unit]
Description=GustoBot Chat Service
After=network.target

[Service]
User=gustobot
Group=gustobot
WorkingDirectory=/opt/gustobot
Environment="PATH=/opt/gustobot/venv/bin"
ExecStart=/opt/gustobot/venv/bin/gunicorn -c gunicorn.conf.py gustobot.main:application
Restart=always

[Install]
WantedBy=multi-user.target
```

启用和启动服务：

```bash
sudo systemctl enable gustobot
sudo systemctl start gustobot
sudo systemctl status gustobot
```

### 3. 使用 Nginx 反向代理

创建 Nginx 配置 `/etc/nginx/sites-available/gustobot`：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE 支持（流式返回）
    location /api/v1/chat/stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 静态文件
    location /uploads/ {
        alias /opt/gustobot/uploads/;
        expires 30d;
    }
}
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/gustobot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4. SSL/HTTPS 配置

使用 Let's Encrypt：

```bash
# 安装 Certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期
sudo crontab -e
# 添加: 0 12 * * * /usr/bin/certbot renew --quiet
```

## 🔍 故障排除

### 常见问题

1. **LLM API 错误**
   ```
   错误: OPENAI_API_KEY is not configured
   解决: 在 .env 文件中设置正确的 API 密钥（LLM_API_KEY 或 OPENAI_API_KEY）
   ```

2. **端口占用**
   ```
   错误: Port 8000 is already in use
   解决: 更改端口或停止占用端口的进程
   ```

3. **文件上传失败**
   ```
   错误: 413 Request Entity Too Large
   解决: 增加 FILE_UPLOAD_MAX_MB 的值
   ```

4. **CORS 错误**
   ```
   错误: Access to fetch at 'http://localhost:8000' has been blocked by CORS policy
   解决: 检查 CORS_ORIGINS 配置
   ```

5. **依赖服务连接失败**
   ```
   错误: Could not connect to Milvus
   解决: 确保 Milvus 服务正在运行并检查配置
   ```

### 日志查看

```bash
# 开发模式
python start_chatbot.py

# 查看应用日志
tail -f logs/gustobot.log

# Docker 日志
docker-compose logs -f gustobot

# Systemd 日志
journalctl -u gustobot -f
```

### 性能优化

1. **增加并发处理**
   ```python
   # 在 uvicorn 命令中添加 --workers
   uvicorn gustobot.main:application --workers 4
   ```

2. **启用 Redis 缓存**
   ```env
   REDIS_URL=redis://localhost:6379
   REDIS_CACHE_TTL=3600
   ```

3. **使用 CDN**
   - 将静态文件托管到 CDN
   - 减少 API 响应大小

4. **数据库优化**
   - 添加适当的索引
   - 使用连接池
   - 定期清理旧数据

## 📞 技术支持

如果遇到问题，请：

1. 查看日志文件获取详细错误信息
2. 检查环境变量配置
3. 确保所有依赖服务正常运行
4. 提交 Issue 到 GitHub 仓库

## 🔄 更新和维护

### 更新应用

```bash
# 拉取最新代码
git pull origin main

# 更新依赖
pip install -r requirements.txt

# 重启服务
sudo systemctl restart gustobot
```

### 备份数据

```bash
# 备份数据库
mysqldump -u root -p gustobot > backup.sql

# 备份上传文件
tar -czf uploads_backup.tar.gz uploads/

# 备份 Redis
redis-cli BGSAVE
cp dump.rdb redis_backup.rdb
```

---

## 📚 其他资源

- [API 文档](http://localhost:8000/docs)
- [项目主页](https://github.com/your-username/GustoBot)
- [贡献指南](CONTRIBUTING.md)
- [许可证](LICENSE)
