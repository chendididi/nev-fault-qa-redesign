from app.rag.service import build_prompt


def test_prompt_requires_structured_answer():
    messages = build_prompt("车辆无法快充", [{"title": "手册", "filename": "manual.pdf", "content": "检查 BMS 和充电口"}])
    content = messages[0]["content"] + messages[1]["content"]
    assert "可能原因" in content
    assert "检查步骤" in content
    assert "[1]" in content


def test_prompt_includes_chat_history():
    messages = build_prompt(
        "下一步怎么查？",
        [],
        history=[
            {"role": "user", "content": "车辆无法快充"},
            {"role": "assistant", "content": "先检查充电口和 BMS。"},
        ],
    )

    content = messages[1]["content"]
    assert "历史对话上下文" in content
    assert "用户: 车辆无法快充" in content
    assert "诊断助手: 先检查充电口和 BMS。" in content
