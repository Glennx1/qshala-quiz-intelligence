"""Vision reads the picture the parser just wrote instead of downloading it back from R2 (audit Q6)."""
import asyncio
import os
import uuid
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.services.ingestion import pipeline as pipeline_mod
from backend.app.services.ingestion.pipeline import (
    IngestionPipeline, INGESTION_STATUS_REGISTRY, local_media_for_url,
)

from test_v6_pipeline import FakeGemini
from test_dedup_before_ai import RecordingEmbedder


class FakeR2:
    public_base_url = "https://cdn.example.test"

    def __init__(self):
        self.uploaded = []

    def upload_file(self, key, path, content_type=None):
        self.uploaded.append(key)
        return key


class CapturingLLM:
    def __init__(self):
        self.sizes = []

    async def describe_image(self, data, mime_type="image/jpeg"):
        self.sizes.append(len(data))
        return "a captured picture"


def _png(path: Path):
    # Noise so the file is well over the 2 KB "spacer" filter.
    Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3)).save(path)


def _deck_with_picture(path: Path, img: Path):
    prs = Presentation()
    blank = prs.slide_layouts[6]
    s = prs.slides.add_slide(blank)
    s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2)).text_frame.text = "QShala Quest pictures"
    s = prs.slides.add_slide(blank)
    s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2)).text_frame.text = "ROUND 1\nPicture round"
    s = prs.slides.add_slide(blank)
    s.shapes.add_textbox(Inches(1), Inches(0.2), Inches(8), Inches(1.5)).text_frame.text = (
        f"QUESTION 1\nWhich unique {uuid.uuid4().hex[:8]} landmark is shown here?")
    s.shapes.add_picture(str(img), Inches(1), Inches(2), Inches(3), Inches(3))
    s = prs.slides.add_slide(blank)
    s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2)).text_frame.text = (
        "ANSWER 1\nAnswer: The Landmark\n\nExplanation & Context:\nBecause it is.")
    prs.save(str(path))


def test_local_media_for_url_only_maps_this_decks_media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SLIDES_DIR", tmp_path)
    doc = "doc-1"
    (tmp_path / doc / "media").mkdir(parents=True)
    (tmp_path / doc / "media" / "a.png").write_bytes(b"x" * 10)
    (tmp_path / "secret.png").write_bytes(b"s")
    base = "https://cdn.example.test"
    assert local_media_for_url(f"{base}/slides/{doc}/media/a.png", doc) == tmp_path / doc / "media" / "a.png"
    assert local_media_for_url(f"{base}/slides/{doc}/media/missing.png", doc) is None
    assert local_media_for_url(f"{base}/slides/other-doc/media/a.png", doc) is None
    assert local_media_for_url(f"{base}/slides/{doc}/media/../../secret.png", doc) is None
    assert local_media_for_url(f"{base}/slides/{doc}/media/sub/a.png", doc) is None
    assert local_media_for_url("https://elsewhere.test/pic.png", doc) is None


def _ingest_with_fake_r2(monkeypatch, tmp_path, prefer_local=True):
    import httpx
    from backend.app.services.storage import r2_storage

    r2 = FakeR2()
    monkeypatch.setattr(r2_storage, "get_media_storage", lambda: r2)
    monkeypatch.setattr(pipeline_mod, "VISION_PREFER_LOCAL", prefer_local)
    fetched = []

    async def fake_get(self, url, *a, **k):
        fetched.append(url)
        raise httpx.ConnectError("no network in tests")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    img = tmp_path / "pic.png"
    _png(img)
    dest = settings.UPLOAD_DIR / f"{uuid.uuid4().hex}.pptx"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _deck_with_picture(dest, img)
    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Document(id=doc_id, filename="pics.pptx", title="pics", year=2022, file_type="pptx",
                        storage_path=str(dest), file_size_bytes=dest.stat().st_size, processing_status="PROCESSING"))
        db.commit()
    finally:
        db.close()
    llm = CapturingLLM()
    pipe = IngestionPipeline()
    pipe.qshala_tagger.provider = FakeGemini()
    pipe.qshala_tagger.rpm = 0
    pipe.embedding_provider = RecordingEmbedder()
    pipe.llm_provider = llm
    asyncio.run(pipe.run(doc_id))
    assert INGESTION_STATUS_REGISTRY[doc_id]["status"] == "COMPLETED", INGESTION_STATUS_REGISTRY[doc_id]
    return doc_id, llm, fetched, r2


@pytest.fixture(autouse=True)
def _remove_mirrored_media():
    """The parser also mirrors media under frontend/public/static/slides/<doc>/; don't leave test pictures there."""
    import shutil
    mirror = Path(__file__).resolve().parents[2] / "frontend" / "public" / "static" / "slides"
    before = {p.name for p in mirror.iterdir()} if mirror.exists() else set()
    yield
    if mirror.exists():
        for p in mirror.iterdir():
            if p.name not in before:
                shutil.rmtree(p, ignore_errors=True)


def test_vision_uses_local_copy_and_does_not_download(monkeypatch, tmp_path):
    doc_id, llm, fetched, r2 = _ingest_with_fake_r2(monkeypatch, tmp_path, prefer_local=True)
    assert r2.uploaded, "the picture should still be uploaded to R2"
    assert fetched == []                                       # no download of a file we just wrote
    assert len(llm.sizes) == 1 and llm.sizes[0] > 2048        # vision received the real picture bytes
    db = SessionLocal()
    try:
        q = db.query(Question).filter(Question.document_id == doc_id).one()
        assert q.visual_clues == "a captured picture"
        assert q.question_images and q.question_images[0].startswith("https://cdn.example.test/slides/")
    finally:
        db.close()


def test_flag_off_falls_back_to_http(monkeypatch, tmp_path):
    doc_id, llm, fetched, r2 = _ingest_with_fake_r2(monkeypatch, tmp_path, prefer_local=False)
    assert len(fetched) == 1 and llm.sizes == []              # old behaviour: tried to download, vision got nothing
