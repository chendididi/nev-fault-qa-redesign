from app.knowledge.parser import chunk_text, extract_repair_metadata


def test_chunk_text_keeps_overlap():
    chunks = chunk_text("a" * 1200, size=500, overlap=100)
    assert len(chunks) == 3
    assert chunks[0][-100:] == chunks[1][:100]


def test_chunk_text_ignores_empty_lines():
    assert chunk_text("\n\n电池故障\n\n驱动异常\n") == ["电池故障\n驱动异常"]


def test_extract_repair_metadata_finds_page_dtc_system_and_vehicle():
    metadata = extract_repair_metadata("""
    --- 第 12 页 / 章节 4.2 / 快充系统 ---
    车型：NEV-A01
    故障码：P1A0C
    HVIL 回路异常，快充握手失败。
    """)

    assert metadata["page"] == 12
    assert metadata["dtc"] == ["P1A0C"]
    assert "HVIL" in metadata["system"]
    assert "快充" in metadata["system"]
    assert metadata["vehicle_model"] == "NEV-A01"
