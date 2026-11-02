"""Tests for Phase M1: upload queue concurrency cap, Cloud Run Job dispatcher, worker terminal status, and heartbeat.
"""
import asyncio
from datetime import datetime, timezone, timedelta
import uuid

import pytest

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.job import IngestionJob
from backend.app.services.ingestion import upload_queue as uq
from backend import worker


@pytest.fixture(autouse=True)
def _isolate_queue():
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


def _mk_doc(db, status="PROCESSING"):
    doc_id = str(uuid.uuid4())
    db.add(Document(id=doc_id, filename=f"{doc_id}.pptx", title="t", year=2022, file_type="pptx",
                    storage_path="x", file_size_bytes=1, processing_status=status))
    db.commit()
    return doc_id


def _cleanup(*doc_ids):
    db = SessionLocal()
    try:
        for d in doc_ids:
            db.query(IngestionJob).filter(IngestionJob.document_id == d).delete(synchronize_session=False)
            db.query(Document).filter(Document.id == d).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_claim_next_respects_max_concurrency_1(monkeypatch):
    monkeypatch.setattr(settings, "INGESTION_MAX_CONCURRENCY", 1)
    db = SessionLocal()
    a, b = _mk_doc(db), _mk_doc(db)
    try:
        uq.enqueue_upload(db, document_id=a, filename="a.pptx")
        uq.enqueue_upload(db, document_id=b, filename="b.pptx")

        j1 = uq.claim_next(db)
        assert j1 is not None and j1.document_id == a
        # Capacity is 1, so second claim must return None while j1 is PROCESSING
        assert uq.claim_next(db) is None

        j1.status = "COMPLETED"
        db.commit()

        j2 = uq.claim_next(db)
        assert j2 is not None and j2.document_id == b
    finally:
        db.close()
        _cleanup(a, b)


def test_claim_next_respects_max_concurrency_2(monkeypatch):
    monkeypatch.setattr(settings, "INGESTION_MAX_CONCURRENCY", 2)
    db = SessionLocal()
    a, b, c = _mk_doc(db), _mk_doc(db), _mk_doc(db)
    try:
        uq.enqueue_upload(db, document_id=a, filename="a.pptx")
        uq.enqueue_upload(db, document_id=b, filename="b.pptx")
        uq.enqueue_upload(db, document_id=c, filename="c.pptx")

        j1 = uq.claim_next(db)
        assert j1 is not None and j1.document_id == a

        # Capacity is 2, so second claim succeeds!
        j2 = uq.claim_next(db)
        assert j2 is not None and j2.document_id == b

        # Now 2 are PROCESSING, so third claim must return None
        assert uq.claim_next(db) is None

        j1.status = "COMPLETED"
        db.commit()

        j3 = uq.claim_next(db)
        assert j3 is not None and j3.document_id == c
    finally:
        db.close()
        _cleanup(a, b, c)


def test_worker_write_terminal_job_status_completed():
    db = SessionLocal()
    doc_id = _mk_doc(db, status="PROCESSING")
    job = uq.enqueue_upload(db, document_id=doc_id, filename="test.pptx")
    job.status = "PROCESSING"
    # Worker finishes pipeline -> doc marked COMPLETED
    doc = db.query(Document).filter(Document.id == doc_id).first()
    doc.processing_status = "COMPLETED"
    db.commit()
    db.close()

    try:
        worker._write_terminal_job_status(doc_id)
        verify_db = SessionLocal()
        try:
            saved_job = verify_db.query(IngestionJob).filter(IngestionJob.document_id == doc_id).first()
            assert saved_job.status == "COMPLETED"
            assert saved_job.current_step == "DONE"
            assert saved_job.completed_at is not None
        finally:
            verify_db.close()
    finally:
        _cleanup(doc_id)


def test_worker_write_terminal_job_status_cancelled():
    db = SessionLocal()
    doc_id = _mk_doc(db, status="PROCESSING")
    job = uq.enqueue_upload(db, document_id=doc_id, filename="test.pptx")
    job.status = "PROCESSING"
    # Cancelled while processing
    doc = db.query(Document).filter(Document.id == doc_id).first()
    doc.processing_status = "CANCELLED"
    db.commit()
    db.close()

    try:
        worker._write_terminal_job_status(doc_id)
        verify_db = SessionLocal()
        try:
            saved_job = verify_db.query(IngestionJob).filter(IngestionJob.document_id == doc_id).first()
            assert saved_job.status == "CANCELLED"
            assert saved_job.completed_at is not None
        finally:
            verify_db.close()
    finally:
        _cleanup(doc_id)


