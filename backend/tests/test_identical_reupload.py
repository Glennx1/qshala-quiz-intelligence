"""Byte-identical re-uploads are fingerprinted, and optionally skipped (audit Q5)."""
import asyncio
import shutil
import uuid

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.models.question_meta import QuestionRepeat
from backend.app.services.ingestion import pipeline as pipeline_mod
from backend.app.services.ingestion.pipeline import (
    IngestionPipeline, INGESTION_STATUS_REGISTRY, sha256_file,
)

from test_v6_pipeline import FakeGemini
from test_dedup_before_ai import RecordingEmbedder, CountingLLM, _deck, _items


def _register(path, name):
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Document(id=doc_id, filename=name, title=name, year=2022, file_type="pptx",
                        storage_path=str(path), file_size_bytes=path.stat().st_size, processing_status="PROCESSING"))
        db.commit()
    finally:
        db.close()
    return doc_id


def _run(doc_id, embedder):
    pipe = IngestionPipeline()
    pipe.qshala_tagger.provider = FakeGemini()
    pipe.qshala_tagger.rpm = 0
    pipe.embedding_provider = embedder
    pipe.llm_provider = CountingLLM()
    asyncio.run(pipe.run(doc_id))
    return INGESTION_STATUS_REGISTRY[doc_id]


def _two_identical_files():
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    a = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    _deck(a, _items(uuid.uuid4().hex[:8], [1, 2]))
    b = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    shutil.copyfile(a, b)
    assert sha256_file(str(a)) == sha256_file(str(b))
    return a, b


def test_default_records_hash_and_still_processes(monkeypatch):
    monkeypatch.setattr(pipeline_mod, "IDENTICAL_REUPLOAD_ACTION", "process")
    a, b = _two_identical_files()
    d1, d2 = _register(a, "one.pptx"), _register(b, "two.pptx")
    assert _run(d1, RecordingEmbedder())["status"] == "COMPLETED"
    reg2 = _run(d2, RecordingEmbedder())
    assert reg2["status"] == "COMPLETED"
    db = SessionLocal()
    try:
        h = sha256_file(str(a))
        assert db.query(Document).get(d1).file_sha256 == h and db.query(Document).get(d2).file_sha256 == h
        assert db.query(QuestionRepeat).filter(QuestionRepeat.document_id == d2).count() == 2   # unchanged behaviour
        assert any("byte-identical" in e["msg"] for e in reg2["events"])
    finally:
        db.close()


def test_skip_mode_completes_without_any_work(monkeypatch):
    monkeypatch.setattr(pipeline_mod, "IDENTICAL_REUPLOAD_ACTION", "skip")
    a, b = _two_identical_files()
    d1, d2 = _register(a, "one.pptx"), _register(b, "two.pptx")
    assert _run(d1, RecordingEmbedder())["status"] == "COMPLETED"
    emb = RecordingEmbedder()
    reg2 = _run(d2, emb)
    assert reg2["status"] == "COMPLETED" and "Skipped" in reg2["current_step"]
    assert emb.texts == []
    db = SessionLocal()
    try:
        doc2 = db.query(Document).get(d2)
        assert doc2.processing_status == "COMPLETED" and doc2.question_count == 0
        assert db.query(Question).filter(Question.document_id == d2).count() == 0
        assert db.query(Question).filter(Question.document_id == d1).count() == 2   # original untouched
    finally:
        db.close()


def test_different_files_are_never_skipped(monkeypatch):
    monkeypatch.setattr(pipeline_mod, "IDENTICAL_REUPLOAD_ACTION", "skip")
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    a = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    b = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    _deck(a, _items(uuid.uuid4().hex[:8], [1, 2]))
    _deck(b, _items(uuid.uuid4().hex[:8], [1, 2]))
    d1, d2 = _register(a, "one.pptx"), _register(b, "two.pptx")
    _run(d1, RecordingEmbedder())
    reg2 = _run(d2, RecordingEmbedder())
    assert reg2["status"] == "COMPLETED" and "Skipped" not in reg2["current_step"]
    db = SessionLocal()
    try:
        assert db.query(Question).filter(Question.document_id == d2).count() == 2
    finally:
        db.close()
