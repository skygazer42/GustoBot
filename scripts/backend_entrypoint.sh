#!/bin/bash
set -euo pipefail

INIT_KB_MILVUS="${INIT_KB_MILVUS:-true}"
KB_DATA_FILE="${KB_DATA_FILE:-/app/data/kb/data.txt}"
KB_MILVUS_SENTINEL="${KB_MILVUS_SENTINEL:-/app/data/.kb_milvus_ingested}"
AUTO_BOOTSTRAP_LIGHTRAG="${AUTO_BOOTSTRAP_LIGHTRAG:-true}"
LIGHTRAG_BOOTSTRAP_DIR="${LIGHTRAG_BOOTSTRAP_DIR:-/app/bootstrap/lightrag_template}"
LIGHTRAG_WORKING_DIR="${LIGHTRAG_WORKING_DIR:-./data/lightrag}"
RECIPE_BOOTSTRAP=$(python -c "from gustobot.config.domain import get_domain_definition; d = get_domain_definition(); print('true' if d.id == 'recipes' and d.document_index_namespace == '.' else 'false')")
LEGACY_KB_BOOTSTRAP=$(python -c "from gustobot.config.domain import get_domain_definition; print('true' if get_domain_definition().document_backend == 'legacy_kb' else 'false')")

resolve_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    ""|.) printf '%s\n' "/app" ;;
    ./*) printf '%s\n' "/app/${1#./}" ;;
    *) printf '%s\n' "/app/$1" ;;
  esac
}

LIGHTRAG_WORKING_DIR_ABS=$(resolve_path "$LIGHTRAG_WORKING_DIR")
LIGHTRAG_BOOTSTRAP_DIR_ABS=$(resolve_path "$LIGHTRAG_BOOTSTRAP_DIR")

bootstrap_lightrag_data() {
  if [ "${AUTO_BOOTSTRAP_LIGHTRAG,,}" != "true" ]; then
    echo "[backend] LightRAG bootstrap disabled via AUTO_BOOTSTRAP_LIGHTRAG=${AUTO_BOOTSTRAP_LIGHTRAG}"
    return
  fi

  if [ ! -d "${LIGHTRAG_BOOTSTRAP_DIR_ABS}" ] || [ -z "$(ls -A "${LIGHTRAG_BOOTSTRAP_DIR_ABS}" 2>/dev/null)" ]; then
    echo "[backend] LightRAG bootstrap目录不存在或为空，跳过自动导入。"
    return
  fi

  mkdir -p "${LIGHTRAG_WORKING_DIR_ABS}"
  if [ -n "$(ls -A "${LIGHTRAG_WORKING_DIR_ABS}" 2>/dev/null)" ]; then
    echo "[backend] LightRAG 工作目录已存在内容，跳过自动导入。"
    return
  fi

  echo "[backend] LightRAG 工作目录为空，正在从模板复制初始数据..."
  cp -a "${LIGHTRAG_BOOTSTRAP_DIR_ABS}/." "${LIGHTRAG_WORKING_DIR_ABS}/"
  echo "[backend] LightRAG 初始数据复制完成。"
}

if [ "$RECIPE_BOOTSTRAP" = "true" ]; then
  bootstrap_lightrag_data
else
  echo "[backend] Current domain skips legacy recipe LightRAG bootstrap."
fi

wait_for_mysql() {
  python - <<'PY'
import os
import time
from urllib.parse import urlparse

import pymysql

database_url = os.getenv("DATABASE_URL", "").strip()
if not database_url or database_url.startswith("sqlite"):
    print("[backend] DATABASE_URL indicates SQLite or is unset; skipping MySQL wait.")
    raise SystemExit(0)

parsed = urlparse(database_url)
host = parsed.hostname or os.getenv("MYSQL_HOST", "mysql")
port = parsed.port or int(os.getenv("MYSQL_PORT", "3306"))
user = parsed.username or os.getenv("MYSQL_USER") or "root"
password = parsed.password or os.getenv("MYSQL_PASSWORD") or os.getenv("MYSQL_ROOT_PASSWORD") or ""
db_name = (parsed.path or "").lstrip("/") or os.getenv("MYSQL_DATABASE") or None

deadline = time.monotonic() + int(os.getenv("MYSQL_WAIT_SECONDS", "180"))
print(f"[backend] Waiting for MySQL at {host}:{port} (db={db_name or '<default>'}) ...")

while time.monotonic() < deadline:
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db_name,
            connect_timeout=5,
            read_timeout=5,
            write_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        print("[backend] MySQL is ready.")
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit(f"MySQL is not reachable at {host}:{port} within timeout")
PY
}

wait_for_milvus() {
  python - <<'PY'
import os
import time
from pymilvus import connections

host = os.getenv("MILVUS_HOST", "milvus")
port = os.getenv("MILVUS_PORT", "19530")
deadline = time.monotonic() + 120

while time.monotonic() < deadline:
    try:
        connections.connect(alias="default", host=host, port=port, timeout=5)
        connections.disconnect("default")
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit("Milvus is not reachable for KB initialisation")
PY
}

run_milvus_ingest() {
  if [ "${INIT_KB_MILVUS,,}" = "false" ]; then
    echo "[backend] KB Milvus ingestion disabled via INIT_KB_MILVUS=false."
    return
  fi

  if [ ! -f "${KB_DATA_FILE}" ]; then
    echo "[backend] KB data file not found: ${KB_DATA_FILE}, skipping Milvus ingestion."
    return
  fi

  if [ -f "${KB_MILVUS_SENTINEL}" ]; then
    echo "[backend] KB Milvus dataset already ingested, skipping."
    return
  fi

  echo "[backend] Waiting for Milvus to become available..."
  wait_for_milvus

  echo "[backend] Importing KB dataset into Milvus from ${KB_DATA_FILE}"
  if python scripts/init_kb_milvus.py; then
    touch "${KB_MILVUS_SENTINEL}"
    echo "[backend] Milvus ingestion completed."
  else
    echo "[backend] Milvus ingestion failed; continuing without bootstrap data." >&2
  fi
}

if [ "$LEGACY_KB_BOOTSTRAP" = "true" ]; then
  run_milvus_ingest
else
  echo "[backend] Current domain skips legacy Milvus bootstrap."
fi

wait_for_mysql

exec "$@"
