import pytest

from app.models import provider as provider_module
from app.models.provider import LocalEmbeddingProvider, LocalModelUnavailable, OpenAICompatibleProvider, rerank_hits


@pytest.mark.asyncio
async def test_vision_ocr_reuses_chat_model_when_vision_model_is_empty(monkeypatch):
    async def fake_chat(self, messages, *, model=None, temperature=0.2):
        assert model == "gpt-5.5"
        assert messages[0]["content"][1]["type"] == "image_url"
        return "NEV OCR 8317"

    monkeypatch.setattr(OpenAICompatibleProvider, "chat", fake_chat)
    provider = OpenAICompatibleProvider({
        "base_url": "http://127.0.0.1:8317/v1",
        "api_key": "test",
        "chat_model": "gpt-5.5",
        "vision_model": None,
    })

    assert await provider.ocr_image(b"image", "image/png") == "NEV OCR 8317"


def test_local_embedding_validates_configured_dimension(monkeypatch):
    class FakeModel:
        def encode(self, texts, batch_size=8, max_length=8192):
            return {"dense_vecs": [[0.1, 0.2]]}

    monkeypatch.setattr(LocalEmbeddingProvider, "_load", lambda self: FakeModel())
    provider = LocalEmbeddingProvider({"embedding_model": "fake", "embedding_dim": 3})

    with pytest.raises(LocalModelUnavailable, match="维度不匹配"):
        provider.embed(["车辆无法快充"])


@pytest.mark.asyncio
async def test_rerank_hits_orders_by_local_scores(monkeypatch):
    async def fake_rerank_texts(db, query, passages, config=None):
        return [0.2, 0.9]

    monkeypatch.setattr(provider_module, "rerank_texts", fake_rerank_texts)
    hits = [
        {"id": "1", "content": "检查雨刮片", "score": 0.8},
        {"id": "2", "content": "检查充电口和 BMS", "score": 0.7},
    ]

    ranked = await rerank_hits(None, "车辆无法快充", hits, limit=2, config={"rerank_model": "fake"})

    assert [hit["id"] for hit in ranked] == ["2", "1"]
    assert ranked[0]["rerank_score"] == 0.9
