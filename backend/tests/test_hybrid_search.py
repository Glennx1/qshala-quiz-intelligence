"""HybridRetriever.search(): the dense candidate pool + query-embedding cache.

Runs against the SQLite fallback (no pgvector locally), which exercises the
Python-side scan path. The database-side pgvector ANN path (is_postgres and
PG_VECTOR_AVAILABLE) only runs against a real Postgres with the extension
enabled, so it isn't covered here -- but both paths return the exact same
result shape, built from the same pool-size/relax-on-empty logic, so this
also guards the contract the Postgres path has to honor.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever
from backend.app.services.ai.local_provider import LocalEmbeddingProvider

TEST_DOC_ID = "test-doc-hybrid-search-001"


def _make_question(db, doc_id: str, qid: str, text: str, topic: str, embedding):
    q = Question(
        id=qid,
        document_id=doc_id,
        question_text=text,
        answer="Answer",
        topic=topic,
        tags=[],
        grade_min=3,
        grade_max=12,
        embedding=embedding,
    )
    db.add(q)
    return q


@pytest.fixture
def db_with_questions():
    test_engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestingSession()
    try:
        doc = Document(
            id=TEST_DOC_ID,
            filename="dummy.pptx",
            title="Dummy Deck",
            file_type="pptx",
            storage_path="dummy.pptx",
        )
        db.add(doc)
        db.commit()

        retriever = HybridRetriever(db)
        retriever.embedding_provider = LocalEmbeddingProvider()
        # Reuse the retriever's own (deterministic, local) embedding provider
        # so dense similarity is meaningful rather than all-zero vectors.
        # asyncio.run() (not get_event_loop()) so this sync fixture doesn't
        # touch whatever event loop the anyio-driven async tests are using.
        emb_space = asyncio.run(
            retriever.embedding_provider.get_embedding("space astronomy planets solar system")
        )
        emb_history = asyncio.run(
            retriever.embedding_provider.get_embedding("australian history federation canberra")
        )

        _make_question(db, doc.id, "q-space-1", "Which planet is known as the Red Planet?", "Space", emb_space)
        _make_question(db, doc.id, "q-history-1", "In what year did Australia federate?", "History", emb_history)
        db.commit()

        yield db
    finally:
        db.close()


@pytest.mark.anyio
async def test_search_returns_relevant_result_shape(db_with_questions):
    retriever = HybridRetriever(db_with_questions)
    retriever.embedding_provider = LocalEmbeddingProvider()
    results = await retriever.search(query="space astronomy planets", limit=5)

    assert len(results) > 0
    top = results[0]
    for key in ("question", "document", "slide", "relevance_score", "dense_similarity", "tag_overlap", "quote"):
        assert key in top
    # The space-themed question should outrank the unrelated history one.
    assert top["question"].id == "q-space-1"


@pytest.mark.anyio
async def test_search_relaxes_when_topic_filter_matches_nothing(db_with_questions):
    retriever = HybridRetriever(db_with_questions)
    retriever.embedding_provider = LocalEmbeddingProvider()
    # No question has this topic -- should fall back to the unfiltered pool
    # instead of returning nothing.
    results = await retriever.search(query="space astronomy planets", topic="Nonexistent Topic Xyz", limit=5)
    assert len(results) > 0


@pytest.mark.anyio
async def test_query_embedding_is_cached(db_with_questions, monkeypatch):
    retriever = HybridRetriever(db_with_questions)
    retriever.embedding_provider = LocalEmbeddingProvider()
    HybridRetriever._embedding_cache.clear()

    calls = {"n": 0}
    original_get_embedding = retriever.embedding_provider.get_embedding

    async def counting_get_embedding(text):
        calls["n"] += 1
        return await original_get_embedding(text)

    monkeypatch.setattr(retriever.embedding_provider, "get_embedding", counting_get_embedding)

    await retriever.search(query="space astronomy planets", limit=5)
    await retriever.search(query="space astronomy planets", limit=5)
    await retriever.search(query="  Space Astronomy Planets  ", limit=5)  # same text, different case/whitespace

    assert calls["n"] == 1, f"expected the embedding API to be called once (cached after), got {calls['n']} calls"

    HybridRetriever._embedding_cache.clear()
