from sqlalchemy import text
from sqlalchemy.orm import Session
from app.models.provider import OpenAICompatibleProvider, active_model_config, embed_texts, rerank_hits, vector_literal


ANSWER_SYSTEM_PROMPT = """你是新能源汽车维修诊断专家。回答必须严谨、可执行、中文输出。
固定结构：
1. 可能原因
2. 检查步骤
3. 安全提醒
4. 维修建议
5. 引用来源
6. 置信提示
禁止编造引用。若资料不足，明确说明需要补充检测数据。"""


async def retrieve(db: Session, query: str, knowledge_base_id: str | None, limit: int = 6) -> list[dict]:
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
    params = {"embedding": vector_literal(embedding), "limit": vector_limit}
    kb_filter = ""
    if knowledge_base_id:
        kb_filter = "WHERE c.knowledge_base_id=:knowledge_base_id"
        params["knowledge_base_id"] = knowledge_base_id
    rows = db.execute(text(f"""
        SELECT c.id, c.content, c.metadata, d.title, d.filename,
               1 - (c.embedding <=> cast(:embedding as vector)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        {kb_filter}
        ORDER BY c.embedding <=> cast(:embedding as vector)
        LIMIT :limit
    """), params).mappings().all()
    hits = [dict(row) for row in rows]
    return await rerank_hits(db, query, hits, limit=limit, config=model_config)


def build_prompt(
    question: str,
    hits: list[dict],
    image_description: str | None = None,
    history: list[dict] | None = None,
) -> list[dict]:
    context = "\n\n".join(
        f"[{index + 1}] 来源: {hit['title']} / {hit['filename']}\n{hit['content']}"
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
