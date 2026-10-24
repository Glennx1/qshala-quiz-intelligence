"""The ingestion pipeline must not hold a DB transaction across the AI stages, and must
survive a connection dropped mid-run. These two tests lock in the fix for the recurring
IdleInTransactionSessionTimeout."""
import asyncio
import uuid
from pathlib import Path
import pytest
from pptx import Presentation
from pptx.util import Inches

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document, Slide
from backend.app.models.question import Question
from backend.app.models.question_meta import DeckMetadata
from backend.app.services.ingestion.pipeline import IngestionPipeline, _ensure_clean


def _build_test_deck(path: Path, tag: str, n: int = 2):
    prs = Presentation()
    blank = prs.slide_layouts[6]

    def add(text):
        s = prs.slides.add_slide(blank)
        tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4))
        tb.text_frame.text = text

    add(f"Quiz Header {tag}")
    for i in range(1, n + 1):
        add(f"QUESTION {i}\nWhat is the test question number {i} for {tag}?")
        add(f"ANSWER {i}\nAnswer: Test Answer {tag} {i}\n\nContext for {tag} {i}.")
    prs.save(str(path))


@pytest.fixture
def seeded_document_id(tmp_path):
    tag = uuid.uuid4().hex[:8]
    dest = settings.UPLOAD_DIR / f"test_lifecycle_{tag}.pptx"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _build_test_deck(dest, tag, n=2)

    db = SessionLocal()
    try:
        doc = Document(
            id=str(uuid.uuid4()),
            filename=f"2024 Test Lifecycle Quiz {tag}.pptx",
            title=f"Test Lifecycle Quiz {tag}",
            file_type="pptx",
            storage_path=str(dest),
            file_size_bytes=dest.stat().st_size,
            processing_status="PENDING",
            slide_count=0,
            question_count=0,
            year=2024,
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    yield doc_id

    # Cleanup
    try:
        if dest.exists():
            dest.unlink()
    except Exception:
        pass
    db = SessionLocal()
    try:
        db.query(Question).filter(Question.document_id == doc_id).delete()
        db.query(Slide).filter(Slide.document_id == doc_id).delete()
        db.query(DeckMetadata).filter(DeckMetadata.document_id == doc_id).delete()
        db.query(Document).filter(Document.id == doc_id).delete()
        db.commit()
    finally:
        db.close()


def test_ensure_clean_commits_open_transaction():
    db = SessionLocal()
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))   # opens a transaction
        assert db.in_transaction()
        _ensure_clean(db, "test")
        assert not db.in_transaction()                          # invariant restored
    finally:
        db.close()


class FakeGemini:
    async def generate_json_schema(self, *args, **kwargs):
        return {
            "results": [
                {"n": 1, "topic_l1": "General Knowledge", "subtopic_l2": "Trivia", "confidence": 0.9, "fit": "good"},
                {"n": 2, "topic_l1": "General Knowledge", "subtopic_l2": "Trivia", "confidence": 0.9, "fit": "good"},
            ]
        }, {"in": 10, "out": 10, "think": 0, "cached": 0}


@pytest.mark.anyio
async def test_pipeline_survives_dropped_connection(monkeypatch, seeded_document_id):
    """Drop the connection during the AI phase; the job must still complete and save questions.
    `seeded_document_id` is a fixture that inserts a small deck's Document + storage file.
    Replace vision/embedding providers with fakes so the test is offline."""
    pipe = IngestionPipeline()
    monkeypatch.setattr("backend.app.services.ingestion.pipeline.is_image_dependent_question", lambda q: False)
    pipe.qshala_tagger.provider = FakeGemini()
    pipe.qshala_tagger.rpm = 0

    # force the embedding stage to invalidate the pool (simulates Neon killing the idle conn)
    real = pipe.embedding_provider.get_embeddings

    async def drop_then_embed(texts):
        SessionLocal().get_bind().dispose()         # throw away pooled connections mid-run
        try:
            return await real(texts)
        except Exception:
            return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(pipe.embedding_provider, "get_embeddings", drop_then_embed)

    await pipe.run(seeded_document_id)

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == seeded_document_id).first()
        assert doc.processing_status == "COMPLETED"
        assert doc.question_count >= 1
    finally:
        db.close()
