import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ROUTE_TASKS = ("chat", "vision_ocr", "embedding", "rerank", "fallback_chat")
ENDPOINT_TYPES = ("remote_api", "vllm", "ollama", "llama_cpp", "lm_studio", "demo_cache", "local")
DEMO_MODE_VALUES = ("real", "fallback", "always")


class ModelNotConfigured(RuntimeError):
    pass


class LocalModelUnavailable(RuntimeError):
    pass


def active_model_config(db: Session) -> dict[str, Any]:
    """Backward-compatible active chat config for older code/tests."""
    try:
        return model_config_for_task(db, "chat")
    except Exception:
        row = db.execute(text("""
            SELECT id, provider, base_url, api_key, chat_model, embedding_model, vision_model, rerank_model, embedding_dim
            FROM model_configs WHERE is_active=true ORDER BY updated_at DESC LIMIT 1
        """)).mappings().first()
        if not row:
            raise ModelNotConfigured("未配置模型，请管理员先配置模型接口")
        return dict(row)


def get_app_setting(db: Session, key: str, default: str = "") -> str:
    if not _table_exists(db, "app_settings"):
        return default
    value = db.execute(text("SELECT value FROM app_settings WHERE key=:key"), {"key": key}).scalar()
    return str(value) if value is not None else default


def set_app_setting(db: Session, key: str, value: str) -> None:
    db.execute(text("""
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (:key, :value, now())
        ON CONFLICT (key) DO UPDATE SET value=excluded.value, updated_at=now()
    """), {"key": key, "value": value})


def model_config_for_task(db: Session, task: str) -> dict[str, Any]:
    if task not in ROUTE_TASKS:
        raise ModelNotConfigured(f"未知模型任务：{task}")
    if _table_exists(db, "model_routes") and _table_exists(db, "model_endpoints"):
        row = db.execute(text("""
            SELECT
                r.task, r.model_name, r.temperature, r.max_tokens, r.enabled AS route_enabled,
                e.id AS endpoint_id, e.name AS endpoint_name, e.provider_type,
                e.base_url, e.api_key, e.capabilities, e.timeout_seconds, e.is_active
            FROM model_routes r
            LEFT JOIN model_endpoints e ON e.id = r.endpoint_id
            WHERE r.task=:task
        """), {"task": task}).mappings().first()
        if row and row["route_enabled"]:
            config = dict(row)
            config["provider"] = config.get("provider_type") or "local"
            config["model"] = config.get("model_name") or ""
            _add_legacy_model_fields(db, config)
            if config["provider"] == "local":
                return config
            if config["provider"] == "demo_cache":
                return config
            if config.get("is_active") and config.get("base_url"):
                return config
    if task != "chat":
        try:
            return model_config_for_task(db, "chat")
        except ModelNotConfigured:
            pass
    row = db.execute(text("""
        SELECT id, provider, base_url, api_key, chat_model, embedding_model, vision_model, rerank_model, embedding_dim
        FROM model_configs WHERE is_active=true ORDER BY updated_at DESC LIMIT 1
    """)).mappings().first()
    if not row:
        raise ModelNotConfigured("未配置模型，请管理员先配置模型接口")
    return dict(row)


def list_model_topology(db: Session) -> dict[str, Any]:
    endpoints = []
    routes: dict[str, Any] = {}
    if _table_exists(db, "model_endpoints"):
        rows = db.execute(text("""
            SELECT id,name,provider_type,base_url,api_key,capabilities,timeout_seconds,is_active,updated_at
            FROM model_endpoints ORDER BY created_at ASC, name ASC
        """)).mappings().all()
        endpoints = [_serialize_endpoint(row, mask=True) for row in rows]
    if _table_exists(db, "model_routes"):
        rows = db.execute(text("""
            SELECT task, endpoint_id, model_name, temperature, max_tokens, enabled, updated_at
            FROM model_routes ORDER BY task ASC
        """)).mappings().all()
        routes = {row["task"]: _serialize_route(row) for row in rows}
    return {
        "demo_mode": get_app_setting(db, "demo_mode", "fallback"),
        "endpoints": endpoints,
        "routes": routes,
    }


