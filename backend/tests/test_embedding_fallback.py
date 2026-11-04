"""Embedding failures must not silently become local hash vectors (audit Q7)."""
import asyncio
import uuid

import pytest

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.question import Question
from backend.app.services.ai import gemini_provider as gp
from backend.app.services.ai.gemini_provider import EmbeddingUnavailable, GeminiEmbeddingProvider
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever
from backend.app.services.ingestion.pipeline import IngestionPipeline, INGESTION_STATUS_REGISTRY

from test_v6_pipeline import FakeGemini
from test_dedup_before_ai import _deck, _items, CountingLLM
from test_identical_reupload import _register


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.is_error = status >= 400
        self._payload = payload or {}
        self.text = "boom"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.is_error:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=self)


def _vec(seed, n=768):
    return [float(seed + i % 7) for i in range(n)]


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(gp, "EMBEDDING_RETRY_DELAY_S", 0)
    return GeminiEmbeddingProvider(api_key="test-key-not-real")


def test_single_embedding_failure_raises_instead_of_returning_a_local_vector(provider, monkeypatch):
    async def always_429(*a, **k):
        return FakeResp(429)
    monkeypatch.setattr(gp, "_post_with_retry", always_429)
    monkeypatch.setattr(gp, "ALLOW_LOCAL_EMBEDDING_FALLBACK", False)
    with pytest.raises(EmbeddingUnavailable):
        asyncio.run(provider.get_embedding("hello"))


def test_old_fallback_still_available_behind_the_flag(provider, monkeypatch):
    async def always_429(*a, **k):
        return FakeResp(429)
    monkeypatch.setattr(gp, "_post_with_retry", always_429)
    monkeypatch.setattr(gp, "ALLOW_LOCAL_EMBEDDING_FALLBACK", True)
    vec = asyncio.run(provider.get_embedding("hello"))
    assert len(vec) == 768


def test_batch_failure_yields_none_entries_not_local_vectors(provider, monkeypatch):
    async def always_503(*a, **k):
        return FakeResp(503)
    monkeypatch.setattr(gp, "_post_with_retry", always_503)
    monkeypatch.setattr(gp, "ALLOW_LOCAL_EMBEDDING_FALLBACK", False)
    out = asyncio.run(provider.get_embeddings(["a", "b", "c"]))
    assert out == [None, None, None]


def test_batch_success_is_normalised(provider, monkeypatch):
    async def fake_post(client, url, payload, api_key, *a, **k):
        n = len(payload["requests"])
        return FakeResp(200, {"embeddings": [{"values": _vec(i + 1)} for i in range(n)]})

    monkeypatch.setattr(gp, "_post_with_retry", fake_post)
    out = asyncio.run(provider.get_embeddings(["a", "b"]))
    assert len(out) == 2 and all(v is not None and len(v) == 768 for v in out)
    assert abs(sum(x * x for x in out[0]) - 1.0) < 1e-6


def test_retry_pass_recovers_items_that_failed_the_first_time(provider, monkeypatch):
    state = {"single_calls": 0}

    async def flaky(client, url, payload, api_key, *a, **k):
        if "batchEmbedContents" in url:
            return FakeResp(503)
        state["single_calls"] += 1
        if state["single_calls"] <= 2:          # the first serial attempts for the two texts fail
            return FakeResp(503)
        return FakeResp(200, {"embedding": {"values": _vec(3)}})

    monkeypatch.setattr(gp, "_post_with_retry", flaky)
    out = asyncio.run(provider.get_embeddings(["a", "b"]))
    assert all(v is not None and len(v) == 768 for v in out)


def test_search_survives_missing_query_embedding_and_does_not_cache_it():
    class Down:
        async def get_embedding(self, text):
            raise EmbeddingUnavailable("down")

    db = SessionLocal()
    try:
        r = HybridRetriever(db)
        r.embedding_provider = Down()
        HybridRetriever._embedding_cache.clear()
        results = asyncio.run(r.search("central bank of India", limit=5))
        assert results, "keyword ranking should still return the seeded banking questions"
        assert "central bank of india" not in HybridRetriever._embedding_cache
        assert "bank" in results[0]["question"].question_text.lower()
    finally:
        db.close()


class HalfBrokenEmbedder:
    model = "fake-embed-1"

    async def get_embeddings(self, texts):
        return [None if i == 0 else [0.5] * 768 for i, _ in enumerate(texts)]


def _run_pipeline(embedder, n=3):
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    _deck(path, _items(uuid.uuid4().hex[:8], list(range(1, n + 1))))
    doc_id = _register(path, "emb.pptx")
    pipe = IngestionPipeline()
    pipe.qshala_tagger.provider = FakeGemini()
    pipe.qshala_tagger.rpm = 0
    pipe.embedding_provider = embedder
    pipe.llm_provider = CountingLLM()
    asyncio.run(pipe.run(doc_id))
    assert INGESTION_STATUS_REGISTRY[doc_id]["status"] == "COMPLETED"
    return doc_id


def test_pipeline_stores_no_vector_for_failed_items_and_labels_the_rest():
    doc_id = _run_pipeline(HalfBrokenEmbedder())
    db = SessionLocal()
    try:
        qs = db.query(Question).filter(Question.document_id == doc_id).all()
        assert len(qs) == 3
        without = [q for q in qs if not q.embedding]
        with_vec = [q for q in qs if q.embedding]
        assert len(without) == 1 and without[0].embedding_model is None
        assert len(with_vec) == 2 and all(q.embedding_model == "fake-embed-1" for q in with_vec)
    finally:
        db.close()


class AllBrokenEmbedder:
    async def get_embeddings(self, texts):
        raise RuntimeError("provider down")


def test_pipeline_total_embedding_failure_stores_null_not_zero_vectors():
    doc_id = _run_pipeline(AllBrokenEmbedder(), n=2)
    db = SessionLocal()
    try:
        qs = db.query(Question).filter(Question.document_id == doc_id).all()
        assert len(qs) == 2 and all(not q.embedding and q.embedding_model is None for q in qs)
    finally:
        db.close()
