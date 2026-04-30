# 部署说明

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

本地 embedding/rerank 模型会在首次使用时下载到 `models/`。如需提前下载，先安装 API 依赖后运行：

```bash
cd apps/api
pip install -r requirements.txt
cd ../..
python3 scripts/download_models.py
```

如果本机只有 Compose v1：

```bash
docker-compose up --build
```

## Docker Hub 超时

如果出现：

```text
Get "https://registry-1.docker.io/v2/": context deadline exceeded
```

优先使用项目内置的国内镜像代理覆盖文件：

```bash
docker-compose -f docker-compose.yml -f docker-compose.cn.yml up --build
```

这个覆盖文件会把 Postgres/pgvector、Redis、MinIO、Python、Node 基础镜像改为 `m.daocloud.io/docker.io/...` 前缀。

如果仍然超时，再配置 Docker daemon 镜像加速。Linux/WSL Docker Engine 的配置文件通常是 `/etc/docker/daemon.json`：

```json
{
  "registry-mirrors": [
    "https://你的阿里云或腾讯云专属加速地址"
  ]
}
```

修改后重启 Docker：

```bash
sudo systemctl restart docker
docker info | grep -A5 "Registry Mirrors"
```

服务端口：

- Web: `http://localhost:3000`
- API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`
- Postgres: `localhost:5432`
- MinIO: `http://localhost:9001`

如果 `3000` 端口被占用，在 `.env` 中设置：

```env
WEB_PORT=3001
```

然后访问 `http://localhost:3001`。

## 默认账号

- 管理员：`admin@example.com` / `Admin123!`
- 技师：`tech@example.com` / `Tech123!`

生产部署前必须修改 `.env` 中的 `JWT_SECRET`、数据库密码、MinIO 密码和默认账号密码。

## 模型配置

远程 OpenAI-compatible 接口只负责 `gpt-5.5` 对话、图片理解和 OCR。Embedding/rerank 使用本地下载模型。

本地开发时：

```env
OPENAI_BASE_URL=http://127.0.0.1:8317/v1
OPENAI_CHAT_MODEL=gpt-5.5
LOCAL_MODEL_CACHE_DIR=../../models
```

Docker 内访问宿主机模型服务时：

```env
OPENAI_BASE_URL=http://host.docker.internal:8317/v1
LOCAL_MODEL_CACHE_DIR=/app/models
```

默认本地模型：

```env
LOCAL_MODEL_SOURCE=modelscope
LOCAL_EMBEDDING_MODEL=BAAI/bge-m3
LOCAL_RERANK_MODEL=BAAI/bge-reranker-v2-m3
EMBEDDING_DIM=1024
```

如果 `host.docker.internal:8317` 不通，确认 8317 服务监听 `0.0.0.0`，而不是只监听宿主机 loopback。
