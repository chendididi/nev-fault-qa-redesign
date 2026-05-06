import re
import time
from typing import Any, AsyncIterator

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.provider import chat_for_task, demo_answer, embed_texts, get_app_setting, rerank_hits, rerank_texts, stream_for_task, vector_literal
from app.rag.trace import preview_text


DOMAIN_TERMS = [
    "BMS",
    "OBC",
    "DCDC",
    "DC/DC",
    "VCU",
    "CAN",
    "HVIL",
    "MCU",
    "READY",
    "SOC",
    "绝缘",
    "互锁",
    "快充",
    "慢充",
    "高压",
    "预充",
    "热管理",
    "水泵",
    "限扭",
    "唤醒",
    "离线",
    "充电",
    "电池",
    "故障",
    "仪表",
    "绝缘",
    "互锁",
    "快充",
    "慢充",
    "高压",
    "预充",
    "热管理",
    "水泵",
    "限扭",
    "唤醒",
    "离线",
]


ANSWER_SYSTEM_PROMPT = """你是新能源汽车维修诊断专家。回答必须严谨、可执行、中文输出。
固定结构：
1. 可能原因
2. 检查步骤
3. 安全提醒
4. 维修建议
5. 引用来源
6. 置信提示
禁止编造引用。若资料不足，明确说明需要补充检测数据。"""


async def retrieve(
    db: Session,
    query: str,
    knowledge_base_id: str | None,
    limit: int = 6,
    *,
    document_id: str | None = None,
    use_rerank: bool = True,
    use_keyword: bool = True,
) -> list[dict]:
    count_filter, count_params = _scope_where(knowledge_base_id, document_id, alias="")
    chunk_count = db.execute(text(f"SELECT COUNT(*) FROM chunks {count_filter}"), count_params).scalar_one()
    if not chunk_count:
        return []

    vector_limit = max(limit * 4, 12)
    hits: list[dict] = []
    try:
        embedding = (await embed_texts(db, [query]))[0]
        rows = _vector_rows(db, embedding, knowledge_base_id, vector_limit, document_id=document_id)
        hits = _merge_hits([dict(row) for row in rows], query, source="vector")
    except Exception:
        hits = []
    if use_keyword:
        keyword_terms = extract_retrieval_terms(query)
        if keyword_terms:
            keyword_rows = _keyword_rows(db, keyword_terms, knowledge_base_id, vector_limit, document_id=document_id)
            hits = _merge_hits(hits + [dict(row) for row in keyword_rows], query, source="keyword")
    if not hits:
        recent_rows = _recent_rows(db, knowledge_base_id, min(vector_limit, 12), document_id=document_id)
        hits = _merge_hits([dict(row) for row in recent_rows], query, source="recent")
    ranked = sorted(hits, key=_pre_rerank_score, reverse=True)
    if not use_rerank:
        return ranked[:limit]
    return await rerank_hits(db, query, ranked[:max(limit * 5, 20)], limit=limit)


def extract_retrieval_terms(query: str) -> list[str]:
    terms = set(re.findall(r"\b[PCBU][0-9A-F]{4}\b", query.upper()))
    lowered = query.lower()
    for term in DOMAIN_TERMS:
        if term.lower() in lowered:
            terms.add(term)
    return sorted(terms, key=lambda value: (-len(value), value))[:8]


def _scope_where(knowledge_base_id: str | None, document_id: str | None, *, alias: str = "c") -> tuple[str, dict[str, object]]:
    prefix = f"{alias}." if alias else ""
    clauses = []
    params: dict[str, object] = {}
    if knowledge_base_id:
        clauses.append(f"{prefix}knowledge_base_id=:knowledge_base_id")
        params["knowledge_base_id"] = knowledge_base_id
    if document_id:
        clauses.append(f"{prefix}document_id=:document_id")
        params["document_id"] = document_id
    return ("WHERE " + " AND ".join(clauses), params) if clauses else ("", params)


def _append_scope(base_where: str, knowledge_base_id: str | None, document_id: str | None) -> tuple[str, dict[str, object]]:
    scope_where, params = _scope_where(knowledge_base_id, document_id)
    if not scope_where:
        return base_where, params
    scope_clause = scope_where.removeprefix("WHERE ")
    joiner = " AND " if "WHERE" in base_where.upper() else " WHERE "
    return f"{base_where}{joiner}{scope_clause}", params