def upsert_model_topology(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    if "base_url" in payload and "endpoints" not in payload:
        return _upsert_legacy_model_config(db, payload)

    demo_mode = payload.get("demo_mode", "fallback")
    if demo_mode not in DEMO_MODE_VALUES:
        raise ValueError("demo_mode 必须是 real、fallback 或 always")
    set_app_setting(db, "demo_mode", demo_mode)

    id_map: dict[str, str] = {}
    for endpoint in payload.get("endpoints", []):
        endpoint_id = endpoint.get("id") or None
        provider_type = endpoint.get("provider_type") or "remote_api"
        if provider_type not in ENDPOINT_TYPES:
            raise ValueError(f"不支持的端点类型：{provider_type}")
        capabilities = endpoint.get("capabilities") or []
        if isinstance(capabilities, str):
            capabilities = [item.strip() for item in capabilities.split(",") if item.strip()]
        api_key = endpoint.get("api_key") or ""
        if endpoint_id and "..." in api_key:
            existing_key = db.execute(
                text("SELECT api_key FROM model_endpoints WHERE id=:id"),
                {"id": endpoint_id},
            ).scalar()
            api_key = existing_key or ""
        params = {
            "id": endpoint_id,
            "name": endpoint.get("name") or provider_type,
            "provider_type": provider_type,
            "base_url": (endpoint.get("base_url") or "").rstrip("/"),
            "api_key": api_key,
            "capabilities": json.dumps(capabilities, ensure_ascii=False),
            "timeout_seconds": int(endpoint.get("timeout_seconds") or 120),
            "is_active": bool(endpoint.get("is_active", True)),
        }
        if endpoint_id:
            row = db.execute(text("""
                UPDATE model_endpoints
                SET name=:name, provider_type=:provider_type, base_url=:base_url, api_key=:api_key,
                    capabilities=cast(:capabilities as jsonb), timeout_seconds=:timeout_seconds,
                    is_active=:is_active, updated_at=now()
                WHERE id=:id
                RETURNING id
            """), params).mappings().first()
            if not row:
                row = _insert_endpoint(db, params)
        else:
            row = _insert_endpoint(db, params)
        if endpoint.get("client_id"):
            id_map[str(endpoint["client_id"])] = str(row["id"])
        if endpoint_id:
            id_map[str(endpoint_id)] = str(row["id"])

    for task, route in (payload.get("routes") or {}).items():
        if task not in ROUTE_TASKS:
            continue
        endpoint_id = route.get("endpoint_id") or None
        endpoint_id = id_map.get(str(endpoint_id), endpoint_id) if endpoint_id else None
        db.execute(text("""
            INSERT INTO model_routes (task, endpoint_id, model_name, temperature, max_tokens, enabled, updated_at)
            VALUES (:task, :endpoint_id, :model_name, :temperature, :max_tokens, :enabled, now())
            ON CONFLICT (task) DO UPDATE SET
                endpoint_id=excluded.endpoint_id,
                model_name=excluded.model_name,
                temperature=excluded.temperature,
                max_tokens=excluded.max_tokens,
                enabled=excluded.enabled,
                updated_at=now()
        """), {
            "task": task,
            "endpoint_id": endpoint_id,
            "model_name": route.get("model_name") or "",
            "temperature": float(route.get("temperature", 0.2) if route.get("temperature") is not None else 0.2),
            "max_tokens": int(route["max_tokens"]) if route.get("max_tokens") not in (None, "") else None,
            "enabled": bool(route.get("enabled", True)),
        })
    db.commit()
    return list_model_topology(db)


def _insert_endpoint(db: Session, params: dict[str, Any]):
    return db.execute(text("""
        INSERT INTO model_endpoints
        (name, provider_type, base_url, api_key, capabilities, timeout_seconds, is_active)
        VALUES (:name, :provider_type, :base_url, :api_key, cast(:capabilities as jsonb), :timeout_seconds, :is_active)
        RETURNING id
    """), params).mappings().one()


def _upsert_legacy_model_config(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    try:
        existing = active_model_config(db)
    except ModelNotConfigured:
        existing = {}
    api_key = payload.get("api_key") or existing.get("api_key") or ""
    if not api_key:
        raise ValueError("API Key 不能为空")
    db.execute(text("UPDATE model_configs SET is_active=false"))
    row = db.execute(text("""
        INSERT INTO model_configs
        (provider, base_url, api_key, chat_model, embedding_model, vision_model, rerank_model, embedding_dim, is_active)
        VALUES ('openai_compatible', :base_url, :api_key, :chat_model, :embedding_model, :vision_model, :rerank_model, :embedding_dim, true)
        RETURNING id,provider,base_url,api_key,chat_model,embedding_model,vision_model,rerank_model,embedding_dim,is_active,updated_at
    """), {
        "base_url": payload["base_url"],
        "api_key": api_key,
        "chat_model": payload["chat_model"],
        "embedding_model": payload.get("embedding_model") or settings.local_embedding_model,
        "vision_model": payload.get("vision_model") or None,
        "rerank_model": payload.get("rerank_model") or settings.local_rerank_model,
        "embedding_dim": int(payload.get("embedding_dim") or settings.embedding_dim),
    }).mappings().one()
    _sync_legacy_config_to_routes(db, dict(row))
    db.commit()
    result = dict(row)
    result["api_key"] = mask_key(result["api_key"])
    return result


def _sync_legacy_config_to_routes(db: Session, config: dict[str, Any]) -> None:
    if not (_table_exists(db, "model_endpoints") and _table_exists(db, "model_routes")):
        return
    endpoint = db.execute(text("""
        INSERT INTO model_endpoints
        (name, provider_type, base_url, api_key, capabilities, timeout_seconds, is_active)
        VALUES ('默认 OpenAI-compatible', 'remote_api', :base_url, :api_key, '["chat","vision"]'::jsonb, 120, true)
        RETURNING id
    """), {"base_url": config["base_url"], "api_key": config["api_key"]}).mappings().one()
    endpoint_id = endpoint["id"]
    for task, model_name in {
        "chat": config.get("chat_model"),
        "vision_ocr": config.get("vision_model") or config.get("chat_model"),
        "fallback_chat": config.get("chat_model"),
    }.items():
        db.execute(text("""
            INSERT INTO model_routes (task, endpoint_id, model_name, temperature, enabled)
            VALUES (:task, :endpoint_id, :model_name, 0.2, true)
            ON CONFLICT (task) DO UPDATE SET endpoint_id=excluded.endpoint_id, model_name=excluded.model_name, updated_at=now()
        """), {"task": task, "endpoint_id": endpoint_id, "model_name": model_name or ""})


def _serialize_endpoint(row: Any, *, mask: bool) -> dict[str, Any]:
    item = dict(row)
    item["id"] = str(item["id"])
    item["api_key"] = mask_key(item.get("api_key") or "") if mask else item.get("api_key") or ""
    capabilities = item.get("capabilities") or []
    if isinstance(capabilities, str):
        try:
            capabilities = json.loads(capabilities)
        except json.JSONDecodeError:
            capabilities = []
    item["capabilities"] = capabilities
    return item


def _serialize_route(row: Any) -> dict[str, Any]:
    item = dict(row)
    if item.get("endpoint_id") is not None:
        item["endpoint_id"] = str(item["endpoint_id"])
    return item


class OpenAICompatibleProvider:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.provider = config.get("provider_type") or config.get("provider") or "remote_api"
        self.base_url = (config.get("base_url") or "").rstrip("/")
        self.timeout = float(config.get("timeout_seconds") or 120)
        self.headers = {"Content-Type": "application/json"}
        api_key = config.get("api_key") or ""
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    async def list_models(self) -> list[str]:
        if self.provider in ("demo_cache", "local"):
            return [self.config.get("model") or self.config.get("model_name") or self.provider]
        async with httpx.AsyncClient(timeout=min(self.timeout, 30)) as client:
            response = await client.get(f"{self.base_url}/models", headers=self.headers)
            response.raise_for_status()
            data = response.json()
        return [item.get("id", "") for item in data.get("data", []) if item.get("id")]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if self.provider == "demo_cache":
            return demo_answer(_last_user_text(messages), [], None)
        payload: dict[str, Any] = {
            "model": model or self.config.get("model") or self.config.get("chat_model"),
            "messages": messages,
            "temperature": temperature if temperature is not None else float(self.config.get("temperature") or 0.2),
        }
        resolved_max_tokens = max_tokens if max_tokens is not None else self.config.get("max_tokens")
        if resolved_max_tokens:
            payload["max_tokens"] = int(resolved_max_tokens)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        if self.provider == "demo_cache":
            content = demo_answer(_last_user_text(messages), [], None)
            for index in range(0, len(content), 16):
                await asyncio.sleep(0.01)
                yield content[index:index + 16]
            return
        payload: dict[str, Any] = {
            "model": model or self.config.get("model") or self.config.get("chat_model"),
            "messages": messages,
            "temperature": temperature if temperature is not None else float(self.config.get("temperature") or 0.2),
            "stream": True,
        }
        resolved_max_tokens = max_tokens if max_tokens is not None else self.config.get("max_tokens")
        if resolved_max_tokens:
            payload["max_tokens"] = int(resolved_max_tokens)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", headers=self.headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

    async def vision_describe(self, prompt: str, image_bytes: bytes, content_type: str) -> str:
        model = self.config.get("model") or self.config.get("vision_model") or self.config.get("chat_model")
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


async def chat_for_task(db: Session, task: str, messages: list[dict[str, Any]]) -> str:
    config = model_config_for_task(db, task)
    provider = OpenAICompatibleProvider(config)
    return await provider.chat(
        messages,
        model=config.get("model"),
        temperature=config.get("temperature"),
        max_tokens=config.get("max_tokens"),
    )


async def stream_for_task(db: Session, task: str, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
    config = model_config_for_task(db, task)
    provider = OpenAICompatibleProvider(config)
    async for chunk in provider.chat_stream(
        messages,
        model=config.get("model"),
        temperature=config.get("temperature"),
        max_tokens=config.get("max_tokens"),
    ):
        yield chunk


async def describe_image_for_task(db: Session, image_bytes: bytes, content_type: str, *, context: str = "") -> str:
    config = model_config_for_task(db, "vision_ocr")
    provider = OpenAICompatibleProvider(config)
    return await provider.ocr_image(image_bytes, content_type, context=context)


def demo_answer(question: str, hits: list[dict], image_description: str | None = None) -> str:
    normalized = question.lower()
    if any(term in normalized for term in ("bms", "p1a", "电池", "soc")):
        topic = "BMS 与高压电池系统"
        cause = "BMS 采样异常、快充握手失败、单体压差过大或高压互锁状态异常。"
        step = "读取 BMS 故障码和冻结帧，核对单体电压/温度/SOC，再检查高压连接器和快充通信。"
    elif any(term in normalized for term in ("绝缘", "hvil", "互锁", "高压")):
        topic = "HVIL 与绝缘故障"
        cause = "高压连接器未完全锁止、维修开关接触异常、线束进水或绝缘电阻低。"
        step = "先下电并验电，检查 HVIL 回路连续性，再用绝缘表按维修手册分段定位。"
    elif any(term in normalized for term in ("仪表", "报警", "图片", "故障灯")):
        topic = "仪表报警与图片诊断"
        cause = "仪表报警通常来自 BMS、VCU、OBC 或热管理控制器上报的联动故障。"
        step = "结合图片中文字、故障灯和诊断仪 DTC，不要仅凭单个报警直接更换部件。"
    else:
        topic = "快充/慢充系统"
        cause = "充电口温度或电子锁异常、CC/CP 信号异常、OBC/快充通信失败、BMS 禁止充电。"
        step = "确认充电桩和车辆端口状态，读取 BMS/OBC/VCU 故障码，检查低压供电、电子锁、CC/CP 与高压互锁。"
    citation_lines = []
    for index, hit in enumerate(hits[:4]):
        citation_lines.append(f"[{index + 1}] {hit.get('title', '演示资料')} / {hit.get('filename', 'demo')}")
    if not citation_lines:
        citation_lines = [f"[1] Demo Cache / {topic} 预置演示案例"]
    image_line = f"\n图片理解结果：{image_description}" if image_description else ""
    return f"""【演示模式结果】当前回答来自预置 Demo Cache 或模型失败兜底，用于保障演示流程不中断。

1. 可能原因
{cause}{image_line}

2. 检查步骤
{step}
建议按“低压供电 -> 通信状态 -> 高压互锁/绝缘 -> 目标控制器数据流 -> 部件确认”的顺序排查。

3. 安全提醒
涉及高压系统时必须执行下电、验电、放电等待和个人防护，禁止带电插拔高压连接器。

4. 维修建议
优先用诊断仪读取 DTC、冻结帧和实时数据流；只有当测量值与资料引用一致时再更换部件。

5. 引用来源
{chr(10).join(citation_lines)}

6. 置信提示
中。该回答用于演示系统流程，正式维修应以实时诊断数据和厂家手册为准。"""


def demo_image_description() -> str:
    return "演示图片识别：疑似仪表或维修资料截图，请结合 DTC、报警文字和高压安全状态继续诊断。"


class LocalEmbeddingProvider:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.settings = get_settings()
        self.model_name = config.get("embedding_model") or config.get("model") or config.get("model_name") or self.settings.local_embedding_model
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
        self.model_name = config.get("rerank_model") or config.get("model") or config.get("model_name") or self.settings.local_rerank_model
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
    resolved = config or model_config_for_task(db, "embedding")
    key = (
        resolved.get("embedding_model") or resolved.get("model") or get_settings().local_embedding_model,
        get_settings().local_model_source,
        _resolve_device(get_settings().local_device),
    )
    provider = _EMBEDDERS.setdefault(key, LocalEmbeddingProvider(resolved))
    return await asyncio.to_thread(provider.embed, texts)


async def rerank_texts(db: Session, query: str, passages: list[str], config: dict[str, Any] | None = None) -> list[float]:
    resolved = config or model_config_for_task(db, "rerank")
    key = (
        resolved.get("rerank_model") or resolved.get("model") or get_settings().local_rerank_model,
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


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "********"
    return value[:4] + "..." + value[-4:]


async def measure_check(name: str, fn) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        message = await fn()
        return {"name": name, "ok": True, "message": str(message), "duration_ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:
        return {"name": name, "ok": False, "message": str(exc), "duration_ms": round((time.perf_counter() - started) * 1000)}


def _add_legacy_model_fields(db: Session, config: dict[str, Any]) -> None:
    settings = get_settings()
    config.setdefault("chat_model", config.get("model_name") or config.get("model") or settings.openai_chat_model)
    config.setdefault("vision_model", config.get("model_name") or config.get("model") or settings.openai_vision_model)
    config.setdefault("embedding_model", settings.local_embedding_model)
    config.setdefault("rerank_model", settings.local_rerank_model)
    config.setdefault("embedding_dim", settings.embedding_dim)
    try:
        embedding_route = db.execute(text("SELECT model_name FROM model_routes WHERE task='embedding'")).scalar()
        rerank_route = db.execute(text("SELECT model_name FROM model_routes WHERE task='rerank'")).scalar()
        if embedding_route:
            config["embedding_model"] = embedding_route
        if rerank_route:
            config["rerank_model"] = rerank_route
    except Exception:
        pass


def _table_exists(db: Session, name: str) -> bool:
    return bool(db.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar())


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


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(item.get("text", "")) for item in content if item.get("type") == "text")
    return "新能源汽车维修诊断演示"
