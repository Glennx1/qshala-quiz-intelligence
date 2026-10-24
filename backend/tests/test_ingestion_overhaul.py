"""Regression tests for the ingestion/tagging overhaul.

These lock in the three things that kept breaking:
  1. No DB transaction may stay open across a slow stage (the IdleInTransactionSessionTimeout class).
  2. The chunked batch tagger must be robust: split large input, park failed/short chunks in review,
     never drop a question or raise out of the deck.
  3. The dedup step must recover from a stale connection (retry-once in the pipeline).
"""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import SessionLocal, short_session
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.models.qshala_tag import QshalaTag
from backend.app.services.tagging import qshala_batch


# --------------------------------------------------------------------- helpers

def _canned_item(n):
    return {
        "n": n,
        "topics": [{"theme": "History", "subtopic_l2": "Modern History", "keywords": ["Exploration"]}],
        "geo_location": "", "india_international": "NA", "relevant_year": 1770,
        "fit": "good", "search_summary": "ok",
    }


class FakeProvider:
    """Returns a well-formed `results` array, one item per [n=X] marker in the prompt."""
    def __init__(self):
        self.calls = 0

    async def generate_json_schema(self, prompt, schema, system_instruction=None, model=None,
                                   thinking_level=None, temperature=0.0):
        import re
        self.calls += 1
        ns = [int(m) for m in re.findall(r"\[n=(\d+)\]", prompt)]
        return {"results": [_canned_item(n) for n in ns]}, {"in": 1, "out": 1}


def _make_questions(db, doc_id, n):
    db.add(Document(id=doc_id, filename="t.pptx", title="t", year=2022, file_type="pptx",
                    storage_path="x", file_size_bytes=1, processing_status="PROCESSING"))
    db.flush()
    qs = []
    for i in range(n):
        q = Question(id=str(uuid.uuid4()), document_id=doc_id,
                     question_text=f"Who charted coast number {i}?", answer=f"Explorer {i}",
                     topic="Uncategorised")
        db.add(q)
        qs.append(q)
    db.flush()
    return qs


def _cleanup(doc_id):
    db = SessionLocal()
    try:
        db.query(QshalaTag).filter(QshalaTag.question_id.in_(
            [q.id for q in db.query(Question).filter(Question.document_id == doc_id).all()])).delete(
            synchronize_session=False)
        db.query(Question).filter(Question.document_id == doc_id).delete(synchronize_session=False)
        db.query(Document).filter(Document.id == doc_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------- invariant guardrail

def test_ensure_clean_commits_open_transaction():
    from backend.app.services.ingestion.pipeline import _ensure_clean
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))          # opens a transaction
        assert db.in_transaction()
        _ensure_clean(db, "test boundary")
        assert not db.in_transaction()         # invariant restored, no open idle transaction
    finally:
        db.close()


def test_short_session_commits_and_closes():
    doc_id = str(uuid.uuid4())
    try:
        with short_session() as db:
            db.add(Document(id=doc_id, filename="s.pptx", title="s", year=2022, file_type="pptx",
                            storage_path="x", file_size_bytes=1, processing_status="PROCESSING"))
        # committed and closed on exit
        db2 = SessionLocal()
        assert db2.query(Document).filter(Document.id == doc_id).first() is not None
        db2.close()
    finally:
        _cleanup(doc_id)


# --------------------------------------------------------------------- batch tagger robustness

def test_batch_tags_every_question_with_a_real_topic():
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        qs = _make_questions(db, doc_id, 5)
        stats = asyncio.run(qshala_batch.tag_questions_batched(
            db, qs, provider=FakeProvider(), model="fake"))
        db.commit()
        assert stats["confirmed"] + stats["draft"] == 5          # none dropped
        rows = db.query(QshalaTag).filter(QshalaTag.question_id.in_([q.id for q in qs])).all()
        assert len(rows) == 5
        # every question got a real classification (topic_l1 set), none parked-for-review
        assert all(r.topic_l1 for r in rows)
    finally:
        db.close()
        _cleanup(doc_id)


def test_large_input_splits_into_multiple_chunks():
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        n = qshala_batch.CHUNK_SIZE * 2 + 3     # forces 3 chunks
        qs = _make_questions(db, doc_id, n)
        prov = FakeProvider()
        stats = asyncio.run(qshala_batch.tag_questions_batched(db, qs, provider=prov, model="fake"))
        db.commit()
        assert prov.calls == 3                   # one Gemini call per chunk, not per question
        assert stats["confirmed"] + stats["draft"] == n          # every question tagged, none dropped
        rows = db.query(QshalaTag).filter(QshalaTag.question_id.in_([q.id for q in qs])).all()
        assert sum(1 for r in rows if r.topic_l1) == n
    finally:
        db.close()
        _cleanup(doc_id)


