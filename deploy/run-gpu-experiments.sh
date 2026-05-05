#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME=${PROJECT_NAME:-nev-fault-qa-redesign}
COMPOSE_FILES=${COMPOSE_FILES:-"-f docker-compose.yml -f docker-compose.cn.yml -f docker-compose.gpu.yml"}
OUTPUT_DIR_IN_CONTAINER=${OUTPUT_DIR_IN_CONTAINER:-/app/uploads/experiments/paper_gpu}
OUTPUT_DIR_ON_HOST=${OUTPUT_DIR_ON_HOST:-./uploads/experiments/paper_gpu}
RAW_DIR_IN_CONTAINER=${RAW_DIR_IN_CONTAINER:-/app/uploads/experiments/raw}

cd "$(dirname "$0")/.."

mkdir -p "${OUTPUT_DIR_ON_HOST}" ./uploads/experiments/raw

compose() {
  docker compose -p "$PROJECT_NAME" $COMPOSE_FILES "$@"
}

echo "Checking CUDA visibility inside api container..."
compose exec -T api python - <<'PY'
import torch
print("torch.cuda.is_available =", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available in api container")
print("cuda.device_count =", torch.cuda.device_count())
print("cuda.device_name =", torch.cuda.get_device_name(0))
PY

echo "Running retrieval ablation variants on GPU..."
compose exec -T api python evaluate_retrieval.py \
  --variant all \
  --out "${RAW_DIR_IN_CONTAINER}/retrieval_eval_all_gpu.csv" \
  --summary-out "${RAW_DIR_IN_CONTAINER}/retrieval_eval_all_gpu.json"

echo "Running hybrid+rerrank detailed pass on GPU..."
compose exec -T api python evaluate_retrieval.py \
  --variant hybrid_rerank \
  --out "${RAW_DIR_IN_CONTAINER}/retrieval_eval_hybrid_rerank_gpu.csv" \
  --summary-out "${RAW_DIR_IN_CONTAINER}/retrieval_eval_hybrid_rerank_gpu.json"

echo "Building paper figures and tables..."
compose exec -T api python experiments/paper_experiments.py \
  --ablation-csv "${RAW_DIR_IN_CONTAINER}/retrieval_eval_all_gpu.csv" \
  --eval-csv "${RAW_DIR_IN_CONTAINER}/retrieval_eval_hybrid_rerank_gpu.csv" \
  --out-dir "${OUTPUT_DIR_IN_CONTAINER}"

echo "Done."
echo "Raw metrics on host: ./uploads/experiments/raw"
echo "Paper artifacts on host: ${OUTPUT_DIR_ON_HOST}"
