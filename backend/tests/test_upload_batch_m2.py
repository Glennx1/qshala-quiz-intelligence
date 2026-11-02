"""Tests for Phase M2: server-side upload batches, totals math, WAITING merge, active batch lookup, and cancel-pending.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.job import IngestionJob
from backend.app.models.upload_batch import UploadBatch
from backend.app.services.ingestion import upload_queue as uq


client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_queue_and_batches():
    def wipe():
        db = SessionLocal()
        try:
            db.query(IngestionJob).delete(synchronize_session=False)
            db.query(UploadBatch).delete(synchronize_session=False)
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


def test_batch_validation_25_cap_and_extension():
    # 0 files -> 400
    res = client.post("/api/v1/jobs/upload-batch", json={"files": []})
    assert res.status_code == 400

    # 26 files -> 400
    files_26 = [{"client_item_id": f"id_{i}", "filename": f"deck_{i}.pptx", "size_bytes": 100} for i in range(26)]
    res = client.post("/api/v1/jobs/upload-batch", json={"files": files_26})
    assert res.status_code == 400

    # Invalid extension -> 400
    bad_files = [{"client_item_id": "bad_1", "filename": "malicious.exe", "size_bytes": 100}]
    res = client.post("/api/v1/jobs/upload-batch", json={"files": bad_files})
    assert res.status_code == 400

    # Valid batch of 3 files (pptx, ppt, pdf) -> 200
    good_files = [
        {"client_item_id": "c1", "filename": "deck1.pptx", "size_bytes": 1000},
        {"client_item_id": "c2", "filename": "deck2.ppt", "size_bytes": 2000},
        {"client_item_id": "c3", "filename": "deck3.pdf", "size_bytes": 3000},
    ]
    res = client.post("/api/v1/jobs/upload-batch", json={"files": good_files})
    assert res.status_code == 200
    body = res.json()
    assert "batch_id" in body and body["batch_id"]


def test_batch_status_waiting_and_totals(monkeypatch):
    async def mock_dispatch():
        return 0
    monkeypatch.setattr("backend.app.services.ingestion.upload_queue.dispatch_available", mock_dispatch)

    good_files = [
        {"client_item_id": "c1", "filename": "deck1.pptx", "size_bytes": 1000},
        {"client_item_id": "c2", "filename": "deck2.pptx", "size_bytes": 2000},
        {"client_item_id": "c3", "filename": "deck3.pdf", "size_bytes": 3000},
    ]
    create_res = client.post("/api/v1/jobs/upload-batch", json={"files": good_files})
    batch_id = create_res.json()["batch_id"]

    status_res = client.get(f"/api/v1/jobs/upload-batch/{batch_id}")
    assert status_res.status_code == 200
    data = status_res.json()

    assert data["batch_id"] == batch_id
    totals = data["totals"]
    assert totals["total"] == 3
    assert totals["waiting"] == 3
    assert totals["queued"] == 0
    assert totals["processing"] == 0
    assert totals["completed"] == 0
    assert totals["failed"] == 0
    assert totals["cancelled"] == 0

    assert len(data["items"]) == 3
    for it in data["items"]:
        assert it["status"] == "WAITING"
        assert it["percentage"] == 0
        assert it["queue_position"] is None


def test_batch_lifecycle_and_queue_positions(monkeypatch):
    async def mock_dispatch():
        return 0
    monkeypatch.setattr("backend.app.services.ingestion.upload_queue.dispatch_available", mock_dispatch)

    files = [
        {"client_item_id": "item_a", "filename": "deck_a.pptx", "size_bytes": 1000},
        {"client_item_id": "item_b", "filename": "deck_b.pptx", "size_bytes": 2000},
    ]
    create_res = client.post("/api/v1/jobs/upload-batch", json={"files": files})
    batch_id = create_res.json()["batch_id"]

    db = SessionLocal()
    doc_a = _mk_doc(db, status="QUEUED")
    try:
        # Enqueue item_a
        job_a = uq.enqueue_upload(
            db, document_id=doc_a, filename="deck_a.pptx",
            batch_id=batch_id, client_item_id="item_a"
        )
        job_a_id = job_a.id
        db.close()

        # Check status: item_a is QUEUED at position 0, item_b is WAITING
        status_res = client.get(f"/api/v1/jobs/upload-batch/{batch_id}")
        data = status_res.json()
        assert data["totals"]["queued"] == 1
        assert data["totals"]["waiting"] == 1

        items = {it["client_item_id"]: it for it in data["items"]}
        assert items["item_a"]["status"] == "QUEUED"
        assert items["item_a"]["queue_position"] == 0
        assert items["item_b"]["status"] == "WAITING"

        # Simulate item_a moving to PROCESSING with progress detail
        db = SessionLocal()
        job = db.query(IngestionJob).filter(IngestionJob.id == job_a_id).first()
        job.status = "PROCESSING"
        doc = db.query(Document).filter(Document.id == doc_a).first()
        doc.processing_status = "PROCESSING"
        doc.progress_detail = {"progress_percentage": 55, "current_stage": "Parsing slides"}
        db.commit()
        db.close()

        status_res2 = client.get(f"/api/v1/jobs/upload-batch/{batch_id}")
        data2 = status_res2.json()
        assert data2["totals"]["processing"] == 1
        assert data2["totals"]["waiting"] == 1
        items2 = {it["client_item_id"]: it for it in data2["items"]}
        assert items2["item_a"]["status"] == "PROCESSING"
        assert items2["item_a"]["percentage"] == 55
        assert items2["item_a"]["step"] == "Parsing slides"

        # Simulate item_a moving to COMPLETED
        db = SessionLocal()
        job = db.query(IngestionJob).filter(IngestionJob.id == job_a_id).first()
        job.status = "COMPLETED"
        doc = db.query(Document).filter(Document.id == doc_a).first()
        doc.processing_status = "COMPLETED"
        doc.slide_count = 12
        doc.question_count = 10
        db.commit()
        db.close()

        status_res3 = client.get(f"/api/v1/jobs/upload-batch/{batch_id}")
        data3 = status_res3.json()
        assert data3["totals"]["completed"] == 1
        assert data3["totals"]["waiting"] == 1
        items3 = {it["client_item_id"]: it for it in data3["items"]}
        assert items3["item_a"]["status"] == "COMPLETED"
        assert items3["item_a"]["percentage"] == 100
        assert items3["item_a"]["slides"] == 12
        assert items3["item_a"]["questions"] == 10
    finally:
        _cleanup(doc_a)


def test_active_batch_lookup(monkeypatch):
    async def mock_dispatch():
        return 0
    monkeypatch.setattr("backend.app.services.ingestion.upload_queue.dispatch_available", mock_dispatch)

    files = [
        {"client_item_id": "c1", "filename": "deck1.pptx", "size_bytes": 1000},
    ]
    create_res = client.post("/api/v1/jobs/upload-batch", json={"files": files})
    batch_id = create_res.json()["batch_id"]

    # When item c1 is still WAITING, active endpoint returns batch_id
    active_res = client.get("/api/v1/jobs/upload-batches/active")
    assert active_res.status_code == 200
    assert active_res.json()["batch_id"] == batch_id

    # Enqueue and complete the item
    db = SessionLocal()
    doc_id = _mk_doc(db, status="COMPLETED")
    try:
        job = uq.enqueue_upload(
            db, document_id=doc_id, filename="deck1.pptx",
            batch_id=batch_id, client_item_id="c1"
        )
        job.status = "COMPLETED"
        db.commit()
        db.close()

        # All items terminal -> active endpoint returns None
        active_res2 = client.get("/api/v1/jobs/upload-batches/active")
        assert active_res2.status_code == 200
        assert active_res2.json()["batch_id"] is None
    finally:
        _cleanup(doc_id)


def test_cancel_pending_leaves_processing_untouched(monkeypatch):
    async def mock_dispatch():
        return 0
    monkeypatch.setattr("backend.app.services.ingestion.upload_queue.dispatch_available", mock_dispatch)

    files = [
        {"client_item_id": "proc_item", "filename": "proc.pptx", "size_bytes": 1000},
        {"client_item_id": "pend_item", "filename": "pend.pptx", "size_bytes": 2000},
        {"client_item_id": "wait_item", "filename": "wait.pptx", "size_bytes": 3000},
    ]
    create_res = client.post("/api/v1/jobs/upload-batch", json={"files": files})
    batch_id = create_res.json()["batch_id"]

    db = SessionLocal()
    doc_proc = _mk_doc(db, status="PROCESSING")
    doc_pend = _mk_doc(db, status="QUEUED")

    try:
        job_proc = uq.enqueue_upload(
            db, document_id=doc_proc, filename="proc.pptx",
            batch_id=batch_id, client_item_id="proc_item"
        )
        job_proc.status = "PROCESSING"
        proc_id = job_proc.id

        job_pend = uq.enqueue_upload(
            db, document_id=doc_pend, filename="pend.pptx",
            batch_id=batch_id, client_item_id="pend_item"
        )
        pend_id = job_pend.id
        db.commit()
        db.close()

        # Call cancel-pending
        cancel_res = client.post(f"/api/v1/jobs/upload-batch/{batch_id}/cancel-pending")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["cancelled_count"] == 1

        # Verify DB directly
        verify_db = SessionLocal()
        try:
            saved_proc = verify_db.query(IngestionJob).filter(IngestionJob.id == proc_id).first()
            assert saved_proc.status == "PROCESSING"  # MUST BE UNTOUCHED!

            saved_pend = verify_db.query(IngestionJob).filter(IngestionJob.id == pend_id).first()
            assert saved_pend.status == "CANCELLED"

            saved_doc_pend = verify_db.query(Document).filter(Document.id == doc_pend).first()
            assert saved_doc_pend.processing_status == "CANCELLED"
        finally:
            verify_db.close()

        # Verify batch status endpoint
        batch_status_res = client.get(f"/api/v1/jobs/upload-batch/{batch_id}")
        data = batch_status_res.json()
        totals = data["totals"]
        assert totals["processing"] == 1
        assert totals["cancelled"] == 1
        assert totals["waiting"] == 1
        assert totals["queued"] == 0
    finally:
        _cleanup(doc_proc, doc_pend)
