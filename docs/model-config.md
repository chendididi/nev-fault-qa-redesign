# 模型配置

系统现在采用“端点 + 路由”的模型架构：端点负责连接 vLLM、Ollama、llama.cpp、LM Studio 或第三方 OpenAI-compatible API；路由负责决定聊天、图片理解、embedding、rerank 和 fallback 各用哪个模型。

## 推荐演示配置

学校单张 4090 服务器推荐跑 vLLM：

```env
VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
VLLM_SERVED_MODEL_NAME=qwen-vl-demo
VLLM_PORT=8008
VLLM_API_KEY=change-me-vllm-key
```

应用后台配置：

- 端点类型：`vllm`
- Base URL：`http://学校服务器IP:8008/v1`
- API Key：与 `VLLM_API_KEY` 一致
- 主聊天路由：`qwen-vl-demo`
- 图片理解/OCR 路由：`qwen-vl-demo`
- Fallback 路由：`Demo Cache` 或第三方远端 API

## 端点类型

- `remote_api`：第三方 OpenAI-compatible API。
- `vllm`：学校 GPU 或云 GPU 上的 vLLM OpenAI server。
- `ollama`：本机轻量模型服务，API Key 可留空。
- `llama_cpp`：GGUF/边缘部署，API Key 可留空。
- `lm_studio`：本地桌面模型服务。
- `local`：当前 API 容器内的 BGE embedding/rerank。
- `demo_cache`：预置演示兜底，不依赖真实模型。

## Demo Mode

- `真实模型优先，失败后 Demo Cache`：推荐演示默认值。
- `只使用真实模型`：用于验收真实推理能力。
- `始终使用 Demo Cache`：用于无 GPU、无外网或答辩前端展示。

Demo Cache 会明确在回答里标记“演示模式结果”，避免和真实维修推理混淆。

## 本地检索模型

默认仍使用：

```env
LOCAL_MODEL_SOURCE=modelscope
LOCAL_EMBEDDING_MODEL=BAAI/bge-m3
LOCAL_RERANK_MODEL=BAAI/bge-reranker-v2-m3
EMBEDDING_DIM=1024
```

如果修改 `EMBEDDING_DIM`，需要清空或迁移 `chunks.embedding` 并重建知识库索引。
