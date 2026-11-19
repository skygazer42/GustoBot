ARG PYTHON_VERSION=3.11
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
RUN sed -i 's/\r$//' scripts/backend_entrypoint.sh scripts/docker_entrypoint.sh && \
    mkdir -p /app/uploads

EXPOSE 8000
ENTRYPOINT ["sh", "scripts/backend_entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "gustobot.main:application", "--host", "0.0.0.0", "--port", "8000"]
