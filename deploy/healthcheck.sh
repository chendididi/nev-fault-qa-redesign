#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME=${PROJECT_NAME:-nev-fault-qa-redesign}
COMPOSE_FILES=${COMPOSE_FILES:-"-f docker-compose.yml -f docker-compose.cn.yml -f docker-compose.gpu.yml"}

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

WEB_PORT=${WEB_PORT:-3001}
VLLM_PORT=${VLLM_PORT:-8008}

docker compose -p "$PROJECT_NAME" $COMPOSE_FILES ps

echo "Checking API..."
curl -fsS http://localhost:8000/api/health
echo

echo "Checking web..."
curl -fsSI "http://localhost:${WEB_PORT}/chat" | head -n 1

echo "Checking MinIO..."
curl -fsSI http://localhost:9001 | head -n 1

echo "Checking vLLM /models..."
curl -fsS -H "Authorization: Bearer ${VLLM_API_KEY:-change-me-vllm-key}" "http://localhost:${VLLM_PORT}/v1/models" | head -c 500 || true
echo

echo "Healthcheck complete."
