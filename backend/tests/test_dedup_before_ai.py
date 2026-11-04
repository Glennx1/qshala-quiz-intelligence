"""Exact repeats skip the AI stages but are still recorded as repeats (audit Q4)."""
import asyncio
import hashlib
import uuid
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.models.question_meta import QuestionRepeat
from backend.app.services.ingestion import pipeline as pipeline_mod
from backend.app.services.ingestion.pipeline import IngestionPipeline, INGESTION_STATUS_REGISTRY

from test_v6_pipeline import FakeGemini  # same fake tagger the other pipeline tests use


def _vec(text: str):
    h = hashlib.sha256(text.encode()).digest()
    return [((h[i % 32] + i) % 97) / 97.0 for i in range(768)]


class RecordingEmbedder:
    def __init__(self):
        self.texts = []

    async def get_embeddings(self, texts):
        self.texts.extend(texts)
        return [_vec(t) for t in texts]

    async def get_embedding(self, text):
        return _vec(text)


class CountingLLM:
    calls = 0

    async def describe_image(self, *a, **k):
        CountingLLM.calls += 1
        return "a picture"


def _deck(path: Path, items):
    prs = Presentation()
    blank = prs.slide_layouts[6]

    def add(text):
        s = prs.slides.add_slide(blank)
        tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4))
        tb.text_frame.text = text

    add("QShala Quest dedup")
    add("ROUND 1\nDirect questions")
    for n, (q, a) in enumerate(items, start=1):
        add(f"QUESTION {n}\n{q}")
        add(f"ANSWER {n}\nAnswer: {a}\n\nExplanation & Context:\nBecause {a}.")
    prs.save(str(path))


def _ingest(items, embedder, name="dedup.pptx"):
    dest = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _deck(dest, items)
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Document(id=doc_id, filename=name, title=name, year=2022, file_type="pptx",
                        storage_path=str(dest), file_size_bytes=dest.stat().st_size, processing_status="PROCESSING"))
        db.commit()
    finally:
        db.close()
    pipe = IngestionPipeline()
    pipe.qshala_tagger.provider = FakeGemini()
    pipe.qshala_tagger.rpm = 0
    pipe.embedding_provider = embedder
    pipe.llm_provider = CountingLLM()
    asyncio.run(pipe.run(doc_id))
    assert INGESTION_STATUS_REGISTRY[doc_id]["status"] == "COMPLETED", INGESTION_STATUS_REGISTRY[doc_id]
    return doc_id


def _items(tag, numbers):
    return [(f"Which unique {tag} river number {i} flows past city {tag}{i}?", f"River {tag} {i}") for i in numbers]


def test_reupload_skips_embedding_but_still_records_repeats():
    tag = uuid.uuid4().hex[:8]
    first = RecordingEmbedder()
    doc1 = _ingest(_items(tag, [1, 2, 3, 4]), first)
    assert len(first.texts) == 4

    second = RecordingEmbedder()
    doc2 = _ingest(_items(tag, [1, 2, 3, 4]), second)
    assert second.texts == []                                   # nothing was embedded for exact repeats

    db = SessionLocal()
    try:
        assert db.query(Question).filter(Question.document_id == doc2).count() == 0
        originals = [q.id for q in db.query(Question).filter(Question.document_id == doc1).all()]
        reps = db.query(QuestionRepeat).filter(QuestionRepeat.document_id == doc2).all()
        assert sorted(r.question_id for r in reps) == sorted(originals)      # every repeat still tracked
        for q in db.query(Question).filter(Question.document_id == doc1).all():
            assert doc2 in [p["document_id"] for p in (q.provenance_decks or [])]
            assert q.occurrence_count == 2
    finally:
        db.close()


def test_mixed_deck_keeps_new_questions_with_their_own_embeddings(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    doc1 = _ingest(_items(tag, [1, 2]), RecordingEmbedder())

    emb = RecordingEmbedder()
    # repeats first, then new ones: the new ones are NOT at the start, so index alignment is exercised
    doc2 = _ingest(_items(tag, [1, 2, 3, 4]), emb)
    assert len(emb.texts) == 2                                  # only the two new questions were embedded

    db = SessionLocal()
    try:
        qs = db.query(Question).filter(Question.document_id == doc2).all()
        assert len(qs) == 2
        for q in qs:
            text = next(t for t in emb.texts if q.question_text in t)
            stored = list(q.embedding)
            assert len(stored) == 768
            assert all(abs(a - b) < 1e-6 for a, b in zip(stored, _vec(text)))   # right vector on the right question
        assert db.query(QuestionRepeat).filter(QuestionRepeat.document_id == doc2).count() == 2
    finally:
        db.close()


def test_flag_off_restores_old_order(monkeypatch):
    monkeypatch.setattr(pipeline_mod, "DEDUP_BEFORE_AI", False)
    tag = uuid.uuid4().hex[:8]
    _ingest(_items(tag, [1, 2]), RecordingEmbedder())
    emb = RecordingEmbedder()
    _ingest(_items(tag, [1, 2]), emb)
    assert len(emb.texts) == 2                                  # old behaviour: repeats were embedded anyway
