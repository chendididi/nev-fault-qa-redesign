from __future__ import annotations

import argparse
import os
from pathlib import Path


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download local embedding and rerank models.")
    parser.add_argument("--source", default=os.getenv("LOCAL_MODEL_SOURCE", "modelscope"), choices=["modelscope", "huggingface", "local"])
    parser.add_argument("--cache-dir", default=os.getenv("LOCAL_MODEL_CACHE_DIR", "models"))
    parser.add_argument("--embedding-model", default=os.getenv("LOCAL_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL))
    parser.add_argument("--rerank-model", default=os.getenv("LOCAL_RERANK_MODEL", DEFAULT_RERANK_MODEL))
    return parser.parse_args()


def download_model(model_id: str, source: str, cache_dir: Path) -> str:
    model_path = Path(model_id).expanduser()
    if model_path.exists():
        return str(model_path)
    if source == "local":
        raise SystemExit(f"Local model path does not exist: {model_id}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    if source == "modelscope":
        from modelscope import snapshot_download

        return snapshot_download(
            model_id=model_id,
            cache_dir=str(cache_dir),
            ignore_patterns=["onnx/**", "imgs/**", "*.jpg", "*.webp"],
            max_workers=4,
        )
    from huggingface_hub import snapshot_download

    return snapshot_download(repo_id=model_id, cache_dir=str(cache_dir))


def main() -> None:
    args = parse_args()
    cache_dir = Path(args.cache_dir).expanduser()
    for label, model_id in [("embedding", args.embedding_model), ("rerank", args.rerank_model)]:
        path = download_model(model_id, args.source, cache_dir)
        print(f"{label}: {model_id} -> {path}")


if __name__ == "__main__":
    main()
