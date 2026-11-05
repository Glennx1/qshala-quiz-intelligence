"""Memory limits for the Cloud Run Job worker (audit M1): no second local copy of the pictures, raw deck freed after
parsing, one large image decode at a time. The upload size cap is deliberately untouched."""
import os
import shutil
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.services.ingestion import pipeline as pipeline_mod
from backend.app.services.ingestion import vision_resize

from test_vision_local_copy import _ingest_with_fake_r2


@pytest.fixture(autouse=True)
def _clean_env_and_mirror(monkeypatch):
    for k in ("CLOUD_RUN_JOB", "KEEP_LOCAL_MEDIA", "DELETE_RAW_DECK_AFTER_PARSE"):
        monkeypatch.delenv(k, raising=False)
    mirror = Path(__file__).resolve().parents[2] / "frontend" / "public" / "static" / "slides"
    before = {p.name for p in mirror.iterdir()} if mirror.exists() else set()
    yield
    if mirror.exists():
        for p in mirror.iterdir():
            if p.name not in before:
                shutil.rmtree(p, ignore_errors=True)


def _storage_path(doc_id):
    db = SessionLocal()
    try:
        return Path(db.query(Document).filter(Document.id == doc_id).one().storage_path)
    finally:
        db.close()


def test_policy_defaults_and_overrides(monkeypatch):
    # outside a Job worker: nothing changes
    assert pipeline_mod.keep_local_media(True) is True
    assert pipeline_mod.delete_raw_deck_after_parse() is False
    # inside a Job worker with R2: no local media copy, raw deck deleted; without R2 the media must stay on disk
    monkeypatch.setenv("CLOUD_RUN_JOB", "qshala-worker")
    assert pipeline_mod.keep_local_media(True) is False
    assert pipeline_mod.keep_local_media(False) is True
    assert pipeline_mod.delete_raw_deck_after_parse() is True
    # explicit settings win
    monkeypatch.setenv("KEEP_LOCAL_MEDIA", "1")
    monkeypatch.setenv("DELETE_RAW_DECK_AFTER_PARSE", "0")
    assert pipeline_mod.keep_local_media(True) is True
    assert pipeline_mod.delete_raw_deck_after_parse() is False


def test_default_run_keeps_deck_and_local_pictures(monkeypatch, tmp_path):
    doc_id, llm, fetched, r2 = _ingest_with_fake_r2(monkeypatch, tmp_path)
    assert _storage_path(doc_id).exists()
    media = settings.SLIDES_DIR / doc_id / "media"
    assert media.exists() and any(media.iterdir())


def test_job_worker_run_frees_deck_and_keeps_no_local_pictures(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUD_RUN_JOB", "qshala-worker")
    doc_id, llm, fetched, r2 = _ingest_with_fake_r2(monkeypatch, tmp_path)
    assert not _storage_path(doc_id).exists()                      # the raw deck was deleted after parsing
    media = settings.SLIDES_DIR / doc_id / "media"
    assert not media.exists() or not any(media.iterdir())          # no second copy of the pictures on disk
    assert r2.uploaded, "pictures must still be uploaded to R2"
    assert len(fetched) == 1                                       # vision now downloads from R2 (fake, offline here)
    db = SessionLocal()
    try:
        q = db.query(Question).filter(Question.document_id == doc_id).one()
        assert q.question_images and q.question_images[0].startswith("https://cdn.example.test/slides/")
    finally:
        db.close()


def test_only_one_large_decode_runs_at_a_time_by_default():
    if "BIG_DECODE_CONCURRENCY" in os.environ:
        pytest.skip("overridden in this environment")
    assert vision_resize._big_decode_gate._value == 1
