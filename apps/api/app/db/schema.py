from sqlalchemy import text
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def init_db(db: Session) -> None:
    settings = get_settings()
    db.execute(text("SELECT pg_advisory_lock(91024001)"))
    try:
        _init_db_locked(db, settings)
    except Exception:
        db.rollback()
        db.execute(text("SELECT pg_advisory_unlock(91024001)"))
        db.commit()
        raise
    else:
        db.execute(text("SELECT pg_advisory_unlock(91024001)"))
        db.commit()


def _init_db_locked(db: Session, settings) -> None:
    db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email text UNIQUE NOT NULL,
            name text NOT NULL,
            role text NOT NULL CHECK (role IN ('admin','technician')),
            password_hash text NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS model_configs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL DEFAULT 'default',
            provider text NOT NULL DEFAULT 'openai_compatible',
            base_url text NOT NULL,
            api_key text NOT NULL,
            chat_model text NOT NULL,
            embedding_model text NOT NULL,
            vision_model text,
            rerank_model text,
            embedding_dim integer NOT NULL DEFAULT 1024,
            is_active boolean NOT NULL DEFAULT true,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS model_endpoints (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            provider_type text NOT NULL DEFAULT 'remote_api',
            base_url text NOT NULL DEFAULT '',
            api_key text NOT NULL DEFAULT '',
            capabilities jsonb NOT NULL DEFAULT '[]'::jsonb,
            timeout_seconds integer NOT NULL DEFAULT 120,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS model_routes (
            task text PRIMARY KEY,
            endpoint_id uuid REFERENCES model_endpoints(id) ON DELETE SET NULL,
            model_name text NOT NULL DEFAULT '',
            temperature double precision NOT NULL DEFAULT 0.2,
            max_tokens integer,
            enabled boolean NOT NULL DEFAULT true,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (task IN ('chat','vision_ocr','embedding','rerank','fallback_chat'))
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key text PRIMARY KEY,
            value text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            description text NOT NULL DEFAULT '',
            created_by uuid REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            knowledge_base_id uuid REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            title text NOT NULL,
            filename text NOT NULL,
            content_type text NOT NULL,
            object_key text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            error text,
            created_by uuid REFERENCES users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS ingestion_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'pending',
            error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text(f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
            knowledge_base_id uuid REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            content text NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            embedding vector({settings.embedding_dim}),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    _ensure_chunk_vector_dim(db, settings.embedding_dim)
    db.execute(text("CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS chunks_kb_idx ON chunks (knowledge_base_id)"))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid REFERENCES users(id),
            title text NOT NULL DEFAULT '新的诊断会话',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id uuid REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role text NOT NULL CHECK (role IN ('user','assistant','system')),
            content text NOT NULL,
            image_object_key text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS retrieval_hits (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            message_id uuid REFERENCES chat_messages(id) ON DELETE CASCADE,
            chunk_id uuid REFERENCES chunks(id) ON DELETE SET NULL,
            score double precision NOT NULL,
            content text NOT NULL,
            citation jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS image_descriptions (
            sha256 text PRIMARY KEY,
            content_type text NOT NULL,
            object_key text,
            description text NOT NULL,
            provider text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid REFERENCES users(id),
            action text NOT NULL,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """))
    _seed(db, settings)
    _seed_model_routing(db, settings)


def _ensure_chunk_vector_dim(db: Session, embedding_dim: int) -> None:
    current_type = db.execute(text("""
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = 'chunks' AND a.attname = 'embedding'
    """)).scalar()
    expected_type = f"vector({embedding_dim})"
    if current_type == expected_type:
        return

    chunk_count = db.execute(text("SELECT COUNT(*) FROM chunks")).scalar_one()
    if chunk_count:
        raise RuntimeError(
            f"chunks.embedding 当前为 {current_type}，配置为 {expected_type}。"
            "请清空旧 chunks 并重新入库，或先迁移知识库索引。"
        )

    db.execute(text("DROP INDEX IF EXISTS chunks_embedding_idx"))
    db.execute(text(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({int(embedding_dim)})"))


def _seed(db: Session, settings) -> None:
    for email, name, role, password in [
        (settings.admin_email, "系统管理员", "admin", settings.admin_password),
        (settings.tech_email, "维修技师", "technician", settings.tech_password),
    ]:
        exists = db.execute(text("SELECT 1 FROM users WHERE email=:email"), {"email": email}).first()
        if not exists:
            db.execute(
                text("INSERT INTO users (email, name, role, password_hash) VALUES (:email,:name,:role,:password_hash)"),
                {"email": email, "name": name, "role": role, "password_hash": pwd_context.hash(password)},
            )
    exists = db.execute(text("SELECT 1 FROM knowledge_bases LIMIT 1")).first()
    if not exists:
        admin = db.execute(text("SELECT id FROM users WHERE email=:email"), {"email": settings.admin_email}).scalar_one()
        db.execute(
            text("INSERT INTO knowledge_bases (name, description, created_by) VALUES (:name,:description,:created_by)"),
            {"name": "默认维修知识库", "description": "新能源汽车维修手册、故障案例和诊断资料", "created_by": admin},
        )
    exists = db.execute(text("SELECT 1 FROM model_configs WHERE is_active=true LIMIT 1")).first()
    if not exists:
        db.execute(text("""
            INSERT INTO model_configs
            (base_url, api_key, chat_model, embedding_model, vision_model, rerank_model, embedding_dim)
            VALUES (:base_url, :api_key, :chat_model, :embedding_model, :vision_model, :rerank_model, :embedding_dim)
        """), {
            "base_url": settings.openai_base_url,
            "api_key": settings.openai_api_key,
            "chat_model": settings.openai_chat_model,
            "embedding_model": settings.local_embedding_model,
            "vision_model": settings.openai_vision_model,
            "rerank_model": settings.local_rerank_model,
            "embedding_dim": settings.embedding_dim,
        })


def _seed_model_routing(db: Session, settings) -> None:
    db.execute(text("""
        INSERT INTO app_settings (key, value)
        VALUES ('demo_mode', 'fallback')
        ON CONFLICT (key) DO NOTHING
    """))

    active_config = db.execute(text("""
        SELECT base_url, api_key, chat_model, embedding_model, vision_model, rerank_model, embedding_dim
        FROM model_configs
        WHERE is_active=true
        ORDER BY updated_at DESC
        LIMIT 1
    """)).mappings().first()

    remote_endpoint_id = db.execute(text("""
        SELECT id FROM model_endpoints
        WHERE provider_type IN ('remote_api','vllm','ollama','llama_cpp','lm_studio')
        ORDER BY created_at ASC
        LIMIT 1
    """)).scalar()
    if not remote_endpoint_id and active_config:
        remote_provider_type = "vllm" if "vllm" in active_config["base_url"] else "remote_api"
        remote_endpoint_id = db.execute(text("""
            INSERT INTO model_endpoints
            (name, provider_type, base_url, api_key, capabilities, timeout_seconds, is_active)
            VALUES ('默认 OpenAI-compatible', :provider_type, :base_url, :api_key, '["chat","vision"]'::jsonb, 120, true)
            RETURNING id
        """), {
            "base_url": active_config["base_url"],
            "api_key": active_config["api_key"],
            "provider_type": remote_provider_type,
        }).scalar_one()

    local_endpoint_id = db.execute(text("""
        SELECT id FROM model_endpoints WHERE provider_type='local' ORDER BY created_at ASC LIMIT 1
    """)).scalar()
    if not local_endpoint_id:
        local_endpoint_id = db.execute(text("""
            INSERT INTO model_endpoints
            (name, provider_type, base_url, api_key, capabilities, timeout_seconds, is_active)
            VALUES ('本地 BGE 检索模型', 'local', '', '', '["embedding","rerank"]'::jsonb, 120, true)
            RETURNING id
        """)).scalar_one()

    demo_endpoint_id = db.execute(text("""
        SELECT id FROM model_endpoints WHERE provider_type='demo_cache' ORDER BY created_at ASC LIMIT 1
    """)).scalar()
    if not demo_endpoint_id:
        demo_endpoint_id = db.execute(text("""
            INSERT INTO model_endpoints
            (name, provider_type, base_url, api_key, capabilities, timeout_seconds, is_active)
            VALUES ('Demo Cache 演示兜底', 'demo_cache', '', '', '["chat","vision"]'::jsonb, 5, true)
            RETURNING id
        """)).scalar_one()

    chat_model = (active_config or {}).get("chat_model") or settings.openai_chat_model
    vision_model = (active_config or {}).get("vision_model") or chat_model
    embedding_model = (active_config or {}).get("embedding_model") or settings.local_embedding_model
    rerank_model = (active_config or {}).get("rerank_model") or settings.local_rerank_model

    for task, endpoint_id, model_name in [
        ("chat", remote_endpoint_id, chat_model),
        ("vision_ocr", remote_endpoint_id, vision_model),
        ("embedding", local_endpoint_id, embedding_model),
        ("rerank", local_endpoint_id, rerank_model),
        ("fallback_chat", demo_endpoint_id, "demo-cache"),
    ]:
        db.execute(text("""
            INSERT INTO model_routes (task, endpoint_id, model_name, temperature, enabled)
            VALUES (:task, :endpoint_id, :model_name, 0.2, true)
            ON CONFLICT (task) DO NOTHING
        """), {"task": task, "endpoint_id": endpoint_id, "model_name": model_name or ""})
