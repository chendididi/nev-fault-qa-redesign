from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


API_ROOT = Path(__file__).resolve().parents[2]


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").exists():
            return parent
    return API_ROOT


REPO_ROOT = _repo_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(API_ROOT / ".env", REPO_ROOT / ".env"), extra="ignore")

    app_name: str = "NEV Fault QA"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    database_url: str = "postgresql://nev:nev_password@localhost:5432/nev_fault_qa"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    admin_email: str = "admin@example.com"
    admin_password: str = "Admin123!"
    tech_email: str = "tech@example.com"
    tech_password: str = "Tech123!"

    s3_endpoint: str = "http://localhost:9000"
    s3_public_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "nev-fault-qa"
    s3_region: str = "us-east-1"

    openai_base_url: str = "http://127.0.0.1:8317/v1"
    openai_api_key: str = "replace-with-your-api-key"
    openai_chat_model: str = "gpt-5.5"
    openai_vision_model: str | None = None

    local_model_source: str = "modelscope"
    local_model_cache_dir: str = "models"
    local_embedding_model: str = "BAAI/bge-m3"
    local_rerank_model: str = "BAAI/bge-reranker-v2-m3"
    local_device: str = "auto"
    embedding_dim: int = 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
