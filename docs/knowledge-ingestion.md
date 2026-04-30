# 知识库入库说明

管理员可在“知识库管理”页面上传资料。支持：

- PDF
- Word `.docx`
- Markdown / TXT
- CSV
- Excel `.xlsx`
- 图片 `.png/.jpg/.jpeg/.webp/.bmp`

入库流程：

1. 文件保存到 MinIO，MinIO 不可用时降级保存到 `uploads/`。
2. 创建 `documents` 和 `ingestion_jobs` 记录。
3. worker 轮询 pending job。
4. 解析文本、调用 `gpt-5.5` 对图片和 PDF 空文本页做 OCR，然后切片。
5. 调用本地 embedding 模型。
6. 写入 `chunks` 表和 pgvector 向量索引，检索时再使用本地 rerank 模型精排。

Embedding 不再调用远程 `/v1/embeddings`，也不再静默使用 fallback embedding。若本地模型未下载、依赖未安装或向量维度与数据库不一致，入库任务会失败并在文档状态中显示错误信息。

默认模型：

- OCR / 图片理解：远程 `gpt-5.5`
- Embedding：本地 `BAAI/bge-m3`，维度 `1024`
- Rerank：本地 `BAAI/bge-reranker-v2-m3`
