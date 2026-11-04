"""R2 cleanup on cancel actually deletes the raw deck (audit Q11)."""
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.job import IngestionJob
from backend.app.services.ingestion.cancellation import purge_document
from backend.app.services.storage import r2_storage
from backend.app.services.storage.r2_storage import CloudflareR2Service

client = TestClient(app)


class FakeBoto:
    def __init__(self, fail=False):
        self.deleted = []
        self.fail = fail

    def delete_object(self, Bucket, Key):
        if self.fail:
            raise RuntimeError("denied")
        self.deleted.append((Bucket, Key))

    def get_paginator(self, name):
        class P:
            def paginate(self, **kw):
                return []
        return P()


def make_service(boto):
    svc = object.__new__(CloudflareR2Service)
    svc.account_id, svc.bucket_name = "acct", "bucket"
    svc.public_base_url = "https://cdn.example.test"
    svc.is_configured = True
    svc._client = boto
    return svc


def test_delete_object_deletes_the_exact_key_and_accepts_public_urls():
    boto = FakeBoto()
    svc = make_service(boto)
    svc.delete_object("raw-uploads/abc.pptx")
    svc.delete_object("https://cdn.example.test/slides/abc/media/x.png")
    assert boto.deleted == [("bucket", "raw-uploads/abc.pptx"), ("bucket", "slides/abc/media/x.png")]


def test_delete_object_raises_on_failure_but_not_when_unconfigured():
    with pytest.raises(RuntimeError):
        make_service(FakeBoto(fail=True)).delete_object("k")
    svc = make_service(FakeBoto())
    svc.is_configured = False
    svc.delete_object("k")          # silently does nothing, like the other methods


def _doc(storage_path="deck.pptx", status="PROCESSING"):
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Document(id=doc_id, filename="deck.pptx", title="t", file_type="pptx", storage_path=storage_path,
                        file_size_bytes=1, processing_status=status))
        db.commit()
    finally:
        db.close()
    return doc_id


def test_purge_document_removes_the_raw_deck_from_r2(monkeypatch):
    boto = FakeBoto()
    svc = make_service(boto)
    monkeypatch.setattr(r2_storage, "get_media_storage", lambda: svc)
    doc_id = _doc("/tmp/whatever/deck.pptx")
    db = SessionLocal()
    try:
        purge_document(db, doc_id)
    finally:
        db.close()
    assert ("bucket", f"raw-uploads/{doc_id}.pptx") in boto.deleted


def test_cancelling_a_batch_deletes_the_raw_key_as_one_key_not_per_character(monkeypatch):
    boto = FakeBoto()
    svc = make_service(boto)
    monkeypatch.setattr(r2_storage, "get_r2_service", lambda: svc)
    monkeypatch.setattr(r2_storage, "get_media_storage", lambda: svc)
    doc_id = _doc("/tmp/whatever/deck.pptx")
    batch_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(IngestionJob(filename="deck.pptx", source_type="MANUAL_UPLOAD", status="PENDING",
                            document_id=doc_id, batch_id=batch_id))
        db.commit()
    finally:
        db.close()
    r = client.post(f"/api/v1/jobs/upload-batch/{batch_id}/cancel")
    assert r.status_code == 200, r.text
    keys = [k for _, k in boto.deleted]
    assert f"raw-uploads/{doc_id}.pptx" in keys
    assert all(len(k) > 1 for k in keys)            # the old code produced one single-character delete per letter


def test_cancelling_pending_items_deletes_the_raw_key(monkeypatch):
    boto = FakeBoto()
    svc = make_service(boto)
    monkeypatch.setattr(r2_storage, "get_r2_service", lambda: svc)
    monkeypatch.setattr(r2_storage, "get_media_storage", lambda: svc)
    doc_id = _doc("/tmp/whatever/deck.pptx")
    batch_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(IngestionJob(filename="deck.pptx", source_type="MANUAL_UPLOAD", status="PENDING",
                            document_id=doc_id, batch_id=batch_id))
        db.commit()
    finally:
        db.close()
    r = client.post(f"/api/v1/jobs/upload-batch/{batch_id}/cancel-pending")
    assert r.status_code == 200, r.text
    assert ("bucket", f"raw-uploads/{doc_id}.pptx") in boto.deleted
