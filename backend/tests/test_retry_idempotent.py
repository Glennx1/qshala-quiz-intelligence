"""A retried ingestion run does not stack a second copy on the first attempt's leftovers (audit M2)."""
import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document, Slide
from backend.app.models.question import Question
from backend.app.services.ingestion import pipeline as pipeline_mod
from backend.app.services.ingestion.pipeline import (
    IngestionPipeline, INGESTION_STATUS_REGISTRY, clear_partial_ingestion,
)

from test_v6_pipeline import FakeGemini
from test_dedup_before_ai import RecordingEmbedder
from test_vision_local_copy import _png, _deck_with_picture, CapturingLLM


@pytest.fixture(autouse=True)
def _remove_mirrored_media():
    mirror = Path(__file__).resolve().parents[2] / "frontend" / "public" / "static" / "slides"
    before = {p.name for p in mirror.iterdir()} if mirror.exists() else set()
    yield
    if mirror.exists():
        for p in mirror.iterdir():
            if p.name not in before:
                shutil.rmtree(p, ignore_errors=True)


def _stale_rows(db, doc_id, n=2):
    s = Slide(id=str(uuid.uuid4()), document_id=doc_id, slide_number=1, slide_type="QUESTION")
    db.add(s)
    db.flush()
    for i in range(n):
        db.add(Question(id=str(uuid.uuid4()), document_id=doc_id, slide_id=s.id, question_text=f"stale {uuid.uuid4()} {i}?",
                        answer="x", topic="General", content_hash=uuid.uuid4().hex))
    db.commit()


def _make_doc(status, tmp_path, with_deck=True):
    doc_id = str(uuid.uuid4())
    dest = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if with_deck:
        img = tmp_path / "p.png"
        _png(img)
        _deck_with_picture(dest, img)
    db = SessionLocal()
    try:
        db.add(Document(id=doc_id, filename="r.pptx", title="r", year=2022, file_type="pptx", storage_path=str(dest),
                        file_size_bytes=1, processing_status=status))
        db.commit()
        _stale_rows(db, doc_id)
    finally:
        db.close()
    return doc_id


def _count(doc_id, model):
    db = SessionLocal()
    try:
        return db.query(model).filter(model.document_id == doc_id).count()
    finally:
        db.close()


def test_helper_clears_unfinished_documents_but_never_completed_ones(tmp_path):
    for status, expect in (("PROCESSING", 0), ("FAILED", 0), ("COMPLETED", 2)):
        doc_id = _make_doc(status, tmp_path, with_deck=False)
        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == doc_id).one()
            cleared = clear_partial_ingestion(db, doc)
        finally:
            db.close()
        assert _count(doc_id, Question) == expect, status
        assert cleared == (2 if expect == 0 else 0)


def _run(doc_id):
    pipe = IngestionPipeline()
    pipe.qshala_tagger.provider = FakeGemini()
    pipe.qshala_tagger.rpm = 0
    pipe.embedding_provider = RecordingEmbedder()
    pipe.llm_provider = CapturingLLM()
    asyncio.run(pipe.run(doc_id))
    return INGESTION_STATUS_REGISTRY[doc_id]


def test_retry_after_a_failed_attempt_ends_with_exactly_one_copy(tmp_path):
    doc_id = _make_doc("PROCESSING", tmp_path)          # the first attempt died after committing 2 stale questions
    status = _run(doc_id)
    assert status["status"] == "COMPLETED", status
    assert _count(doc_id, Question) == 1                # the deck's one real question; the stale two are gone


def test_switch_off_keeps_old_behaviour(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "RESET_PARTIAL_ON_RETRY", False)
    doc_id = _make_doc("PROCESSING", tmp_path)
    assert _run(doc_id)["status"] == "COMPLETED"
    assert _count(doc_id, Question) == 3                # 2 stale + 1 new, as before