def _vector_rows(db: Session, embedding: list[float], knowledge_base_id: str | None, limit: int, *, document_id: str | None = None):
    params = {"embedding": vector_literal(embedding), "limit": limit}
    where_clause, scope_params = _append_scope("WHERE c.embedding IS NOT NULL", knowledge_base_id, document_id)
    params.update(scope_params)
    return db.execute(text(f"""
        SELECT c.id, c.document_id, c.content, c.metadata, d.title, d.filename,
               1 - (c.embedding <=> cast(:embedding as vector)) AS score,
               1 - (c.embedding <=> cast(:embedding as vector)) AS vector_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {where_clause}
        ORDER BY c.embedding <=> cast(:embedding as vector)
        LIMIT :limit
    """), params).mappings().all()


def _keyword_rows(db: Session, terms: list[str], knowledge_base_id: str | None, limit: int, *, document_id: str | None = None):
    params: dict[str, object] = {"limit": limit}
    clauses = []
    for index, term in enumerate(terms):
        key = f"term_{index}"
        params[key] = f"%{term}%"
        clauses.append(f"(c.content ILIKE :{key} OR c.metadata::text ILIKE :{key})")
    where_clause, scope_params = _append_scope(f"WHERE ({' OR '.join(clauses)})", knowledge_base_id, document_id)
    params.update(scope_params)
    return db.execute(text(f"""
        SELECT c.id, c.document_id, c.content, c.metadata, d.title, d.filename,
               0.0 AS score,
               0.0 AS vector_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {where_clause}
        ORDER BY c.created_at DESC
        LIMIT :limit
    """), params).mappings().all()


def _recent_rows(db: Session, knowledge_base_id: str | None, limit: int, *, document_id: str | None = None):
    params: dict[str, object] = {"limit": limit}
    where_clause, scope_params = _scope_where(knowledge_base_id, document_id)
    params.update(scope_params)
    return db.execute(text(f"""
        SELECT c.id, c.document_id, c.content, c.metadata, d.title, d.filename,
               0.0 AS score,
               0.0 AS vector_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {where_clause}
        ORDER BY c.created_at DESC
        LIMIT :limit
    """), params).mappings().all()


def _merge_hits(rows: list[dict], query: str, *, source: str) -> list[dict]:
    by_id: dict[object, dict] = {}
    terms = extract_retrieval_terms(query)
    for row in rows:
        hit = by_id.setdefault(row["id"], dict(row))
        hit.setdefault("sources", [])
        for row_source in row.get("sources") or [source]:
            if row_source not in hit["sources"]:
                hit["sources"].append(row_source)
        matches = _matching_terms(hit.get("content", ""), hit.get("metadata") or {}, terms)
        hit["keyword_matches"] = sorted(set(hit.get("keyword_matches", []) + matches))
        hit["keyword_score"] = len(hit["keyword_matches"])
        hit["score"] = max(float(hit.get("score") or 0), float(row.get("score") or 0))
        hit["vector_score"] = max(float(hit.get("vector_score") or 0), float(row.get("vector_score") or 0))
    return list(by_id.values())


def _matching_terms(content: str, metadata: dict, terms: list[str]) -> list[str]:
    haystack = f"{content}\n{metadata}".lower()
    return [term for term in terms if term.lower() in haystack]


def _pre_rerank_score(hit: dict) -> float:
    return float(hit.get("vector_score") or 0) + min(float(hit.get("keyword_score") or 0), 3.0) * 0.05


def _format_citation_metadata(hit: dict) -> str:
    metadata = hit.get("metadata") or {}
    parts = []
    if metadata.get("page"):
        parts.append(f"第 {metadata['page']} 页")
    if metadata.get("heading"):
        parts.append(str(metadata["heading"]))
    for key in ["system", "dtc"]:
        values = metadata.get(key)
        if isinstance(values, list) and values:
            parts.append("/".join(str(value) for value in values[:4]))
    return "（" + " · ".join(parts) + "）" if parts else ""


