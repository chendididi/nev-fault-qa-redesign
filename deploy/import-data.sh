#!/usr/bin/env bash
set -euo pipefail

SOURCE=${1:-}
PROJECT_NAME=${PROJECT_NAME:-nev-fault-qa-redesign}
COMPOSE_FILES=${COMPOSE_FILES:-"-f docker-compose.yml -f docker-compose.cn.yml"}

if [ -z "$SOURCE" ]; then
  echo "Usage: bash deploy/import-data.sh ./nev-demo-backup"
  exit 1
fi

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

POSTGRES_USER=${POSTGRES_USER:-nev}
POSTGRES_DB=${POSTGRES_DB:-nev_fault_qa}

echo "Starting storage services..."
docker compose -p "$PROJECT_NAME" $COMPOSE_FILES up -d postgres redis minio

echo "Waiting for Postgres..."
for _ in $(seq 1 60); do
  if docker compose -p "$PROJECT_NAME" $COMPOSE_FILES exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if [ -f "$SOURCE/postgres.sql" ]; then
  echo "Restoring Postgres database..."
  docker compose -p "$PROJECT_NAME" $COMPOSE_FILES exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 < "$SOURCE/postgres.sql"
fi

if [ -f "$SOURCE/minio-data.tar.gz" ]; then
  echo "Restoring MinIO volume..."
  docker run --rm \
    -v "${PROJECT_NAME}_minio-data:/data" \
    -v "$(realpath "$SOURCE"):/backup:ro" \
    m.daocloud.io/docker.io/library/alpine:3.20 \
    sh -c "rm -rf /data/* && tar -C /data -xzf /backup/minio-data.tar.gz"
fi

[ -f "$SOURCE/uploads.tar.gz" ] && tar -xzf "$SOURCE/uploads.tar.gz"
[ -f "$SOURCE/models.tar.gz" ] && tar -xzf "$SOURCE/models.tar.gz"

echo "Import complete."
