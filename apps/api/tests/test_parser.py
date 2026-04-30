from app.knowledge.parser import chunk_text


def test_chunk_text_keeps_overlap():
    chunks = chunk_text("a" * 1200, size=500, overlap=100)
    assert len(chunks) == 3
    assert chunks[0][-100:] == chunks[1][:100]


def test_chunk_text_ignores_empty_lines():
    assert chunk_text("\n\n电池故障\n\n驱动异常\n") == ["电池故障\n驱动异常"]
