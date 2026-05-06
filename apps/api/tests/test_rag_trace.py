import pytest

from app.rag import service as rag_service
from app.rag.trace import metadata_coverage_from_records, preview_text


class FakeResult:
    def __init__(self, rows=None, scalar=0):
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class DemoDb:
    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM documents d" in sql and "JOIN knowledge_bases" in sql:
            return FakeResult([{
                "id": "doc-1",
                "title": "快充诊断手册",
                "filename": "manual.pdf",
                "status": "ready",
                "knowledge_base_id": "kb-1",
                "knowledge_base": "默认知识库",
            }])
        if "ILIKE" in sql:
            return FakeResult([_chunk_row(source_score=0.0)])
        if "ORDER BY c.created_at DESC" in sql:
            return FakeResult([_chunk_row(source_score=0.0)])
        return FakeResult()


class RetrieveDb:
    def execute(self, statement, params=None):
        sql = str(statement)
        if "COUNT(*) FROM chunks" in sql:
            return FakeResult(scalar=1)
        if "ORDER BY c.created_at DESC" in sql:
            return FakeResult([_chunk_row(source_score=0.0)])
        return FakeResult()


def _chunk_row(source_score):
    return {
        "id": "chunk-1",
        "document_id": "doc-1",
        "content": "BMS 快充握手失败，优先检查充电口、CC/CP、HVIL 与 BMS 冻结帧。",
        "metadata": {"chunk_index": 0, "system": ["BMS"], "dtc": ["P1A0C"], "keywords": ["BMS"]},
        "title": "快充诊断手册",
        "filename": "manual.pdf",
        "score": source_score,
        "vector_score": source_score,
    }


def test_trace_preview_and_metadata_coverage_are_bounded():
    assert preview_text("  A\n\nB  " * 200, limit=12) == "A B A B A B…"

    coverage = metadata_coverage_from_records([
        {"metadata": {"page": 1, "system": ["BMS"], "keywords": ["BMS"]}},
        {"metadata": {"dtc": ["P1A0C"], "keywords": ["P1A0C"]}},
    ])

    assert coverage["page"] == 1
    assert coverage["system"] == 1
    assert coverage["dtc"] == 1
    assert coverage["keywords"] == 2


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_recent_chunks_when_embedding_fails(monkeypatch):
    async def fail_embed(db, texts, config=None):
        raise RuntimeError("embedding offline")

    monkeypatch.setattr(rag_service, "embed_texts", fail_embed)

    hits = await rag_service.retrieve(RetrieveDb(), "没有领域词的问题", None, document_id="doc-1", use_rerank=False)

    assert hits[0]["id"] == "chunk-1"
    assert hits[0]["sources"] == ["recent"]


@pytest.mark.asyncio
async def test_document_rag_demo_marks_embedding_rerank_and_chat_fallbacks(monkeypatch):
    async def fail_embed(db, texts, config=None):
        raise RuntimeError("embedding offline")

    async def fail_rerank(db, query, passages, config=None):
        raise RuntimeError("rerank offline")

    async def fail_chat(db, task, messages):
        raise RuntimeError(f"{task} offline")

    monkeypatch.setattr(rag_service, "embed_texts", fail_embed)
    monkeypatch.setattr(rag_service, "rerank_texts", fail_rerank)
    monkeypatch.setattr(rag_service, "chat_for_task", fail_chat)
    monkeypatch.setattr(rag_service, "get_app_setting", lambda db, key, default="": "fallback")

    demo = await rag_service.run_document_rag_demo(DemoDb(), "doc-1", "BMS 快充失败怎么查？")

    assert demo["reranked_hits"][0]["id"] == "chunk-1"
    assert {item["stage"] for item in demo["fallbacks"]} >= {"embedding", "rerank", "answer", "fallback_chat"}
    assert demo["steps"][-1]["status"] == "fallback"
    assert demo["answer"]
