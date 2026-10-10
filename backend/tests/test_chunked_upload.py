import io
import sys
import uuid
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.document import Document

client = TestClient(app)

def test_chunked_upload_assembly():
    content = b"Mock PPTX presentation content sliced into three chunks." * 100
    chunk_size = len(content) // 3
    chunks = [
        content[:chunk_size],
        content[chunk_size:2 * chunk_size],
        content[2 * chunk_size:]
    ]
    upload_id = str(uuid.uuid4())
    filename = "test_large_deck.pptx"

    # Send chunk 0
    res0 = client.post(
        "/api/v1/documents/upload-chunk",
        data={
            "upload_id": upload_id,
            "chunk_index": 0,
            "total_chunks": 3,
            "filename": filename,
            "title": "Test Large Deck"
        },
        files={"chunk": ("chunk_0", io.BytesIO(chunks[0]), "application/octet-stream")}
    )
    assert res0.status_code == 200
    assert res0.json()["status"] == "CHUNK_RECEIVED"
    assert res0.json()["chunk_index"] == 0

    # Send chunk 1
    res1 = client.post(
        "/api/v1/documents/upload-chunk",
        data={
            "upload_id": upload_id,
            "chunk_index": 1,
            "total_chunks": 3,
            "filename": filename,
            "title": "Test Large Deck"
        },
        files={"chunk": ("chunk_1", io.BytesIO(chunks[1]), "application/octet-stream")}
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "CHUNK_RECEIVED"

    # Send final chunk 2
    res2 = client.post(
        "/api/v1/documents/upload-chunk",
        data={
            "upload_id": upload_id,
            "chunk_index": 2,
            "total_chunks": 3,
            "filename": filename,
            "title": "Test Large Deck"
        },
        files={"chunk": ("chunk_2", io.BytesIO(chunks[2]), "application/octet-stream")}
    )
    assert res2.status_code == 200
    data = res2.json()
    assert data["status"] == "COMPLETED"
    doc_info = data["document"]
    assert doc_info["title"] == "Test Large Deck"
    assert doc_info["file_size_bytes"] == len(content)

    # Verify document in database
    db = SessionLocal()
    doc = db.query(Document).filter(Document.id == doc_info["id"]).first()
    assert doc is not None
    assert Path(doc.storage_path).exists()
    assert Path(doc.storage_path).read_bytes() == content

    # Clean up test artifact
    try:
        if Path(doc.storage_path).exists():
            Path(doc.storage_path).unlink()
        db.delete(doc)
        db.commit()
    finally:
        db.close()
