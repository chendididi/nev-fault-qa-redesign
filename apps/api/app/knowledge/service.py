import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.knowledge.parser import chunk_text, extract_repair_metadata, extract_text
from app.knowledge.storage import ObjectStorage
from app.models.provider import OpenAICompatibleProvider, active_model_config, embed_texts, vector_literal


async def ingest_document(db: Session, document_id: str) -> None:
    storage = ObjectStorage()
    doc = db.execute(text("""
        SELECT id, knowledge_base_id, title, filename, content_type, object_key
        FROM documents WHERE id=:id
    """), {"id": document_id}).mappings().first()
    if not doc:
        return
    try:
        db.execute(text("UPDATE documents SET status='processing', updated_at=now() WHERE id=:id"), {"id": document_id})
        db.execute(text("UPDATE ingestion_jobs SET status='processing', updated_at=now() WHERE document_id=:id"), {"id": document_id})
        db.commit()

        data = storage.get(doc["object_key"])
        model_config = active_model_config(db)
        ocr_provider = OpenAICompatibleProvider(model_config)
        extracted = await extract_text(doc["filename"], doc["content_type"], data, ocr_provider)
        chunks = chunk_text(extracted)
        db.execute(text("DELETE FROM chunks WHERE document_id=:id"), {"id": document_id})
        if chunks:
            embeddings = await embed_texts(db, chunks, model_config)
            for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=False)):
                metadata = {
                    "title": doc["title"],
                    "filename": doc["filename"],
                    "chunk_index": index,
                    **extract_repair_metadata(content),
                }
                db.execute(text("""
                    INSERT INTO chunks (document_id, knowledge_base_id, content, metadata, embedding)
                    VALUES (:document_id, :knowledge_base_id, :content, cast(:metadata as jsonb), cast(:embedding as vector))
                """), {
                    "document_id": document_id,
                    "knowledge_base_id": doc["knowledge_base_id"],
                    "content": content,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                    "embedding": vector_literal(embedding),
                })
        db.execute(text("UPDATE documents SET status='ready', error=NULL, updated_at=now() WHERE id=:id"), {"id": document_id})
        db.execute(text("UPDATE ingestion_jobs SET status='done', error=NULL, updated_at=now() WHERE document_id=:id"), {"id": document_id})
        db.commit()
    except Exception as exc:
        db.rollback()
        db.execute(text("UPDATE documents SET status='failed', error=:error, updated_at=now() WHERE id=:id"), {"id": document_id, "error": str(exc)})
        db.execute(text("UPDATE ingestion_jobs SET status='failed', error=:error, updated_at=now() WHERE document_id=:id"), {"id": document_id, "error": str(exc)})
        db.commit()
