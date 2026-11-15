#!/usr/bin/env bash
set -euo pipefail

LIGHTRAG_DIR="${LIGHTRAG_WORKING_DIR:-/app/data/lightrag}"
INIT_ON_STARTUP="${INIT_LIGHTRAG_ON_STARTUP:-true}"
LIGHTRAG_JSON_SOURCE="${LIGHTRAG_JSON_PATH:-/app/data/recipe.json}"
RECIPE_BOOTSTRAP=$(python -c "from gustobot.config.domain import get_domain_definition; d = get_domain_definition(); print('true' if d.id == 'recipes' and d.document_index_namespace == '.' else 'false')")

log() {
  printf '[entrypoint] %s\n' "$*"
}

bootstrap_lightrag() {
  local required_file="${LIGHTRAG_DIR}/kv_store_full_docs.json"

  if [ ! -f "$required_file" ] || [ ! -s "$required_file" ]; then
    if [ -z "${LLM_API_KEY:-}" ] || [ -z "${EMBEDDING_API_KEY:-}" ]; then
      log "LightRAG 初始化跳过：缺少 LLM_API_KEY 或 EMBEDDING_API_KEY。"
      return
    fi

    log "检测到 LightRAG 数据缺失，开始初始化..."
    mkdir -p "$LIGHTRAG_DIR"

    python /app/scripts/init_lightrag.py \
      --source json \
      --json-path "$LIGHTRAG_JSON_SOURCE" \
      ${LIGHTRAG_INIT_LIMIT:+--limit "$LIGHTRAG_INIT_LIMIT"}

    log "LightRAG 初始化完成。"
  else
    log "LightRAG 数据已存在，跳过初始化。"
  fi
}

if [ "$RECIPE_BOOTSTRAP" != "true" ]; then
  log "Current domain skips legacy recipe LightRAG bootstrap."
elif [ "$INIT_ON_STARTUP" = "true" ]; then
  bootstrap_lightrag
else
  log "INIT_LIGHTRAG_ON_STARTUP=false，跳过 LightRAG 初始化。"
fi

exec "$@"
