# NEV Fault QA Redesign

新能源汽车多模态 RAG 维修系统。系统面向维修技师和管理员，支持维修资料入库、向量检索、文本/图片问答、步骤化诊断回答和引用溯源。

## Tech Stack

- Web: Next.js, TypeScript, Tailwind CSS
- API: FastAPI, Python
- Database: PostgreSQL + pgvector
- Queue/Cache: Redis
- Object storage: MinIO/S3 compatible storage
- Deployment: Docker Compose
- Model interface: OpenAI-compatible chat/vision API plus local embedding/rerank models

## Quick Start

1. Copy env files:

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

2. Configure model settings in `.env`, or log in as admin and update them in the model settings page. The remote API is used for `gpt-5.5` chat, image understanding and OCR; embedding/rerank models are local.

3. Optionally pre-download local embedding/rerank models after installing API dependencies. If skipped, the API/worker downloads them lazily on first embedding/rerank use:

```bash
cd apps/api
pip install -r requirements.txt
cd ../..
python3 scripts/download_models.py
```

4. Start the stack:

```bash
docker compose up --build
# If your machine only has Compose v1:
docker-compose up --build
```

Recommended command for the current WSL/Docker environment, especially when Docker Hub or npm/PyPI is slow in China:

```bash
docker-compose -f docker-compose.yml -f docker-compose.cn.yml up -d --build
```

This project uses `WEB_PORT` from `.env`. The current local default is:

```env
WEB_PORT=3001
```

That avoids conflict with other services that may already use port `3000`.

Useful Docker commands:

```bash
# Check service status
docker-compose -f docker-compose.yml -f docker-compose.cn.yml ps

# Follow logs
docker-compose -f docker-compose.yml -f docker-compose.cn.yml logs -f api web worker

# Stop services without deleting database/object-storage volumes
docker-compose -f docker-compose.yml -f docker-compose.cn.yml down
```

If Compose v1 reports `ContainerConfig` while recreating old containers, remove only the app containers and start again:

```bash
docker-compose -f docker-compose.yml -f docker-compose.cn.yml rm -sf api worker web
docker-compose -f docker-compose.yml -f docker-compose.cn.yml up -d --build
```

5. Open:

- Web: http://localhost:3001
- Chat: http://localhost:3001/chat
- API docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001

Default accounts:

- Admin: `admin@example.com` / `Admin123!`
- Technician: `tech@example.com` / `Tech123!`

If port `3001` is also occupied, change `WEB_PORT` in `.env` and restart the stack.

## Local Development

API:

```bash
cd apps/api
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
LOCAL_MODEL_CACHE_DIR=../../models python ../../scripts/download_models.py
uvicorn app.main:app --reload
```

Web:

```bash
cd apps/web
npm install
npm run dev
```

## Scope

第一版支持文本、图片和文档，不包含视频、音频、复杂工单流和企业多租户。图片理解和 OCR 默认复用 `OPENAI_CHAT_MODEL`，embedding/rerank 使用本地下载模型。