async def run_document_rag_demo(db: Session, document_id: str, question: str, *, limit: int = 5) -> dict[str, Any]:
    document = db.execute(text("""
        SELECT d.id,d.title,d.filename,d.status,d.knowledge_base_id,k.name AS knowledge_base
        FROM documents d
        JOIN knowledge_bases k ON k.id=d.knowledge_base_id
        WHERE d.id=:document_id
    """), {"document_id": document_id}).mappings().first()
    if not document:
        raise ValueError("document_not_found")
    query = question.strip()
    if not query:
        raise ValueError("empty_question")

    fallbacks: list[dict[str, str]] = []
    steps: list[dict[str, Any]] = []
    retrieval_terms = extract_retrieval_terms(query)
    steps.append({
        "name": "query_parse",
        "label": "检索词解析",
        "status": "done",
        "summary": {"terms": retrieval_terms, "question_chars": len(query)},
    })

    vector_limit = max(limit * 4, 12)
    vector_rows: list[dict] = []
    started = time.perf_counter()
    try:
        query_embedding = (await embed_texts(db, [query]))[0]
        vector_rows = [dict(row) for row in _vector_rows(db, query_embedding, None, vector_limit, document_id=document_id)]
        steps.append({
            "name": "vector_search",
            "label": "向量候选",
            "status": "done",
            "duration_ms": _step_ms(started),
            "summary": {"candidate_count": len(vector_rows), "vector_dim": len(query_embedding)},
        })
    except Exception as exc:
        fallbacks.append({"stage": "embedding", "message": str(exc), "used": "keyword_or_recent_chunks"})
        steps.append({
            "name": "vector_search",
            "label": "向量候选",
            "status": "fallback",
            "duration_ms": _step_ms(started),
            "summary": {"candidate_count": 0, "fallback": "keyword_or_recent_chunks"},
            "error": str(exc),
        })

    hits = _merge_hits(vector_rows, query, source="vector") if vector_rows else []
    keyword_rows: list[dict] = []
    started = time.perf_counter()
    if retrieval_terms:
        keyword_rows = [dict(row) for row in _keyword_rows(db, retrieval_terms, None, vector_limit, document_id=document_id)]
        hits = _merge_hits(hits + keyword_rows, query, source="keyword")
    steps.append({
        "name": "keyword_search",
        "label": "关键词命中",
        "status": "done",
        "duration_ms": _step_ms(started),
        "summary": {"terms": retrieval_terms, "candidate_count": len(keyword_rows)},
    })

    if not hits:
        recent_rows = [dict(row) for row in _recent_rows(db, None, min(vector_limit, 12), document_id=document_id)]
        hits = _merge_hits(recent_rows, query, source="recent")
        fallbacks.append({"stage": "candidate_generation", "message": "未获得向量或关键词候选", "used": "recent_chunks"})

    pre_ranked = sorted(hits, key=_pre_rerank_score, reverse=True)
    for hit in pre_ranked:
        hit["pre_score"] = _pre_rerank_score(hit)
    steps.append({
        "name": "merge_rank",
        "label": "合并预排序",
        "status": "done",
        "summary": {"candidate_count": len(pre_ranked), "top_sources": _top_sources(pre_ranked[:limit])},
    })

    started = time.perf_counter()
    try:
        rerank_scores = await rerank_texts(db, query, [hit["content"] for hit in pre_ranked[:max(limit * 5, 20)]])
        reranked = []
        for hit, score in zip(pre_ranked, rerank_scores, strict=False):
            enriched = dict(hit)
            enriched["rerank_score"] = score
            reranked.append(enriched)
        ranked_hits = sorted(reranked, key=lambda item: item["rerank_score"], reverse=True)[:limit]
        steps.append({
            "name": "rerank",
            "label": "重排 TopK",
            "status": "done",
            "duration_ms": _step_ms(started),
            "summary": {"reranked_count": len(ranked_hits)},
        })
    except Exception as exc:
        ranked_hits = pre_ranked[:limit]
        fallbacks.append({"stage": "rerank", "message": str(exc), "used": "pre_rank_order"})
        steps.append({
            "name": "rerank",
            "label": "重排 TopK",
            "status": "fallback",
            "duration_ms": _step_ms(started),
            "summary": {"reranked_count": 0, "fallback": "pre_rank_order"},
            "error": str(exc),
        })

    messages = build_prompt(query, ranked_hits)
    prompt_summary = {
        "message_count": len(messages),
        "context_chunks": len(ranked_hits),
        "prompt_chars": sum(len(item.get("content", "")) for item in messages),
        "citation_labels": [f"[{index + 1}]" for index in range(len(ranked_hits))],
    }

    started = time.perf_counter()
    demo_mode = get_app_setting(db, "demo_mode", "fallback")
    if demo_mode == "always":
        answer = demo_answer(query, ranked_hits)
        fallbacks.append({"stage": "answer", "message": "demo_mode=always", "used": "demo_answer"})
        answer_status = "fallback"
    else:
        try:
            answer = await chat_for_task(db, "chat", messages)
            answer_status = "done"
        except Exception as exc:
            fallbacks.append({"stage": "answer", "message": str(exc), "used": "fallback_chat_or_demo"})
            try:
                answer = await chat_for_task(db, "fallback_chat", messages)
                answer_status = "fallback"
            except Exception as fallback_exc:
                if demo_mode in ("fallback", "always"):
                    answer = demo_answer(query, ranked_hits)
                    answer_status = "fallback"
                    fallbacks.append({"stage": "fallback_chat", "message": str(fallback_exc), "used": "demo_answer"})
                else:
                    answer = _degraded_answer(fallback_exc, ranked_hits)
                    answer_status = "failed"
                    fallbacks.append({"stage": "fallback_chat", "message": str(fallback_exc), "used": "degraded_answer"})
    steps.append({
        "name": "answer_generation",
        "label": "答案生成",
        "status": answer_status,
        "duration_ms": _step_ms(started),
        "summary": {"demo_mode": demo_mode, "answer_chars": len(answer)},
    })

    return {
        "document": {
            "id": str(document["id"]),
            "title": document["title"],
            "filename": document["filename"],
            "status": document["status"],
            "knowledge_base_id": str(document["knowledge_base_id"]),
            "knowledge_base": document["knowledge_base"],
        },
        "query": {"question": query, "retrieval_terms": retrieval_terms},
        "steps": steps,
        "candidates": [_serialize_demo_hit(hit, index + 1) for index, hit in enumerate(pre_ranked[:12])],
        "reranked_hits": [_serialize_demo_hit(hit, index + 1) for index, hit in enumerate(ranked_hits)],
        "prompt_summary": prompt_summary,
        "answer": answer,
        "citations": [_serialize_demo_citation(hit, index + 1) for index, hit in enumerate(ranked_hits)],
        "fallbacks": fallbacks,
    }


