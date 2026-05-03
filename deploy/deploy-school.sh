#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME=${PROJECT_NAME:-nev-fault-qa-redesign}
COMPOSE_FILES=${COMPOSE_FILES:-"-f docker-compose.yml -f docker-compose.cn.yml -f docker-compose.gpu.yml"}

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp deploy/env.school.example .env
  echo "Created .env from deploy/env.school.example. Edit SERVER_IP and secrets, then rerun this script."
  exit 1
fi

echo "Starting NEV Fault QA school deployment..."
docker compose -p "$PROJECT_NAME" $COMPOSE_FILES up -d --build

bash deploy/healthcheck.sh
