import hashlib
import json
from io import BytesIO
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.auth.security import create_access_token, get_current_user, hash_password, require_admin, verify_password
from app.core.config import get_settings
from app.db.schema import init_db
from app.db.session import get_db
from app.knowledge.service import ingest_document
from app.knowledge.storage import ObjectStorage
from app.models.provider import (
    ModelNotConfigured,
    OpenAICompatibleProvider,
    demo_image_description,
    describe_image_for_task,
    embed_texts,
    get_app_setting,
    list_model_topology,
    measure_check,
    model_config_for_task,
    rerank_texts,
    upsert_model_topology,
)
from app.rag.service import answer_question, run_document_rag_demo, stream_answer_chunks
from app.rag.trace import get_rag_trace_response, record_trace_event, reset_document_trace

settings = get_settings()
app = FastAPI(title="NEV Fault QA API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    db = next(get_db())
    try:
        init_db(db)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: dict, db: Session = Depends(get_db)) -> dict:
    user = db.execute(
        text("SELECT id,email,name,role,password_hash,is_active FROM users WHERE email=:email"),
        {"email": payload.get("email")},
    ).mappings().first()
    if not user or not user["is_active"] or not verify_password(payload.get("password", ""), user["password_hash"]):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    token = create_access_token(str(user["id"]), user["role"])
    return {"access_token": token, "token_type": "bearer", "user": {k: str(user[k]) for k in ["id", "email", "name", "role"]}}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"user": {**user, "id": str(user["id"])}}


