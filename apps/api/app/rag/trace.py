import json
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


TRACE_STEP_LABELS = {
    "upload_saved": "文件已保存",
    "queued": "入库任务排队",
    "extract_text_ocr": "文本抽取/OCR",
    "chunk": "文本切片",
    "embedding": "向量化",
    "index": "写入索引",
    "ready": "入库完成",
    "failed": "入库失败",
}

TRACE_PREVIEW_CHARS = 420
CHUNK_PREVIEW_CHARS = 360
METADATA_KEYS = ("page", "heading", "system", "dtc", "vehicle_model", "keywords")


def now_timer() -> float:
    return time.perf_counter()


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def preview_text(value: str | None, *, limit: int = TRACE_PREVIEW_CHARS) -> str:
    if not value:
        return ""
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def reset_document_trace(db: Session, document_id: str) -> None:
    db.execute(text("DELETE FROM document_rag_trace_events WHERE document_id=:document_id"), {"document_id": document_id})


def record_trace_event(
    db: Session,
    document_id: str,
    step: str,
    status: str,
    *,
    duration_ms: int | None = None,
    summary: dict[str, Any] | None = None,
    preview: str | None = None,
    error: str | None = None,
):
    row = db.execute(text("""
        INSERT INTO document_rag_trace_events
        (document_id, step, status, duration_ms, summary, preview, error)
        VALUES (:document_id, :step, :status, :duration_ms, cast(:summary as jsonb), :preview, :error)
        RETURNING id
    """), {
        "document_id": document_id,
        "step": step,
        "status": status,
        "duration_ms": duration_ms,
        "summary": json.dumps(summary or {}, ensure_ascii=False),
        "preview": preview_text(preview),
        "error": preview_text(error, limit=800),
    }).mappings().one()
    return row["id"]


def start_trace_event(db: Session, document_id: str, step: str, *, summary: dict[str, Any] | None = None):
    return record_trace_event(db, document_id, step, "running", summary=summary)


def finish_trace_event(
    db: Session,
    event_id,
    status: str,
    *,
    duration_ms: int | None = None,
    summary: dict[str, Any] | None = None,
    preview: str | None = None,
    error: str | None = None,
) -> None:
    db.execute(text("""
        UPDATE document_rag_trace_events
        SET status=:status,
            duration_ms=:duration_ms,
            summary=cast(:summary as jsonb),
            preview=:preview,
            error=:error,
            updated_at=now()
        WHERE id=:id
    """), {
        "id": event_id,
        "status": status,
        "duration_ms": duration_ms,
        "summary": json.dumps(summary or {}, ensure_ascii=False),
        "preview": preview_text(preview),
        "error": preview_text(error, limit=800),
    })


def get_rag_trace_response(db: Session, document_id: str) -> dict[str, Any] | None:
    document = db.execute(text("""
        SELECT d.id,d.title,d.filename,d.content_type,d.status,d.error,d.created_at,d.updated_at,
               k.id AS knowledge_base_id,k.name AS knowledge_base
        FROM documents d
        JOIN knowledge_bases k ON k.id=d.knowledge_base_id
        WHERE d.id=:document_id
    """), {"document_id": document_id}).mappings().first()
    if not document:
        return None

    events = db.execute(text("""
        SELECT id,step,status,duration_ms,summary,preview,error,created_at,updated_at
        FROM document_rag_trace_events
        WHERE document_id=:document_id
        ORDER BY created_at ASC, id ASC
    """), {"document_id": document_id}).mappings().all()

    previews = db.execute(text("""
        SELECT id,content,metadata,embedding IS NOT NULL AS has_embedding,created_at
        FROM chunks
        WHERE document_id=:document_id
        ORDER BY created_at ASC, id ASC
        LIMIT 8
    """), {"document_id": document_id}).mappings().all()

    return {
        "document": _serialize_document(document),
        "events": [_serialize_event(row) for row in events],
        "chunk_summary": build_chunk_summary(db, document_id),
        "chunk_previews": [_serialize_chunk_preview(row) for row in previews],
    }


def build_chunk_summary(db: Session, document_id: str) -> dict[str, Any]:
    stats = db.execute(text("""
        SELECT COUNT(*) AS total_chunks,
               COUNT(embedding) AS embedded_chunks,
               COALESCE(MIN(length(content)), 0) AS min_chars,
               COALESCE(MAX(length(content)), 0) AS max_chars,
               COALESCE(AVG(length(content)), 0) AS avg_chars
        FROM chunks
        WHERE document_id=:document_id
    """), {"document_id": document_id}).mappings().one()
    metadata_rows = db.execute(text("""
        SELECT metadata
        FROM chunks
        WHERE document_id=:document_id
        LIMIT 2000
    """), {"document_id": document_id}).mappings().all()
    total = int(stats["total_chunks"] or 0)
    coverage_counts = {key: 0 for key in METADATA_KEYS}
    for row in metadata_rows:
        metadata = _json_dict(row["metadata"])
        for key in METADATA_KEYS:
            value = metadata.get(key)
            if value not in (None, "", [], {}):
                coverage_counts[key] += 1
    return {
        "total_chunks": total,
        "embedded_chunks": int(stats["embedded_chunks"] or 0),
        "min_chars": int(stats["min_chars"] or 0),
        "max_chars": int(stats["max_chars"] or 0),
        "avg_chars": round(float(stats["avg_chars"] or 0), 1),
        "metadata_coverage": {
            key: {
                "count": count,
                "ratio": round(count / total, 3) if total else 0,
            }
            for key, count in coverage_counts.items()
        },
    }


def metadata_coverage_from_records(records: list[dict[str, Any]]) -> dict[str, int]:
    coverage = {key: 0 for key in METADATA_KEYS}
    for record in records:
        metadata = _json_dict(record.get("metadata") or {})
        for key in METADATA_KEYS:
            value = metadata.get(key)
            if value not in (None, "", [], {}):
                coverage[key] += 1
    return coverage


def _serialize_document(row) -> dict[str, Any]:
    item = dict(row)
    return {key: str(value) if key == "id" or key.endswith("_id") else value for key, value in item.items()}


def _serialize_event(row) -> dict[str, Any]:
    item = dict(row)
    item["id"] = str(item["id"])
    item["label"] = TRACE_STEP_LABELS.get(item["step"], item["step"])
    item["summary"] = _json_dict(item.get("summary"))
    return item


def _serialize_chunk_preview(row) -> dict[str, Any]:
    metadata = _json_dict(row["metadata"])
    return {
        "id": str(row["id"]),
        "chunk_index": metadata.get("chunk_index"),
        "metadata": metadata,
        "has_embedding": bool(row["has_embedding"]),
        "char_count": len(row["content"] or ""),
        "preview": preview_text(row["content"], limit=CHUNK_PREVIEW_CHARS),
    }


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}
