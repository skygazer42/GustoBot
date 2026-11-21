ARG PYTHON_VERSION=3.11

FROM milvusdb/milvus:v2.5.12 AS milvus
RUN printf '%s\n' \
    'listen-client-urls: http://0.0.0.0:2379' \
    'advertise-client-urls: http://0.0.0.0:2379' \
    'quota-backend-bytes: 4294967296' \
    'auto-compaction-mode: revision' \
    'auto-compaction-retention: "1000"' \
    > /milvus/configs/embedEtcd.yaml

FROM node:22-bookworm-slim AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:${PYTHON_VERSION}-slim AS server

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

COPY gustobot ./gustobot
COPY scripts ./scripts
COPY migrations ./migrations
COPY eval/knowledge ./eval/knowledge
COPY --from=web-build /web/dist ./web_dist
RUN sed -i 's/\r$//' scripts/backend_entrypoint.sh scripts/docker_entrypoint.sh && \
    mkdir -p /app/uploads

EXPOSE 8000
ENTRYPOINT ["sh", "scripts/backend_entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "gustobot.main:application", "--host", "0.0.0.0", "--port", "8000"]
