"""Cancelling an upload must really stop and clean up: slices on disk, ingestion, DB row."""
import asyncio
import io
import shutil
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.main import app
from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.services.ingestion.pipeline import IngestionPipeline, INGESTION_STATUS_REGISTRY
from backend.app.services.ingestion import cancellation

client = TestClient(app)
SAMPLE_DECK = Path(__file__).resolve().parent.parent / "sample_decks" / "Australian_History_Quiz_2022.pptx"


def _send_chunk(upload_id, idx, total, payload=b"x" * 2048, filename="deck.pptx"):
    return client.post(
        "/api/v1/documents/upload-chunk",
        data={"upload_id": upload_id, "chunk_index": idx, "total_chunks": total, "filename": filename},
        files={"chunk": (f"chunk_{idx}", io.BytesIO(payload), "application/octet-stream")},
    )


def test_cancel_chunked_upload_removes_slices_and_refuses_more():
    upload_id = f"upl_{uuid.uuid4().hex}"
    assert _send_chunk(upload_id, 0, 5).status_code == 200
    chunk_dir = settings.STORAGE_DIR / "tmp_chunks" / upload_id
    assert any(chunk_dir.glob("chunk_*.part"))

    res = client.delete(f"/api/v1/documents/upload-chunk/{upload_id}")
    assert res.status_code == 200 and res.json()["status"] == "CANCELLED"
    assert not chunk_dir.exists()

    # a slice that was already in flight when the user cancelled is refused and leaves nothing behind
    late = _send_chunk(upload_id, 1, 5)
    assert late.status_code == 409
    assert not chunk_dir.exists()


def test_upload_id_cannot_escape_tmp_chunks():
    assert _send_chunk("../../etc", 0, 2).status_code == 400
    assert client.delete("/api/v1/documents/upload-chunk/..%2F..%2Fetc").status_code in (400, 404)


def _make_doc(tmp_name: str) -> str:
    dest = settings.UPLOAD_DIR / tmp_name
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLE_DECK, dest)
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Document(id=doc_id, filename="Australian_History_Quiz_2022.pptx", title="cancel-test",
                        year=2022, file_type="pptx", storage_path=str(dest),
                        file_size_bytes=dest.stat().st_size, processing_status="PROCESSING"))
        db.commit()
    finally:
        db.close()
    return doc_id


def _doc_exists(doc_id) -> bool:
    db = SessionLocal()
    try:
        return db.query(Document).filter(Document.id == doc_id).first() is not None
    finally:
        db.close()


def test_cancel_before_pipeline_stops_ingestion_and_purges_everything():
    doc_id = _make_doc(f"{uuid.uuid4().hex}.pptx")
    stored = Path(SessionLocal().query(Document).filter(Document.id == doc_id).first().storage_path)
    INGESTION_STATUS_REGISTRY[doc_id] = {"document_id": doc_id, "status": "PROCESSING"}

    res = client.post(f"/api/v1/documents/{doc_id}/cancel")
    assert res.json()["status"] == "CANCELLING"

    asyncio.run(IngestionPipeline().run(doc_id))

    assert INGESTION_STATUS_REGISTRY[doc_id]["status"] == "CANCELLED"
    assert not _doc_exists(doc_id)
    assert not stored.exists()
    assert not (settings.SLIDES_DIR / doc_id).exists()
    assert not cancellation.doc_cancel_requested(doc_id)  # flag cleared after cleanup


def test_cancel_when_nothing_is_running_purges_immediately():
    doc_id = _make_doc(f"{uuid.uuid4().hex}.pptx")
    INGESTION_STATUS_REGISTRY.pop(doc_id, None)
    res = client.post(f"/api/v1/documents/{doc_id}/cancel")
    assert res.json()["status"] == "CANCELLED"
    assert not _doc_exists(doc_id)


def test_completed_document_cannot_be_cancelled():
    doc_id = _make_doc(f"{uuid.uuid4().hex}.pptx")
    db = SessionLocal()
    d = db.query(Document).filter(Document.id == doc_id).first()
    d.processing_status = "COMPLETED"
    db.commit()
    db.close()
    assert client.post(f"/api/v1/documents/{doc_id}/cancel").status_code == 409
    client.delete(f"/api/v1/documents/{doc_id}")  # tidy up


def test_uncancelled_ingestion_still_completes():
    """Guard against the new checkpoints breaking the normal path."""
    doc_id = _make_doc(f"{uuid.uuid4().hex}.pptx")
    asyncio.run(IngestionPipeline().run(doc_id))
    assert INGESTION_STATUS_REGISTRY[doc_id]["status"] == "COMPLETED"
    client.delete(f"/api/v1/documents/{doc_id}")
