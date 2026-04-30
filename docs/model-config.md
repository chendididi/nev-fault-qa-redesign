# 模型配置

系统采用混合模型架构：OpenAI-compatible 接口负责对话、图片理解和 OCR，本地模型负责 embedding 和 rerank。

必填项：

- `base_url`：兼容接口地址。本地开发示例：`http://127.0.0.1:8317/v1`；Docker 示例：`http://host.docker.internal:8317/v1`。
- `api_key`：远程大模型 API key。
- `chat_model`：诊断问答模型，默认 `gpt-5.5`。
- `embedding_model`：本地向量化模型，默认 `BAAI/bge-m3`。
- `rerank_model`：本地精排模型，默认 `BAAI/bge-reranker-v2-m3`。
- `embedding_dim`：pgvector 列维度，`BAAI/bge-m3` 默认 `1024`。

可选项：

- `vision_model`：图片理解/OCR 模型。留空时复用 `chat_model`。
- `LOCAL_MODEL_SOURCE`：本地模型来源，默认 `modelscope`，也支持 `huggingface` 或 `local`。
- `LOCAL_MODEL_CACHE_DIR`：本地模型缓存目录，Docker 默认 `/app/models`。
- `LOCAL_DEVICE`：`auto`、`cpu` 或 `cuda`。

注意：如果修改 `embedding_dim`，需要新建数据库或迁移 `chunks.embedding` 列维度，并重建知识库索引。

下载默认本地模型：

```bash
python3 scripts/download_models.py
```
