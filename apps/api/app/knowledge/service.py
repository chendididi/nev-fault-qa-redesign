import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.knowledge.parser import chunk_text, extract_repair_metadata, extract_text
from app.knowledge.storage import ObjectStorage
from app.models.provider import OpenAICompatibleProvider, active_model_config, embed_texts, vector_literal
from app.rag.trace import (
    elapsed_ms,
    finish_trace_event,
    metadata_coverage_from_records,
    now_timer,
    preview_text,
    record_trace_event,
    start_trace_event,
)


async def ingest_document(db: Session, document_id: str) -> None:
    storage = ObjectStorage()
    doc = db.execute(text("""
        SELECT id, knowledge_base_id, title, filename, content_type, object_key
        FROM documents WHERE id=:id
    """), {"id": document_id}).mappings().first()
    if not doc:
        return
    current_event_id = None
    current_started = 0.0
    try:
        db.execute(text("UPDATE documents SET status='processing', updated_at=now() WHERE id=:id"), {"id": document_id})
        db.execute(text("UPDATE ingestion_jobs SET status='processing', updated_at=now() WHERE document_id=:id"), {"id": document_id})
        db.commit()

        current_started = now_timer()
        current_event_id = start_trace_event(
            db,
            document_id,
            "extract_text_ocr",
            summary={"filename": doc["filename"], "content_type": doc["content_type"]},
        )
        db.commit()
        data = storage.get(doc["object_key"])
        model_config = active_model_config(db)
        ocr_provider = OpenAICompatibleProvider(model_config)
        extracted = await extract_text(doc["filename"], doc["content_type"], data, ocr_provider)
        finish_trace_event(
            db,
            current_event_id,
            "done",
            duration_ms=elapsed_ms(current_started),
            summary={"characters": len(extracted), "preview_chars": min(len(extracted), 420)},
            preview=extracted,
        )
        current_event_id = None
        db.commit()

        current_started = now_timer()
        current_event_id = start_trace_event(db, document_id, "chunk", summary={"chunk_size": 900, "overlap": 120})
        db.commit()
        chunks = chunk_text(extracted)
        if not chunks:
            raise RuntimeError("文档未抽取到可入库文本，无法生成 chunk")
        chunk_lengths = [len(chunk) for chunk in chunks]
        finish_trace_event(
            db,
            current_event_id,
            "done",
            duration_ms=elapsed_ms(current_started),
            summary={
                "chunk_count": len(chunks),
                "min_chars": min(chunk_lengths),
                "max_chars": max(chunk_lengths),
                "avg_chars": round(sum(chunk_lengths) / len(chunk_lengths), 1),
            },
            preview=chunks[0],
        )
        current_event_id = None
        db.commit()

        embeddings: list[list[float] | None] = [None] * len(chunks)
        current_started = now_timer()
        current_event_id = start_trace_event(db, document_id, "embedding", summary={"chunk_count": len(chunks)})
        db.commit()
        try:
            embedded = await embed_texts(db, chunks, model_config)
            for index, embedding in enumerate(embedded[:len(chunks)]):
                embeddings[index] = embedding
            vector_dim = len(embedded[0]) if embedded else 0
            finish_trace_event(
                db,
                current_event_id,
                "done",
                duration_ms=elapsed_ms(current_started),
                summary={"embedded_chunks": len([item for item in embeddings if item is not None]), "vector_dim": vector_dim},
            )
        except Exception as exc:
            db.rollback()
            finish_trace_event(
                db,
                current_event_id,
                "failed",
                duration_ms=elapsed_ms(current_started),
                summary={"embedded_chunks": 0, "fallback": "keyword_or_recent_chunks"},
                error=str(exc),
            )
        current_event_id = None
        db.commit()

        current_started = now_timer()
        current_event_id = start_trace_event(db, document_id, "index", summary={"target": "chunks + pgvector"})
        db.commit()
        db.execute(text("DELETE FROM chunks WHERE document_id=:id"), {"id": document_id})
        records = []
        for index, content in enumerate(chunks):
            metadata = {
                "title": doc["title"],
                "filename": doc["filename"],
                "chunk_index": index,
                **extract_repair_metadata(content),
            }
            embedding = embeddings[index] if index < len(embeddings) else None
            db.execute(text("""
                INSERT INTO chunks (document_id, knowledge_base_id, content, metadata, embedding)
                VALUES (:document_id, :knowledge_base_id, :content, cast(:metadata as jsonb), cast(:embedding as vector))
            """), {
                "document_id": document_id,
                "knowledge_base_id": doc["knowledge_base_id"],
                "content": content,
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "embedding": vector_literal(embedding) if embedding is not None else None,
            })
            records.append({"metadata": metadata, "has_embedding": embedding is not None})
        finish_trace_event(
            db,
            current_event_id,
            "done",
            duration_ms=elapsed_ms(current_started),
            summary={
                "inserted_chunks": len(records),
                "embedded_chunks": len([record for record in records if record["has_embedding"]]),
                "metadata_coverage": metadata_coverage_from_records(records),
            },
            preview=preview_text(chunks[0]),
        )
        current_event_id = None
        db.execute(text("UPDATE documents SET status='ready', error=NULL, updated_at=now() WHERE id=:id"), {"id": document_id})
        db.execute(text("UPDATE ingestion_jobs SET status='done', error=NULL, updated_at=now() WHERE document_id=:id"), {"id": document_id})
        record_trace_event(
            db,
            document_id,
            "ready",
            "done",
            summary={"chunk_count": len(records), "embedded_chunks": len([record for record in records if record["has_embedding"]])},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if current_event_id is not None:
            finish_trace_event(
                db,
                current_event_id,
                "failed",
                duration_ms=elapsed_ms(current_started) if current_started else None,
                error=str(exc),
            )
        record_trace_event(db, document_id, "failed", "failed", error=str(exc))
        db.execute(text("UPDATE documents SET status='failed', error=:error, updated_at=now() WHERE id=:id"), {"id": document_id, "error": str(exc)})
        db.execute(text("UPDATE ingestion_jobs SET status='failed', error=:error, updated_at=now() WHERE document_id=:id"), {"id": document_id, "error": str(exc)})
        db.commit()
