import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Any
import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ModelNotConfigured(RuntimeError):
    pass


class LocalModelUnavailable(RuntimeError):
    pass


def active_model_config(db: Session) -> dict[str, Any]:
    row = db.execute(text("""
        SELECT id, provider, base_url, api_key, chat_model, embedding_model, vision_model, rerank_model, embedding_dim
        FROM model_configs WHERE is_active=true ORDER BY updated_at DESC LIMIT 1
    """)).mappings().first()
    if not row:
        raise ModelNotConfigured("未配置模型，请管理员先配置 OpenAI-compatible 模型接口")
    return dict(row)


class OpenAICompatibleProvider:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_url = config["base_url"].rstrip("/")
        self.headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}

    async def chat(self, messages: list[dict[str, Any]], *, model: str | None = None, temperature: float = 0.2) -> str:
        payload = {"model": model or self.config["chat_model"], "messages": messages, "temperature": temperature}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    async def vision_describe(self, prompt: str, image_bytes: bytes, content_type: str) -> str:
        model = self.config.get("vision_model") or self.config["chat_model"]
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_b64}"}},
            ],
        }]
        return await self.chat(messages, model=model)

    async def ocr_image(self, image_bytes: bytes, content_type: str, *, context: str = "") -> str:
        context_line = f"\n上下文: {context}" if context else ""
        prompt = f"""请作为 OCR 引擎识别图片中的所有可见文字，保持原文顺序，中文输出。
如果图片是新能源汽车维修资料、仪表盘、故障码截图或线路图，请同时保留关键标签、故障码、零部件名称和表格内容。
如果没有可识别文字，请回复“未识别到可见文字”。{context_line}"""
        return await self.vision_describe(prompt, image_bytes, content_type)


class LocalEmbeddingProvider:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.settings = get_settings()
        self.model_name = config.get("embedding_model") or self.settings.local_embedding_model
        self.device = _resolve_device(self.settings.local_device)
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise LocalModelUnavailable("缺少 FlagEmbedding 依赖，请先安装后端 requirements 并下载本地 embedding 模型") from exc
        model_path = resolve_local_model(self.model_name)
        use_fp16 = self.device != "cpu"
        try:
            self._model = BGEM3FlagModel(model_path, use_fp16=use_fp16, device=self.device)
        except TypeError:
            self._model = BGEM3FlagModel(model_path, use_fp16=use_fp16)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        output = model.encode(texts, batch_size=8, max_length=8192)
        dense = output["dense_vecs"] if isinstance(output, dict) else output
        vectors = [_to_float_list(item) for item in dense]
        expected_dim = int(self.config.get("embedding_dim") or self.settings.embedding_dim)
        for vector in vectors:
            if len(vector) != expected_dim:
                raise LocalModelUnavailable(f"Embedding 维度不匹配：模型返回 {len(vector)}，配置为 {expected_dim}")
        return vectors


class LocalRerankerProvider:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.settings = get_settings()
        self.model_name = config.get("rerank_model") or self.settings.local_rerank_model
        self.device = _resolve_device(self.settings.local_device)
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        if not self.model_name:
            raise LocalModelUnavailable("未配置本地 rerank 模型")
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise LocalModelUnavailable("缺少 FlagEmbedding 依赖，请先安装后端 requirements 并下载本地 rerank 模型") from exc
        model_path = resolve_local_model(self.model_name)
        use_fp16 = self.device != "cpu"
        self._model = FlagReranker(model_path, use_fp16=use_fp16)
        return self._model

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        model = self._load()
        scores = model.compute_score([[query, passage] for passage in passages], normalize=True)
        if isinstance(scores, int | float):
            return [float(scores)]
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        return [float(score) for score in scores]


_EMBEDDERS: dict[tuple[str, str, str], LocalEmbeddingProvider] = {}
_RERANKERS: dict[tuple[str, str, str], LocalRerankerProvider] = {}


def resolve_local_model(model_name: str) -> str:
    if not model_name:
        raise LocalModelUnavailable("本地模型名称不能为空")
    settings = get_settings()
    model_path = Path(model_name).expanduser()
    if model_path.exists():
        return str(model_path)

    cache_dir = Path(settings.local_model_cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_model_path = cache_dir / model_name
    if _is_complete_local_model(cached_model_path):
        return str(cached_model_path)

    source = settings.local_model_source.lower()
    if source == "modelscope":
        try:
            from modelscope import snapshot_download
        except ImportError as exc:
            raise LocalModelUnavailable("缺少 modelscope 依赖，无法从 ModelScope 下载本地模型") from exc
        return snapshot_download(model_id=model_name, cache_dir=str(cache_dir))
    if source == "huggingface":
        os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
        return model_name
    if source == "local":
        raise LocalModelUnavailable(f"本地模型路径不存在：{model_name}")
    raise LocalModelUnavailable(f"不支持的本地模型来源：{settings.local_model_source}")


async def embed_texts(db: Session, texts: list[str], config: dict[str, Any] | None = None) -> list[list[float]]:
    resolved = config or active_model_config(db)
    key = (
        resolved.get("embedding_model") or get_settings().local_embedding_model,
        get_settings().local_model_source,
        _resolve_device(get_settings().local_device),
    )
    provider = _EMBEDDERS.setdefault(key, LocalEmbeddingProvider(resolved))
    return await asyncio.to_thread(provider.embed, texts)


async def rerank_texts(db: Session, query: str, passages: list[str], config: dict[str, Any] | None = None) -> list[float]:
    resolved = config or active_model_config(db)
    key = (
        resolved.get("rerank_model") or get_settings().local_rerank_model,
        get_settings().local_model_source,
        _resolve_device(get_settings().local_device),
    )
    provider = _RERANKERS.setdefault(key, LocalRerankerProvider(resolved))
    return await asyncio.to_thread(provider.rerank, query, passages)


async def rerank_hits(db: Session, query: str, hits: list[dict], *, limit: int, config: dict[str, Any] | None = None) -> list[dict]:
    if not hits:
        return []
    try:
        scores = await rerank_texts(db, query, [hit["content"] for hit in hits], config)
    except Exception as exc:
        logger.warning("Local reranker unavailable, falling back to vector order: %s", exc)
        return hits[:limit]
    ranked = []
    for hit, score in zip(hits, scores, strict=False):
        enriched = dict(hit)
        enriched["rerank_score"] = score
        ranked.append(enriched)
    return sorted(ranked, key=lambda item: item["rerank_score"], reverse=True)[:limit]


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _resolve_device(value: str) -> str:
    if value != "auto":
        return value
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _is_complete_local_model(path: Path) -> bool:
    if not path.is_dir():
        return False
    has_config = (path / "config.json").exists()
    has_weights = any((path / filename).exists() for filename in ("pytorch_model.bin", "model.safetensors"))
    return has_config and has_weights


def _to_float_list(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]
