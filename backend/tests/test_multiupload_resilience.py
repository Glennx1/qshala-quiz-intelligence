"""Regression test suite for Multi-Deck Upload Resiliency & API Hardening (F1 - F7).
Asserts that all six backend failure modes and client session behaviors are permanently verified.
"""
import asyncio
from datetime import datetime, timezone, timedelta
import uuid
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.job import IngestionJob
from backend.app.models.upload_batch import UploadBatch
from backend.app.models.upload_session import UploadSession
from backend.app.services.ingestion import upload_queue as uq
from backend.app.services.ingestion.job_trigger import IngestionJobTriggerError


client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_test_state():
    db = SessionLocal()
    try:
        db.query(UploadSession).delete(synchronize_session=False)
        db.query(IngestionJob).delete(synchronize_session=False)
        db.query(UploadBatch).delete(synchronize_session=False)
        db.query(Document).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(UploadSession).delete(synchronize_session=False)
        db.query(IngestionJob).delete(synchronize_session=False)
        db.query(UploadBatch).delete(synchronize_session=False)
        db.query(Document).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _mk_doc(db, status="PROCESSING"):
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        filename=f"{doc_id}.pptx",
        title="Sample Deck",
        year=2024,
        file_type="pptx",
        storage_path=f"storage/uploads/{doc_id}.pptx",
        file_size_bytes=1024,
        processing_status=status
    )
    db.add(doc)
    db.commit()
    return doc_id


def test_f1_dead_worker_reaper_frees_slot_after_8_min(monkeypatch):
    """F1: If a worker terminates without terminal status, reaper marks it FAILED after 8m,
    allowing the next queued deck to claim the concurrency slot."""
    db = SessionLocal()
    try:
        # Create dead job that was updated 9 minutes ago in PROCESSING
        d1 = _mk_doc(db, "PROCESSING")
        job1 = IngestionJob(
            id=str(uuid.uuid4()),
            source_type="MANUAL_UPLOAD",
            filename="deck1.pptx",
            status="PROCESSING",
            document_id=d1,
            current_step="5. Reading question images",
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=9),
        )
        db.add(job1)

        # Create queued job waiting for slot
        d2 = _mk_doc(db, "QUEUED")
        job2 = IngestionJob(
            id=str(uuid.uuid4()),
            source_type="MANUAL_UPLOAD",
            filename="deck2.pptx",
            status="PENDING",
            document_id=d2,
            current_step="Queued",
            updated_at=datetime.now(timezone.utc),
        )
        db.add(job2)
        db.commit()

        # Reaper should reclaim job1
        reaped = uq.reap_dead_workers(db)
        assert reaped == 1

        db.refresh(job1)
        assert job1.status == "FAILED"
        assert "no progress for over 8 min" in (job1.error_message or "").lower()

        # Now dispatch_available should be able to run job2
        class MockPipeline:
            async def run(self, doc_id):
                with SessionLocal() as s:
                    doc = s.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.processing_status = "COMPLETED"
                    s.commit()

        monkeypatch.setattr("backend.app.services.ingestion.pipeline.IngestionPipeline", MockPipeline)

        dispatched = asyncio.run(uq.dispatch_available())
        assert dispatched == 1
        db.refresh(job2)
        assert job2.status in ("PROCESSING", "COMPLETED")
    finally:
        db.close()


def test_f2_transient_trigger_error_backs_off_without_burning_queue():
    """F2: Transient Cloud Run trigger error (429/503) does not burn the remaining queued jobs."""
    db = SessionLocal()
    try:
        batch = UploadBatch(id="batch_f2", total_expected=3, items=[])
        db.add(batch)

        jobs = []
        for i in range(3):
            d = _mk_doc(db, "QUEUED")
            j = IngestionJob(
                id=str(uuid.uuid4()),
                source_type="MANUAL_UPLOAD",
                filename=f"deck_{i}.pptx",
                status="PENDING",
                batch_id=batch.id,
                client_item_id=f"cid_{i}",
                document_id=d,
                current_step="Queued",
            )
            db.add(j)
            jobs.append(j)
        db.commit()

        # Simulate transient error on Cloud Run trigger
        with patch("backend.app.services.ingestion.job_trigger.trigger_ingestion_job",
                   side_effect=IngestionJobTriggerError("429 ResourceExhausted", transient=True)):
            dispatched = asyncio.run(uq.dispatch_available(force_cloud_run_job=True))

            assert dispatched == 1  # 1 attempted, caught transient error
            for j in jobs:
                db.refresh(j)

            # Job 0 received backoff retry, but NOT marked FAILED
            assert jobs[0].status == "PENDING"
            assert (jobs[0].retry_count or 0) == 1

            # Sibling jobs 1 and 2 were NOT marked FAILED or burned
            assert jobs[1].status == "PENDING"
            assert (jobs[1].retry_count or 0) == 0
            assert jobs[2].status == "PENDING"
            assert (jobs[2].retry_count or 0) == 0
    finally:
        db.close()