def test_short_results_parks_missing_questions_for_review():
    """Model returns fewer items than asked: the missing ones must go to review (draft), not vanish."""
    doc_id = str(uuid.uuid4())

    class ShortProvider(FakeProvider):
        async def generate_json_schema(self, prompt, schema, **k):
            import re
            ns = [int(m) for m in re.findall(r"\[n=(\d+)\]", prompt)]
            # drop the last item from each chunk
            return {"results": [_canned_item(n) for n in ns[:-1]]}, {"in": 1, "out": 1}

    db = SessionLocal()
    try:
        qs = _make_questions(db, doc_id, 5)      # one chunk (5 < CHUNK_SIZE), 1 item dropped
        stats = asyncio.run(qshala_batch.tag_questions_batched(
            db, qs, provider=ShortProvider(), model="fake"))
        db.commit()
        assert stats["confirmed"] + stats["draft"] == 5          # none dropped
        rows = db.query(QshalaTag).filter(QshalaTag.question_id.in_([q.id for q in qs])).all()
        tagged = [r for r in rows if r.topic_l1]
        parked = [r for r in rows if not r.topic_l1 and (r.verification_notes or "").startswith("needs review")]
        assert len(tagged) == 4 and len(parked) == 1             # 4 classified, the missing 1 parked
    finally:
        db.close()
        _cleanup(doc_id)


def test_failed_chunk_parks_all_its_questions_and_does_not_raise():
    doc_id = str(uuid.uuid4())

    class BoomProvider:
        async def generate_json_schema(self, *a, **k):
            raise RuntimeError("gemini down")

    db = SessionLocal()
    try:
        qs = _make_questions(db, doc_id, 4)
        stats = asyncio.run(qshala_batch.tag_questions_batched(
            db, qs, provider=BoomProvider(), model="fake"))
        db.commit()
        assert stats["draft"] == 4 and stats["confirmed"] == 0
        assert stats["failed_chunks"] == 1
        rows = db.query(QshalaTag).filter(QshalaTag.question_id.in_([q.id for q in qs])).all()
        assert all(r.status == "draft" for r in rows)            # all in the review queue
    finally:
        db.close()
        _cleanup(doc_id)


def test_dedup_retries_once_on_stale_connection_and_completes(monkeypatch):
    """Simulate Neon dropping the connection during the dedup SELECT: the pipeline must roll back,
    retry once on a fresh transaction, and finish the deck (processing_status COMPLETED)."""
    from sqlalchemy.exc import OperationalError
    from backend.app.services.deduplication.deduplicator import Deduplicator
    from backend.app.services.ingestion.cancellation import purge_document
    import test_v6_pipeline as v6

    original = Deduplicator.deduplicate_batch
    state = {"raised": False}

    def flaky_dedup(self, *a, **k):
        if not state["raised"]:
            state["raised"] = True
            raise OperationalError("SELECT ... content_hash IN (...)", {},
                                   Exception("terminating connection due to idle-in-transaction timeout"))
        return original(self, *a, **k)

    monkeypatch.setattr(Deduplicator, "deduplicate_batch", flaky_dedup)

    doc = v6._ingest("2022 Stale Conn Quiz.pptx", uuid.uuid4().hex[:8])
    db = SessionLocal()
    try:
        d = db.query(Document).filter(Document.id == doc).first()
        assert d is not None and d.processing_status == "COMPLETED"   # recovered, not FAILED
        assert state["raised"] is True                                 # the failure really happened
        assert db.query(Question).filter(Question.document_id == doc).count() >= 1
    finally:
        purge_document(db, doc)
        db.close()


def test_recent_human_exemplars_reads_confirmed_human_tags():
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        qs = _make_questions(db, doc_id, 1)
        db.add(QshalaTag(question_id=qs[0].id, taxonomy_version="v6", source="HUMAN",
                         status="confirmed", topic_l1="Sports", subtopic_l2="Cricket", confidence=1.0))
        db.commit()
        ex = qshala_batch.recent_human_exemplars(db)
        assert any(e["theme"] == "Sports" and e["subtopic"] == "Cricket" for e in ex)
    finally:
        db.close()
        _cleanup(doc_id)