def test_worker_write_terminal_job_status_failed_with_error():
    db = SessionLocal()
    doc_id = _mk_doc(db, status="PROCESSING")
    job = uq.enqueue_upload(db, document_id=doc_id, filename="test.pptx")
    job.status = "PROCESSING"
    doc = db.query(Document).filter(Document.id == doc_id).first()
    doc.processing_status = "FAILED"
    doc.processing_error = "Deck extraction exploded"
    db.commit()
    db.close()

    try:
        worker._write_terminal_job_status(doc_id, error="Deck extraction exploded")
        verify_db = SessionLocal()
        try:
            saved_job = verify_db.query(IngestionJob).filter(IngestionJob.document_id == doc_id).first()
            assert saved_job.status == "FAILED"
            assert "Deck extraction exploded" in saved_job.error_message
        finally:
            verify_db.close()
    finally:
        _cleanup(doc_id)


def test_worker_write_terminal_job_status_no_job_no_op():
    # Calling on a document with no job should not raise
    worker._write_terminal_job_status("nonexistent-doc-id")


def test_dispatch_available_cloud_run_job_trigger_failure(monkeypatch):
    monkeypatch.setattr(settings, "INGESTION_MODE", "cloud_run_job")
    monkeypatch.setattr(settings, "INGESTION_MAX_CONCURRENCY", 1)

    def mock_trigger(doc_id):
        raise RuntimeError("Cloud Run API quota exceeded")

    monkeypatch.setattr("backend.app.services.ingestion.job_trigger.trigger_ingestion_job", mock_trigger)

    db = SessionLocal()
    doc_id = _mk_doc(db)
    try:
        job = uq.enqueue_upload(db, document_id=doc_id, filename="t.pptx")
        job_id = job.id
    finally:
        db.close()

    try:
        dispatched = asyncio.run(uq.dispatch_available())
        assert dispatched == 1

        check_db = SessionLocal()
        try:
            saved_job = check_db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
            assert saved_job.status == "FAILED"
            assert "Cloud Run API quota exceeded" in saved_job.error_message

            saved_doc = check_db.query(Document).filter(Document.id == doc_id).first()
            assert saved_doc.processing_status == "FAILED"
            assert "Cloud Run API quota exceeded" in saved_doc.processing_error
        finally:
            check_db.close()
    finally:
        _cleanup(doc_id)


def test_stale_reclaim_respects_fresh_heartbeat():
    db = SessionLocal()
    fresh_doc = _mk_doc(db)
    stale_doc = _mk_doc(db)
    now = datetime.now(timezone.utc)
    try:
        # Fresh job: updated 5 minutes ago
        fresh_job = IngestionJob(
            id=str(uuid.uuid4()),
            document_id=fresh_doc,
            filename="fresh.pptx",
            source_type="MANUAL_UPLOAD",
            status="PROCESSING",
            created_at=now - timedelta(minutes=60),
            updated_at=now - timedelta(minutes=5),
        )
        # Stale job: updated 35 minutes ago (> 30 min cutoff)
        stale_job = IngestionJob(
            id=str(uuid.uuid4()),
            document_id=stale_doc,
            filename="stale.pptx",
            source_type="MANUAL_UPLOAD",
            status="PROCESSING",
            created_at=now - timedelta(minutes=60),
            updated_at=now - timedelta(minutes=35),
        )
        db.add(fresh_job)
        db.add(stale_job)
        db.commit()

        # Run _reclaim_stale
        uq._reclaim_stale(db)

        # Fresh job must still be PROCESSING
        db.refresh(fresh_job)
        assert fresh_job.status == "PROCESSING"

        # Stale job must be reclaimed as FAILED
        db.refresh(stale_job)
        assert stale_job.status == "FAILED"
        assert "no progress" in stale_job.error_message.lower()
    finally:
        db.close()
        _cleanup(fresh_doc, stale_doc)