@app.get("/api/admin/users")
def list_users(_: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(text("SELECT id,email,name,role,is_active,created_at FROM users ORDER BY created_at DESC")).mappings().all()
    return {"items": [serialize(row) for row in rows]}


@app.post("/api/admin/users")
def create_user(payload: dict, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    if payload.get("role") not in ("admin", "technician"):
        raise HTTPException(status_code=400, detail="角色必须是 admin 或 technician")
    row = db.execute(text("""
        INSERT INTO users (email, name, role, password_hash, is_active)
        VALUES (:email,:name,:role,:password_hash,true)
        RETURNING id,email,name,role,is_active,created_at
    """), {
        "email": payload["email"],
        "name": payload.get("name") or payload["email"],
        "role": payload["role"],
        "password_hash": hash_password(payload["password"]),
    }).mappings().one()
    db.commit()
    return serialize(row)


@app.patch("/api/admin/users/{user_id}")
def update_user(user_id: str, payload: dict, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    row = db.execute(text("""
        UPDATE users SET is_active=:is_active WHERE id=:id
        RETURNING id,email,name,role,is_active,created_at
    """), {"id": user_id, "is_active": bool(payload.get("is_active"))}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.commit()
    return serialize(row)


@app.get("/api/admin/model-config")
def get_model_config(_: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        return list_model_topology(db)
    except ModelNotConfigured:
        return {}


@app.put("/api/admin/model-config")
def upsert_model_config(payload: dict, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        return upsert_model_topology(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/model-config/test")
async def test_model_config(payload: dict | None = None, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    payload = payload or {}
    chat_config = resolve_test_config(db, payload, "chat")
    vision_config = resolve_test_config(db, payload, "vision_ocr")
    checks = []

    async def check_chat() -> str:
        provider = OpenAICompatibleProvider(chat_config)
        content = await provider.chat(
            [{"role": "user", "content": "用中文回复：模型连接正常。"}],
            model=chat_config.get("model"),
            temperature=0,
        )
        return content[:300]

    async def check_vision_ocr() -> str:
        provider = OpenAICompatibleProvider(vision_config)
        image = Image.new("RGB", (360, 120), "white")
        draw = ImageDraw.Draw(image)
        draw.text((20, 42), "NEV OCR 8317", fill="black")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        content = await provider.ocr_image(buffer.getvalue(), "image/png", context="连接测试图片")
        return content[:300]

    async def check_models() -> str:
        provider = OpenAICompatibleProvider(chat_config)
        try:
            models = await provider.list_models()
        except Exception as exc:
            return f"/models 不可用或未开放，已跳过模型列表检查：{exc}"
        if not models:
            return "端点可访问，但 /models 未返回模型列表"
        return "可用模型: " + ", ".join(models[:8])

    async def check_embedding() -> str:
        vectors = await embed_texts(db, ["新能源汽车故障诊断"])
        dim = len(vectors[0]) if vectors else 0
        expected = int(get_settings().embedding_dim)
        if dim != expected:
            raise RuntimeError(f"Embedding 维度不匹配：模型返回 {dim}，配置为 {expected}")
        return f"本地 embedding 正常，维度 {dim}"

    async def check_rerank() -> str:
        scores = await rerank_texts(db, "车辆无法快充", ["检查充电口和 BMS", "更换雨刮片"])
        return "本地 rerank 正常，分数 " + ", ".join(f"{score:.4f}" for score in scores)

    for name, fn in [
        ("models", check_models),
        ("chat", check_chat),
        ("vision_ocr", check_vision_ocr),
        ("embedding", check_embedding),
        ("rerank", check_rerank),
    ]:
        checks.append(await measure_check(name, fn))
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


@app.get("/api/knowledge-bases")
def list_kbs(db: Session = Depends(get_db), _: dict = Depends(get_current_user)) -> dict:
    rows = db.execute(text("SELECT id,name,description,created_at FROM knowledge_bases ORDER BY created_at DESC")).mappings().all()
    return {"items": [serialize(row) for row in rows]}


@app.post("/api/admin/knowledge-bases")
def create_kb(payload: dict, user: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    row = db.execute(text("""
        INSERT INTO knowledge_bases (name, description, created_by)
        VALUES (:name,:description,:created_by)
        RETURNING id,name,description,created_at
    """), {"name": payload["name"], "description": payload.get("description", ""), "created_by": user["id"]}).mappings().one()
    db.commit()
    return serialize(row)


@app.get("/api/admin/documents")
def list_documents(_: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(text("""
        SELECT d.id,d.title,d.filename,d.content_type,d.status,d.error,d.created_at,k.name AS knowledge_base
        FROM documents d JOIN knowledge_bases k ON k.id=d.knowledge_base_id
        ORDER BY d.created_at DESC
    """)).mappings().all()
    return {"items": [serialize(row) for row in rows]}


@app.post("/api/admin/documents")
async def upload_document(
    knowledge_base_id: str = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    data = await file.read()
    storage = ObjectStorage()
    key = storage.put(file.filename or "document", file.content_type or "application/octet-stream", data)
    row = db.execute(text("""
        INSERT INTO documents (knowledge_base_id,title,filename,content_type,object_key,created_by)
        VALUES (:knowledge_base_id,:title,:filename,:content_type,:object_key,:created_by)
        RETURNING id,title,filename,content_type,status,created_at
    """), {
        "knowledge_base_id": knowledge_base_id,
        "title": title,
        "filename": file.filename or "document",
        "content_type": file.content_type or "application/octet-stream",
        "object_key": key,
        "created_by": user["id"],
    }).mappings().one()
    job = db.execute(text("INSERT INTO ingestion_jobs (document_id) VALUES (:document_id) RETURNING id"), {"document_id": row["id"]}).mappings().one()
    record_trace_event(db, str(row["id"]), "upload_saved", "done", summary={
        "filename": file.filename or "document",
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": len(data),
    })
    record_trace_event(db, str(row["id"]), "queued", "done", summary={"job_id": str(job["id"])})
    db.commit()
    return serialize(row)


@app.get("/api/admin/documents/{document_id}/rag-trace")
def get_document_rag_trace(document_id: str, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    response = get_rag_trace_response(db, document_id)
    if not response:
        raise HTTPException(status_code=404, detail="文档不存在")
    return response


@app.post("/api/admin/documents/{document_id}/rag-demo")
async def document_rag_demo(document_id: str, payload: dict, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    question = str((payload or {}).get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    try:
        return await run_document_rag_demo(db, document_id, question)
    except ValueError as exc:
        if str(exc) == "document_not_found":
            raise HTTPException(status_code=404, detail="文档不存在") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/documents/{document_id}/reingest")
async def reingest_document(document_id: str, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    exists = db.execute(text("SELECT 1 FROM documents WHERE id=:id"), {"id": document_id}).first()
    if not exists:
        raise HTTPException(status_code=404, detail="文档不存在")
    reset_document_trace(db, document_id)
    record_trace_event(db, document_id, "upload_saved", "done", summary={"source": "existing_object", "reason": "reingest"})
    record_trace_event(db, document_id, "queued", "done", summary={"source": "manual_reingest"})
    db.execute(text("UPDATE ingestion_jobs SET status='pending', error=NULL, updated_at=now() WHERE document_id=:id"), {"id": document_id})
    db.execute(text("UPDATE documents SET status='pending', error=NULL, updated_at=now() WHERE id=:id"), {"id": document_id})
    db.commit()
    await ingest_document(db, document_id)
    return {"ok": True}


@app.delete("/api/admin/documents/{document_id}")
def delete_document(document_id: str, _: dict = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    db.execute(text("DELETE FROM documents WHERE id=:id"), {"id": document_id})
    db.commit()
    return {"ok": True}


@app.get("/api/chat/sessions")
def list_sessions(user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(text("""
        SELECT s.id,s.title,s.created_at,s.updated_at,
               COALESCE(stats.message_count, 0) AS message_count,
               last_msg.content AS last_message
        FROM chat_sessions s
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS message_count
            FROM chat_messages m
            WHERE m.session_id=s.id
        ) stats ON true
        LEFT JOIN LATERAL (
            SELECT content
            FROM chat_messages m
            WHERE m.session_id=s.id
            ORDER BY m.created_at DESC
            LIMIT 1
        ) last_msg ON true
        WHERE s.user_id=:user_id
        ORDER BY s.updated_at DESC
    """), {"user_id": user["id"]}).mappings().all()
    return {"items": [serialize(row) for row in rows]}


@app.post("/api/chat")
async def chat(
    question: str = Form(...),
    knowledge_base_id: str | None = Form(None),
    session_id: str | None = Form(None),
    image: UploadFile | None = File(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if not session_id:
        row = db.execute(text("""
            INSERT INTO chat_sessions (user_id,title) VALUES (:user_id,:title) RETURNING id
        """), {"user_id": user["id"], "title": question[:40] or "新的诊断会话"}).mappings().one()
        session_id = str(row["id"])
    else:
        ensure_session_access(db, session_id, user)

    history = load_session_context(db, session_id)

    image_key = None
    image_description = None
    if image:
        data = await image.read()
        image_key, image_description = await describe_and_cache_image(
            db,
            data,
            image.filename or "image",
            image.content_type or "application/octet-stream",
        )

    user_msg = db.execute(text("""
        INSERT INTO chat_messages (session_id,role,content,image_object_key)
        VALUES (:session_id,'user',:content,:image_key) RETURNING id
    """), {"session_id": session_id, "content": question, "image_key": image_key}).mappings().one()
    answer, hits = await answer_question(db, question, knowledge_base_id, image_description, history)
    assistant_msg = db.execute(text("""
        INSERT INTO chat_messages (session_id,role,content) VALUES (:session_id,'assistant',:content) RETURNING id
    """), {"session_id": session_id, "content": answer}).mappings().one()
    for hit in hits:
        db.execute(text("""
            INSERT INTO retrieval_hits (message_id,chunk_id,score,content,citation)
            VALUES (:message_id,:chunk_id,:score,:content,cast(:citation as jsonb))
        """), {
            "message_id": assistant_msg["id"],
            "chunk_id": hit["id"],
            "score": hit.get("rerank_score", hit["score"]),
            "content": hit["content"],
            "citation": json.dumps({
                "title": hit["title"],
                "filename": hit["filename"],
                "metadata": hit.get("metadata") or {},
                "vector_score": hit.get("vector_score", hit["score"]),
                "rerank_score": hit.get("rerank_score"),
                "keyword_matches": hit.get("keyword_matches", []),
                "retrieval_terms": hit.get("retrieval_terms", []),
                "sources": hit.get("sources", []),
            }, ensure_ascii=False),
        })
    db.execute(text("UPDATE chat_sessions SET updated_at=now() WHERE id=:id"), {"id": session_id})
    db.commit()
    return {
        "session_id": session_id,
        "question_message_id": str(user_msg["id"]),
        "answer": answer,
        "image_description": image_description,
        "citations": [serialize_hit(hit) for hit in hits],
    }


@app.post("/api/chat/stream")
async def chat_stream(
    question: str = Form(...),
    knowledge_base_id: str | None = Form(None),
    session_id: str | None = Form(None),
    image: UploadFile | None = File(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if not session_id:
        row = db.execute(text("""
            INSERT INTO chat_sessions (user_id,title) VALUES (:user_id,:title) RETURNING id
        """), {"user_id": user["id"], "title": question[:40] or "新的诊断会话"}).mappings().one()
        session_id = str(row["id"])
    else:
        ensure_session_access(db, session_id, user)

    history = load_session_context(db, session_id)
    image_key = None
    image_description = None
    if image:
        data = await image.read()
        image_key, image_description = await describe_and_cache_image(
            db,
            data,
            image.filename or "image",
            image.content_type or "application/octet-stream",
        )

    user_msg = db.execute(text("""
        INSERT INTO chat_messages (session_id,role,content,image_object_key)
        VALUES (:session_id,'user',:content,:image_key) RETURNING id
    """), {"session_id": session_id, "content": question, "image_key": image_key}).mappings().one()
    db.commit()

    async def event_stream():
        answer_parts: list[str] = []
        chunk_iter, hits = await stream_answer_chunks(db, question, knowledge_base_id, image_description, history)
        yield sse_event({"type": "start", "session_id": session_id, "question_message_id": str(user_msg["id"]), "image_description": image_description})
        async for chunk in chunk_iter:
            answer_parts.append(chunk)
            yield sse_event({"type": "delta", "content": chunk})
        answer = "".join(answer_parts)
        assistant_msg = db.execute(text("""
            INSERT INTO chat_messages (session_id,role,content) VALUES (:session_id,'assistant',:content) RETURNING id
        """), {"session_id": session_id, "content": answer}).mappings().one()
        store_retrieval_hits(db, assistant_msg["id"], hits)
        db.execute(text("UPDATE chat_sessions SET updated_at=now() WHERE id=:id"), {"id": session_id})
        db.commit()
        yield sse_event({"type": "done", "session_id": session_id, "answer": answer, "citations": [serialize_hit(hit) for hit in hits]})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/chat/sessions/{session_id}/messages")
def session_messages(session_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    ensure_session_access(db, session_id, user)
    rows = db.execute(text("""
        SELECT id,role,content,image_object_key,created_at FROM chat_messages
        WHERE session_id=:id ORDER BY created_at ASC
    """), {"id": session_id}).mappings().all()
    messages = [serialize(row) for row in rows]
    hits = db.execute(text("""
        SELECT h.message_id,h.chunk_id,h.score,h.content,h.citation
        FROM retrieval_hits h
        JOIN chat_messages m ON m.id=h.message_id
        WHERE m.session_id=:id
        ORDER BY h.created_at ASC
    """), {"id": session_id}).mappings().all()
    hits_by_message: dict[str, list[dict]] = {}
    for hit in hits:
        citation = hit["citation"] or {}
        message_id = str(hit["message_id"])
        hits_by_message.setdefault(message_id, []).append({
            "id": str(hit["chunk_id"] or hit["message_id"]),
            "score": hit["score"],
            "content": hit["content"],
            "title": citation.get("title", ""),
            "filename": citation.get("filename", ""),
            "metadata": citation.get("metadata", {}),
            "vector_score": citation.get("vector_score"),
            "rerank_score": citation.get("rerank_score"),
            "keyword_matches": citation.get("keyword_matches", []),
            "retrieval_terms": citation.get("retrieval_terms", []),
            "sources": citation.get("sources", []),
        })
    for message in messages:
        message["citations"] = hits_by_message.get(message["id"], [])
    return {"items": messages}


@app.delete("/api/chat/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    ensure_session_access(db, session_id, user)
    db.execute(text("DELETE FROM chat_sessions WHERE id=:id"), {"id": session_id})
    db.commit()
    return {"ok": True}


async def describe_and_cache_image(db: Session, data: bytes, filename: str, content_type: str) -> tuple[str, str]:
    image_key = ObjectStorage().put(filename, content_type, data)
    digest = hashlib.sha256(data).hexdigest()
    cached = db.execute(text("""
        SELECT description FROM image_descriptions WHERE sha256=:sha256
    """), {"sha256": digest}).mappings().first()
    if cached:
        return image_key, cached["description"]

    try:
        description = await describe_image_for_task(db, data, content_type, context="用户上传的新能源汽车维修相关图片")
    except Exception as exc:
        if get_app_setting(db, "demo_mode", "fallback") in ("fallback", "always"):
            description = f"{demo_image_description()}（真实视觉模型暂不可用：{exc}）"
        else:
            description = f"图片已保存，但视觉模型不可用：{exc}"
    db.execute(text("""
        INSERT INTO image_descriptions (sha256, content_type, object_key, description, provider)
        VALUES (:sha256, :content_type, :object_key, :description, :provider)
        ON CONFLICT (sha256) DO UPDATE SET object_key=excluded.object_key
    """), {
        "sha256": digest,
        "content_type": content_type,
        "object_key": image_key,
        "description": description,
        "provider": "vision_ocr",
    })
    return image_key, description


def store_retrieval_hits(db: Session, message_id, hits: list[dict]) -> None:
    for hit in hits:
        db.execute(text("""
            INSERT INTO retrieval_hits (message_id,chunk_id,score,content,citation)
            VALUES (:message_id,:chunk_id,:score,:content,cast(:citation as jsonb))
        """), {
            "message_id": message_id,
            "chunk_id": hit["id"],
            "score": hit.get("rerank_score", hit["score"]),
            "content": hit["content"],
            "citation": json.dumps({
                "title": hit["title"],
                "filename": hit["filename"],
                "metadata": hit.get("metadata") or {},
                "vector_score": hit.get("vector_score", hit["score"]),
                "rerank_score": hit.get("rerank_score"),
                "keyword_matches": hit.get("keyword_matches", []),
                "retrieval_terms": hit.get("retrieval_terms", []),
                "sources": hit.get("sources", []),
            }, ensure_ascii=False),
        })


def sse_event(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def resolve_test_config(db: Session, payload: dict, task: str) -> dict:
    if "base_url" in payload and "endpoints" not in payload:
        return legacy_payload_config(db, payload)

    route = None
    endpoint = payload.get("endpoint")
    if not endpoint and payload.get("endpoints") and payload.get("routes"):
        route = (payload.get("routes") or {}).get(task) or {}
        endpoint_id = route.get("endpoint_id")
        for item in payload.get("endpoints") or []:
            if item.get("id") == endpoint_id or item.get("client_id") == endpoint_id:
                endpoint = item
                break
    if endpoint:
        route = route or payload.get("route") or {}
        api_key = endpoint.get("api_key") or ""
        endpoint_id = endpoint.get("id")
        if endpoint_id and "..." in api_key:
            api_key = db.execute(text("SELECT api_key FROM model_endpoints WHERE id=:id"), {"id": endpoint_id}).scalar() or ""
        model_name = route.get("model_name") or payload.get("model_name") or endpoint.get("model_name") or ""
        return {
            "provider": endpoint.get("provider_type") or "remote_api",
            "provider_type": endpoint.get("provider_type") or "remote_api",
            "base_url": (endpoint.get("base_url") or "").rstrip("/"),
            "api_key": api_key,
            "model": model_name,
            "chat_model": model_name,
            "vision_model": model_name,
            "timeout_seconds": int(endpoint.get("timeout_seconds") or 120),
            "temperature": float(route.get("temperature", 0.2) if route.get("temperature") is not None else 0.2),
            "max_tokens": route.get("max_tokens"),
        }
    return model_config_for_task(db, task)


def legacy_payload_config(db: Session, payload: dict) -> dict:
    settings = get_settings()
    config = model_config_for_task(db, "chat")
    for key in ["base_url", "chat_model", "embedding_model", "vision_model", "rerank_model", "embedding_dim"]:
        if key in payload:
            value = payload[key]
            if key in ("vision_model", "rerank_model"):
                config[key] = value or None
            elif value not in (None, ""):
                config[key] = value
    api_key = payload.get("api_key")
    if api_key and "..." not in api_key:
        config["api_key"] = api_key
    config["model"] = config.get("chat_model") or config.get("model")
    config["embedding_model"] = config.get("embedding_model") or settings.local_embedding_model
    config["rerank_model"] = config.get("rerank_model") or settings.local_rerank_model
    config["embedding_dim"] = int(config.get("embedding_dim") or settings.embedding_dim)
    return config


def ensure_session_access(db: Session, session_id: str, user: dict) -> None:
    row = db.execute(text("SELECT user_id FROM chat_sessions WHERE id=:id"), {"id": session_id}).mappings().first()
    if not row or (str(row["user_id"]) != str(user["id"]) and user["role"] != "admin"):
        raise HTTPException(status_code=404, detail="会话不存在")


def load_session_context(db: Session, session_id: str, limit: int = 8) -> list[dict]:
    rows = db.execute(text("""
        SELECT role,content FROM (
            SELECT role,content,created_at
            FROM chat_messages
            WHERE session_id=:id AND role IN ('user','assistant')
            ORDER BY created_at DESC
            LIMIT :limit
        ) recent
        ORDER BY created_at ASC
    """), {"id": session_id, "limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def serialize(row) -> dict:
    return {key: str(value) if key == "id" or key.endswith("_id") else value for key, value in dict(row).items()}


def serialize_hit(hit: dict) -> dict:
    return {
        "id": str(hit["id"]),
        "score": hit.get("rerank_score", hit["score"]),
        "vector_score": hit.get("vector_score", hit["score"]),
        "rerank_score": hit.get("rerank_score"),
        "keyword_matches": hit.get("keyword_matches", []),
        "retrieval_terms": hit.get("retrieval_terms", []),
        "sources": hit.get("sources", []),
        "metadata": hit.get("metadata") or {},
        "content": hit["content"],
        "title": hit["title"],
        "filename": hit["filename"],
    }
