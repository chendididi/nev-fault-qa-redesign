#!/usr/bin/env bash
set -euo pipefail

TARGET=${1:-}
PROJECT_NAME=${PROJECT_NAME:-nev-fault-qa-redesign}
COMPOSE_FILES=${COMPOSE_FILES:-"-f docker-compose.yml -f docker-compose.cn.yml"}

if [ -z "$TARGET" ]; then
  echo "Usage: bash deploy/export-data.sh ./backup/nev-demo-\$(date +%Y%m%d)"
  exit 1
fi

cd "$(dirname "$0")/.."
mkdir -p "$TARGET"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

POSTGRES_USER=${POSTGRES_USER:-nev}
POSTGRES_DB=${POSTGRES_DB:-nev_fault_qa}

echo "Exporting Postgres database..."
docker compose -p "$PROJECT_NAME" $COMPOSE_FILES exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists > "$TARGET/postgres.sql"

echo "Exporting MinIO volume..."
docker run --rm \
  -v "${PROJECT_NAME}_minio-data:/data:ro" \
  -v "$(realpath "$TARGET"):/backup" \
  m.daocloud.io/docker.io/library/alpine:3.20 \
  tar -C /data -czf /backup/minio-data.tar.gz .

echo "Exporting uploads and local model cache..."
tar -czf "$TARGET/uploads.tar.gz" uploads 2>/dev/null || true
tar -czf "$TARGET/models.tar.gz" models 2>/dev/null || true

if [ -f .env ]; then
  sed -E 's/^([^=]*(KEY|TOKEN|SECRET|PASSWORD)[^=]*)=.*/\1=__SET_ON_SERVER__/I' .env > "$TARGET/env.redacted"
fi

cat > "$TARGET/manifest.txt" <<MANIFEST
project=$PROJECT_NAME
created_at=$(date -Iseconds)
postgres_dump=postgres.sql
minio_archive=minio-data.tar.gz
uploads_archive=uploads.tar.gz
models_archive=models.tar.gz
MANIFEST

echo "Export complete: $TARGET"