def _step_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _top_sources(hits: list[dict]) -> list[str]:
    sources: list[str] = []
    for hit in hits:
        for source in hit.get("sources") or []:
            if source not in sources:
                sources.append(source)
    return sources


def _serialize_demo_hit(hit: dict, rank: int) -> dict[str, Any]:
    metadata = hit.get("metadata") or {}
    return {
        "rank": rank,
        "id": str(hit["id"]),
        "document_id": str(hit.get("document_id") or ""),
        "title": hit.get("title", ""),
        "filename": hit.get("filename", ""),
        "chunk_index": metadata.get("chunk_index"),
        "score": round(float(hit.get("rerank_score", hit.get("pre_score", hit.get("score", 0))) or 0), 4),
        "vector_score": round(float(hit.get("vector_score") or 0), 4),
        "keyword_score": int(hit.get("keyword_score") or 0),
        "pre_score": round(float(hit.get("pre_score", _pre_rerank_score(hit))) or 0, 4),
        "rerank_score": round(float(hit["rerank_score"]), 4) if hit.get("rerank_score") is not None else None,
        "sources": hit.get("sources", []),
        "keyword_matches": hit.get("keyword_matches", []),
        "metadata": metadata,
        "content": preview_text(hit.get("content", ""), limit=420),
    }


def _serialize_demo_citation(hit: dict, rank: int) -> dict[str, Any]:
    return {
        "label": f"[{rank}]",
        "chunk_id": str(hit["id"]),
        "title": hit.get("title", ""),
        "filename": hit.get("filename", ""),
        "metadata": hit.get("metadata") or {},
        "content": preview_text(hit.get("content", ""), limit=320),
    }


