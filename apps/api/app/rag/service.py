import re
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models.provider import OpenAICompatibleProvider, active_model_config, embed_texts, rerank_hits, vector_literal


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
    use_rerank: bool = True,
    use_keyword: bool = True,
) -> list[dict]:
    count_params = {}
    count_filter = ""
    if knowledge_base_id:
        count_filter = "WHERE knowledge_base_id=:knowledge_base_id"
        count_params["knowledge_base_id"] = knowledge_base_id
    chunk_count = db.execute(text(f"SELECT COUNT(*) FROM chunks {count_filter}"), count_params).scalar_one()
    if not chunk_count:
        return []

    model_config = active_model_config(db)
    embedding = (await embed_texts(db, [query], model_config))[0]
    vector_limit = max(limit * 4, 12)
    rows = _vector_rows(db, embedding, knowledge_base_id, vector_limit)
    hits = _merge_hits([dict(row) for row in rows], query, source="vector")
    if use_keyword:
        keyword_terms = extract_retrieval_terms(query)
        if keyword_terms:
            keyword_rows = _keyword_rows(db, keyword_terms, knowledge_base_id, vector_limit)
            hits = _merge_hits(hits + [dict(row) for row in keyword_rows], query, source="keyword")
    ranked = sorted(hits, key=_pre_rerank_score, reverse=True)
    if not use_rerank:
        return ranked[:limit]
    return await rerank_hits(db, query, ranked[:max(limit * 5, 20)], limit=limit, config=model_config)


def extract_retrieval_terms(query: str) -> list[str]:
    terms = set(re.findall(r"\b[PCBU][0-9A-F]{4}\b", query.upper()))
    lowered = query.lower()
    for term in DOMAIN_TERMS:
        if term.lower() in lowered:
            terms.add(term)
    return sorted(terms, key=lambda value: (-len(value), value))[:8]


def _vector_rows(db: Session, embedding: list[float], knowledge_base_id: str | None, limit: int):
    params = {"embedding": vector_literal(embedding), "limit": limit}
    kb_filter = ""
    if knowledge_base_id:
        kb_filter = "WHERE c.knowledge_base_id=:knowledge_base_id"
        params["knowledge_base_id"] = knowledge_base_id
    return db.execute(text(f"""
        SELECT c.id, c.content, c.metadata, d.title, d.filename,
               1 - (c.embedding <=> cast(:embedding as vector)) AS score,
               1 - (c.embedding <=> cast(:embedding as vector)) AS vector_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {kb_filter}
        ORDER BY c.embedding <=> cast(:embedding as vector)
        LIMIT :limit
    """), params).mappings().all()


def _keyword_rows(db: Session, terms: list[str], knowledge_base_id: str | None, limit: int):
    params: dict[str, object] = {"limit": limit}
    clauses = []
    for index, term in enumerate(terms):
        key = f"term_{index}"
        params[key] = f"%{term}%"
        clauses.append(f"(c.content ILIKE :{key} OR c.metadata::text ILIKE :{key})")
    kb_filter = ""
    if knowledge_base_id:
        kb_filter = "AND c.knowledge_base_id=:knowledge_base_id"
        params["knowledge_base_id"] = knowledge_base_id
    return db.execute(text(f"""
        SELECT c.id, c.content, c.metadata, d.title, d.filename,
               0.0 AS score,
               0.0 AS vector_score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE ({' OR '.join(clauses)}) {kb_filter}
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
    history_query = "\n".join(item.get("content", "") for item in (history or [])[-4:] if item.get("role") == "user")
    retrieval_query = "\n".join(part for part in [history_query, question, image_description or ""] if part)
    hits = await retrieve(db, retrieval_query, knowledge_base_id)
    provider = OpenAICompatibleProvider(active_model_config(db))
    try:
        answer = await provider.chat(build_prompt(question, hits, image_description, history))
    except Exception as exc:
        answer = f"""1. 可能原因
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
    return answer, hits
