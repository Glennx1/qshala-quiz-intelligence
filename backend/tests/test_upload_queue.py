"""Upload queue: enqueue, serial processing, crash reconcile, safe retry.

The point of the queue is that decks ingest ONE AT A TIME (memory-safe on a small host) and that an
interrupted job never silently re-runs in a way that duplicates data. These tests lock that in using
a stubbed pipeline, so they run offline and fast.
"""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import SessionLocal
from backend.app.models.document import Document, Slide
from backend.app.models.job import IngestionJob
from backend.app.models.question import Question
from backend.app.services.ingestion import upload_queue as uq


@pytest.fixture(autouse=True)
def _isolate_queue():
    """The queue is global state in the shared test DB; clear any MANUAL_UPLOAD jobs left by other
    tests so each test here controls the queue exactly."""
    def wipe():
        db = SessionLocal()
        try:
            db.query(IngestionJob).filter(IngestionJob.source_type == "MANUAL_UPLOAD").delete(
                synchronize_session=False)
            db.commit()
        finally:
            db.close()
    wipe()
    yield
    wipe()


def _mk_doc(db):
    doc_id = str(uuid.uuid4())
    db.add(Document(id=doc_id, filename=f"{doc_id}.pptx", title="t", year=2022, file_type="pptx",
                    storage_path="x", file_size_bytes=1, processing_status="PROCESSING"))
    db.commit()
    return doc_id


def _cleanup(*doc_ids):
    db = SessionLocal()
    try:
        for d in doc_ids:
            db.query(IngestionJob).filter(IngestionJob.document_id == d).delete(synchronize_session=False)
            db.query(Slide).filter(Slide.document_id == d).delete(synchronize_session=False)
            db.query(Question).filter(Question.document_id == d).delete(synchronize_session=False)
            db.query(Document).filter(Document.id == d).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_enqueue_sets_doc_queued_and_creates_pending_job():
    db = SessionLocal()
    doc_id = _mk_doc(db)
    try:
        job = uq.enqueue_upload(db, document_id=doc_id, filename="t.pptx")
        assert job.status == "PENDING" and job.source_type == "MANUAL_UPLOAD"
        assert db.query(Document).get(doc_id).processing_status == "QUEUED"
    finally:
        db.close()
        _cleanup(doc_id)


def test_claim_is_serial_only_one_processing_at_a_time():
    db = SessionLocal()
    a, b = _mk_doc(db), _mk_doc(db)
    try:
        uq.enqueue_upload(db, document_id=a, filename="a.pptx")
        uq.enqueue_upload(db, document_id=b, filename="b.pptx")
        first = uq.claim_next(db)
        assert first is not None and first.document_id == a      # oldest first
        # with one already PROCESSING, the next claim must return nothing (cap = 1)
        assert uq.claim_next(db) is None
        first.status = "COMPLETED"; db.commit()
        second = uq.claim_next(db)
        assert second is not None and second.document_id == b    # now the next one is claimable
    finally:
        db.close()
        _cleanup(a, b)


def test_process_one_runs_pipeline_and_marks_completed(monkeypatch):
    db = SessionLocal()
    doc_id = _mk_doc(db)
    try:
        uq.enqueue_upload(db, document_id=doc_id, filename="t.pptx")
    finally:
        db.close()

    ran = {"doc": None}

    class StubPipeline:
        async def run(self, document_id):
            ran["doc"] = document_id
            s = SessionLocal()
            try:
                d = s.query(Document).get(document_id)
                d.processing_status = "COMPLETED"; d.question_count = 3
                s.commit()
            finally:
                s.close()

    monkeypatch.setattr("backend.app.services.ingestion.pipeline.IngestionPipeline", StubPipeline)
    try:
        assert asyncio.run(uq.process_one()) is True
        assert ran["doc"] == doc_id
        db = SessionLocal()
        job = db.query(IngestionJob).filter(IngestionJob.document_id == doc_id).first()
        assert job.status == "COMPLETED" and job.completed_at is not None
        db.close()
        # nothing left to process
        assert asyncio.run(uq.process_one()) is False
    finally:
        _cleanup(doc_id)


def test_process_one_marks_failed_when_pipeline_does_not_complete(monkeypatch):
    db = SessionLocal()
    doc_id = _mk_doc(db)
    try:
        uq.enqueue_upload(db, document_id=doc_id, filename="t.pptx")
    finally:
        db.close()

    class BoomPipeline:
        async def run(self, document_id):
            raise RuntimeError("out of memory")

    monkeypatch.setattr("backend.app.services.ingestion.pipeline.IngestionPipeline", BoomPipeline)
    try:
        assert asyncio.run(uq.process_one()) is True
        db = SessionLocal()
        job = db.query(IngestionJob).filter(IngestionJob.document_id == doc_id).first()
        assert job.status == "FAILED" and job.error_message
        db.close()
    finally:
        _cleanup(doc_id)


def test_reconcile_marks_interrupted_jobs_failed():
    db = SessionLocal()
    doc_id = _mk_doc(db)
    try:
        job = uq.enqueue_upload(db, document_id=doc_id, filename="t.pptx")
        job.status = "PROCESSING"; db.commit()          # simulate a crash mid-run
        uq.reconcile_on_startup(db)
        db.refresh(job)
        assert job.status == "FAILED"
        assert db.query(Document).get(doc_id).processing_status == "FAILED"
    finally:
        db.close()
        _cleanup(doc_id)


def test_requeue_purges_partial_artifacts_and_resets():
    db = SessionLocal()
    doc_id = _mk_doc(db)
    try:
        job = uq.enqueue_upload(db, document_id=doc_id, filename="t.pptx")
        # simulate partial output from a failed attempt
        db.add(Slide(id=str(uuid.uuid4()), document_id=doc_id, slide_number=1, slide_type="QUESTION",
                     title="", extracted_text="q", speaker_notes="", image_paths=[], has_images=False,
                     metadata_json={}))
        db.add(Question(id=str(uuid.uuid4()), document_id=doc_id, question_text="q", answer="a",
                        topic="Uncategorised"))
        job.status = "FAILED"; db.commit()

        uq.requeue_job(db, job)
        db.refresh(job)
        assert job.status == "PENDING" and job.retry_count == 1
        assert db.query(Document).get(doc_id).processing_status == "QUEUED"
        assert db.query(Slide).filter(Slide.document_id == doc_id).count() == 0      # artifacts purged
        assert db.query(Question).filter(Question.document_id == doc_id).count() == 0
        assert db.query(Document).get(doc_id) is not None                             # doc kept
    finally:
        db.close()
        _cleanup(doc_id)