def build_prompt(
    question: str,
    hits: list[dict],
    image_description: str | None = None,
    history: list[dict] | None = None,
) -> list[dict]:
    context = "\n\n".join(
        f"[{index + 1}] 来源: {hit['title']} / {hit['filename']}{_format_citation_metadata(hit)}\n{hit['content']}"
        for index, hit in enumerate(hits)
    )
    image_part = f"\n\n图片理解结果:\n{image_description}" if image_description else ""
    history_part = ""
    if history:
        formatted_history = "\n".join(
            f"{'用户' if item.get('role') == 'user' else '诊断助手'}: {item.get('content', '')}"
            for item in history
            if item.get("role") in {"user", "assistant"} and item.get("content")
        )
        if formatted_history:
            history_part = f"\n\n历史对话上下文:\n{formatted_history}"
    user_prompt = f"""维修问题:
{question}
{image_part}
{history_part}

检索资料:
{context or "无可用资料"}

请按照固定结构输出，并在引用来源中使用 [1]、[2] 这样的编号。"""
    return [{"role": "system", "content": ANSWER_SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]


async def answer_question(
    db: Session,
    question: str,
    knowledge_base_id: str | None,
    image_description: str | None = None,
    history: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    messages, hits = await prepare_answer_context(db, question, knowledge_base_id, image_description, history)
    demo_mode = get_app_setting(db, "demo_mode", "fallback")
    if demo_mode == "always":
        return demo_answer(question, hits, image_description), hits
    try:
        answer = await chat_for_task(db, "chat", messages)
    except Exception as exc:
        try:
            answer = await chat_for_task(db, "fallback_chat", messages)
        except Exception:
            if demo_mode in ("fallback", "always"):
                answer = demo_answer(question, hits, image_description)
            else:
                answer = _degraded_answer(exc, hits)
    return answer, hits


async def prepare_answer_context(
    db: Session,
    question: str,
    knowledge_base_id: str | None,
    image_description: str | None = None,
    history: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    history_query = "\n".join(item.get("content", "") for item in (history or [])[-4:] if item.get("role") == "user")
    retrieval_query = "\n".join(part for part in [history_query, question, image_description or ""] if part)
    hits = await retrieve(db, retrieval_query, knowledge_base_id)
    retrieval_terms = extract_retrieval_terms(retrieval_query)
    for hit in hits:
        hit["retrieval_terms"] = retrieval_terms
    return build_prompt(question, hits, image_description, history), hits


async def stream_answer_chunks(
    db: Session,
    question: str,
    knowledge_base_id: str | None,
    image_description: str | None = None,
    history: list[dict] | None = None,
) -> tuple[AsyncIterator[str], list[dict]]:
    messages, hits = await prepare_answer_context(db, question, knowledge_base_id, image_description, history)
    demo_mode = get_app_setting(db, "demo_mode", "fallback")
    if demo_mode == "always":
        async def demo_iter() -> AsyncIterator[str]:
            yield demo_answer(question, hits, image_description)

        return demo_iter(), hits

    async def iterator() -> AsyncIterator[str]:
        try:
            async for chunk in stream_for_task(db, "chat", messages):
                yield chunk
        except Exception as exc:
            try:
                async for chunk in stream_for_task(db, "fallback_chat", messages):
                    yield chunk
            except Exception:
                if demo_mode in ("fallback", "always"):
                    yield demo_answer(question, hits, image_description)
                else:
                    yield _degraded_answer(exc, hits)

    return iterator(), hits


def _degraded_answer(exc: Exception, hits: list[dict]) -> str:
    return f"""1. 可能原因
模型调用失败，无法完成诊断。

2. 检查步骤
请管理员检查模型配置 base_url、api_key、chat_model 是否可用。

3. 安全提醒
涉及高压电池、驱动电机、充电系统时，必须先断电并由具备资质的人员操作。

4. 维修建议
错误信息: {exc}

5. 引用来源
{", ".join(f"[{i + 1}] {hit['title']}" for i, hit in enumerate(hits)) or "无"}

6. 置信提示
低。当前回答为系统降级提示。"""
