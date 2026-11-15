FROM python:3.10-slim AS server

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

RUN set -eux; \
    printf '%s\n' \
        "deb https://mirrors.tuna.tsinghua.edu.cn/debian trixie main contrib non-free" \
        "deb https://mirrors.tuna.tsinghua.edu.cn/debian trixie-updates main contrib non-free" \
        "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security trixie-security main contrib non-free" \
        > /etc/apt/sources.list; \
    rm -f /etc/apt/sources.list.d/*; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip -i https://mirrors.ustc.edu.cn/pypi/simple && \
    pip install -r requirements.txt -i https://mirrors.ustc.edu.cn/pypi/simple

COPY gustobot ./gustobot
COPY data ./data
COPY scripts ./scripts
COPY scripts/backend_entrypoint.sh ./backend_entrypoint.sh
RUN chmod +x /app/backend_entrypoint.sh && \
    sed -i 's/\r$//' /app/backend_entrypoint.sh

# Build-time arguments for LightRAG initialization (使用 .env 文件中的变量名)
ARG INIT_LIGHTRAG_ON_BUILD=false
ARG LLM_API_KEY
ARG LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ARG LLM_MODEL=qwen3-max
ARG EMBEDDING_API_KEY
ARG EMBEDDING_MODEL=qwen/qwen3-embedding-8b
ARG EMBEDDING_BASE_URL=http://139.224.116.116:3000/v1
ARG EMBEDDING_DIMENSION=4096
ARG LIGHTRAG_INIT_LIMIT=1000

# Persist configuration for runtime
ENV LLM_BASE_URL=${LLM_BASE_URL}
ENV LLM_MODEL=${LLM_MODEL}
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
ENV EMBEDDING_BASE_URL=${EMBEDDING_BASE_URL}
ENV EMBEDDING_DIMENSION=${EMBEDDING_DIMENSION}
ENV LIGHTRAG_BOOTSTRAP_DIR=/app/bootstrap/lightrag_template

# Initialize LightRAG data during build (if enabled)
# LightRAG 需要 OPENAI_API_KEY 环境变量，所以这里做映射
RUN if [ "$INIT_LIGHTRAG_ON_BUILD" = "true" ] && [ -n "$LLM_API_KEY" ]; then \
        echo "========================================"; \
        echo "Initializing LightRAG during build..."; \
        echo "========================================"; \
        mkdir -p ${LIGHTRAG_BOOTSTRAP_DIR} /app/data/lightrag; \
        export OPENAI_API_KEY=${LLM_API_KEY}; \
        export OPENAI_API_BASE=${LLM_BASE_URL}; \
        export OPENAI_MODEL=${LLM_MODEL}; \
        export EMBEDDING_API_KEY=${EMBEDDING_API_KEY}; \
        export EMBEDDING_MODEL=${EMBEDDING_MODEL}; \
        export EMBEDDING_BASE_URL=${EMBEDDING_BASE_URL}; \
        export EMBEDDING_DIMENSION=${EMBEDDING_DIMENSION}; \
        export LIGHTRAG_WORKING_DIR=${LIGHTRAG_BOOTSTRAP_DIR}; \
        python scripts/init_lightrag.py \
            --source json \
            --json-path /app/data/recipe.json \
            ${LIGHTRAG_INIT_LIMIT:+--limit $LIGHTRAG_INIT_LIMIT} && \
        cp -a ${LIGHTRAG_BOOTSTRAP_DIR}/. /app/data/lightrag/ && \
        echo "========================================"; \
        echo "LightRAG initialization completed!"; \
        echo "Generated files:"; \
        ls -lh /app/data/lightrag/; \
        echo "========================================"; \
    else \
        echo "Skipping LightRAG initialization during build"; \
        echo "  INIT_LIGHTRAG_ON_BUILD=${INIT_LIGHTRAG_ON_BUILD}"; \
        echo "  LLM_API_KEY set: $([ -n \"${LLM_API_KEY}\" ] && echo 'yes' || echo 'no')"; \
        mkdir -p ${LIGHTRAG_BOOTSTRAP_DIR} /app/data/lightrag; \
    fi

# Unset API keys for security
ENV LLM_API_KEY=your_api_key_here
ENV EMBEDDING_API_KEY=your_api_key_here

EXPOSE 8000
ENTRYPOINT ["./backend_entrypoint.sh"]
CMD ["uvicorn", "gustobot.main:application", "--host", "0.0.0.0", "--port", "8000"]