def test_f3_abandoned_batch_ignored_after_5_min_without_heartbeat():
    """F3: Batches with un-uploaded items (>5 min without heartbeat) are ignored as abandoned."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Abandoned batch: created 10 min ago, no heartbeat, waiting item
        batch_old = UploadBatch(
            id="batch_old",
            total_expected=1,
            items=[{"client_item_id": "c1", "filename": "old.pptx"}],
            created_at=now - timedelta(minutes=10),
            last_seen_at=now - timedelta(minutes=10),
        )
        db.add(batch_old)
        db.commit()

        # Active lookup should treat batch_old as abandoned
        res = client.get("/api/v1/jobs/upload-batches/active")
        assert res.status_code == 200
        assert res.json()["batch_id"] is None

        # Fresh batch with recent heartbeat is recognized
        batch_fresh = UploadBatch(
            id="batch_fresh",
            total_expected=1,
            items=[{"client_item_id": "c2", "filename": "fresh.pptx"}],
            created_at=now,
            last_seen_at=now,
        )
        db.add(batch_fresh)
        db.commit()

        res2 = client.get("/api/v1/jobs/upload-batches/active")
        assert res2.status_code == 200
        assert res2.json()["batch_id"] == "batch_fresh"

        # Heartbeat endpoint keeps batch active
        hb_res = client.post(f"/api/v1/jobs/upload-batch/{batch_fresh.id}/heartbeat")
        assert hb_res.status_code == 200
        assert hb_res.json()["status"] == "OK"
    finally:
        db.close()


def test_f4_cancel_running_job_transitions_to_cancelling_and_holds_slot(monkeypatch):
    """F4: Cancelling a running deck sets CANCELLING and preserves the concurrency slot
    until the worker actually unwinds, preventing two worker containers from overlapping."""
    db = SessionLocal()
    try:
        d1 = _mk_doc(db, "PROCESSING")
        job1 = IngestionJob(
            id=str(uuid.uuid4()),
            source_type="MANUAL_UPLOAD",
            filename="running.pptx",
            status="PROCESSING",
            document_id=d1,
            current_step="Processing",
        )
        db.add(job1)

        d2 = _mk_doc(db, "QUEUED")
        job2 = IngestionJob(
            id=str(uuid.uuid4()),
            source_type="MANUAL_UPLOAD",
            filename="queued.pptx",
            status="PENDING",
            document_id=d2,
            current_step="Queued",
        )
        db.add(job2)
        db.commit()

        # Cancel job1
        cancel_res = client.post(f"/api/v1/jobs/{job1.id}/cancel")
        assert cancel_res.status_code == 200

        db.refresh(job1)
        # Status must be CANCELLING (holding slot)
        assert job1.status == "CANCELLING"
        doc1 = db.query(Document).filter(Document.id == d1).first()
        assert doc1.cancel_requested is True

        class MockPipeline:
            async def run(self, doc_id):
                with SessionLocal() as s:
                    doc = s.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.processing_status = "COMPLETED"
                    s.commit()

        monkeypatch.setattr("backend.app.services.ingestion.pipeline.IngestionPipeline", MockPipeline)

        # Sibling job2 must NOT be dispatched yet
        dispatched = asyncio.run(uq.dispatch_available())
        assert dispatched == 0
        db.refresh(job2)
        assert job2.status == "PENDING"

        # Once worker completes cancel and marks CANCELLED, slot opens
        job1.status = "CANCELLED"
        db.commit()

        dispatched = asyncio.run(uq.dispatch_available())
        assert dispatched == 1
        db.refresh(job2)
        assert job2.status in ("PROCESSING", "COMPLETED")
    finally:
        db.close()


def test_f5_get_batch_status_is_read_only_with_zero_dispatch_side_effects():
    """F5: GET /upload-batch/{id} is strictly read-only and never triggers dispatch."""
    db = SessionLocal()
    try:
        batch = UploadBatch(id="batch_f5", total_expected=1, items=[])
        db.add(batch)
        d = _mk_doc(db, "QUEUED")
        job = IngestionJob(
            id=str(uuid.uuid4()),
            source_type="MANUAL_UPLOAD",
            filename="deck.pptx",
            status="PENDING",
            batch_id=batch.id,
            client_item_id="cid_f5",
            document_id=d,
            current_step="Queued",
        )
        db.add(job)
        db.commit()

        with patch.object(uq, "dispatch_available") as mock_dispatch:
            res = client.get(f"/api/v1/jobs/upload-batch/{batch.id}")
            assert res.status_code == 200
            mock_dispatch.assert_not_called()
    finally:
        db.close()


def test_f6_chunked_upload_session_db_backed_and_typed_statuses(monkeypatch):
    """F6: Chunked upload in cloud_run_job mode uses DB session:
    - Out-of-order chunk 1 before 0 returns 425 slice_not_ready (not 409).
    - Repeated slice returns idempotent 200.
    - Explicit delete/cancel sets cancelled and returns 409 upload_cancelled.
    """
    monkeypatch.setattr(settings, "INGESTION_MODE", "cloud_run_job")

    mock_r2 = MagicMock()
    mock_r2.is_configured = True
    mock_r2.create_multipart_upload.return_value = "r2_up_123"
    mock_r2.upload_part.return_value = "etag_part"
    monkeypatch.setattr("backend.app.services.storage.r2_storage.get_r2_service", lambda: mock_r2)

    upload_id = str(uuid.uuid4())

    # Out of order slice 1 before 0 -> 425
    res_ooo = client.post(
        "/api/v1/documents/upload-chunk",
        data={
            "upload_id": upload_id,
            "chunk_index": 1,
            "total_chunks": 3,
            "filename": "f6_test.pptx",
        },
        files={"chunk": ("chunk_1.bin", b"slice1_bytes")},
    )
    assert res_ooo.status_code == 425
    assert res_ooo.json().get("detail", {}).get("code") == "slice_not_ready"

    # Slice 0 succeeds
    res_0 = client.post(
        "/api/v1/documents/upload-chunk",
        data={
            "upload_id": upload_id,
            "chunk_index": 0,
            "total_chunks": 3,
            "filename": "f6_test.pptx",
        },
        files={"chunk": ("chunk_0.bin", b"slice0_bytes")},
    )
    assert res_0.status_code == 200
    assert res_0.json().get("status") == "CHUNK_RECEIVED"

    # Repeated slice 0 is idempotent 200
    res_0_repeat = client.post(
        "/api/v1/documents/upload-chunk",
        data={
            "upload_id": upload_id,
            "chunk_index": 0,
            "total_chunks": 3,
            "filename": "f6_test.pptx",
        },
        files={"chunk": ("chunk_0.bin", b"slice0_bytes")},
    )
    assert res_0_repeat.status_code == 200
    assert res_0_repeat.json().get("status") == "CHUNK_RECEIVED"

    # Explicit cancel via DELETE /upload-chunk/{upload_id}
    res_cancel = client.delete(f"/api/v1/documents/upload-chunk/{upload_id}")
    assert res_cancel.status_code == 200

    # Next slice after cancel returns 409 upload_cancelled
    res_after_cancel = client.post(
        "/api/v1/documents/upload-chunk",
        data={
            "upload_id": upload_id,
            "chunk_index": 1,
            "total_chunks": 3,
            "filename": "f6_test.pptx",
        },
        files={"chunk": ("chunk_1.bin", b"slice1_bytes")},
    )
    assert res_after_cancel.status_code == 409
    assert res_after_cancel.json().get("detail", {}).get("code") == "upload_cancelled"
