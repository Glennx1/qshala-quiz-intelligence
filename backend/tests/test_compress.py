"""Auto-compression: oversized pictures inside a .pptx get shrunk before parsing."""
import io
import os
import tempfile
import zipfile

import numpy as np
from PIL import Image

from backend.app.services.ingestion import compress as compress_mod
from backend.app.services.ingestion.compress import compress_pptx


def _fake_pptx_with_noisy_image(w: int, h: int) -> str:
    arr = (np.random.rand(h, w, 3) * 255).astype("uint8")
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    img_bytes = buf.getvalue()

    fd, path = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("ppt/media/image1.jpg", img_bytes)
        z.writestr("[Content_Types].xml", "<Types/>")
    return path


def test_large_image_is_shrunk_in_place(monkeypatch):
    monkeypatch.setattr(compress_mod, "MIN_FILE_MB", 0.0001)
    monkeypatch.setattr(compress_mod, "MIN_PIC_BYTES", 1000)
    path = _fake_pptx_with_noisy_image(3000, 2000)
    try:
        before = os.path.getsize(path)
        result = compress_pptx(path)
        after = os.path.getsize(path)
        assert result["shrunk"] == 1
        assert after < before
    finally:
        os.unlink(path)


def test_small_file_is_skipped(monkeypatch):
    monkeypatch.setattr(compress_mod, "MIN_FILE_MB", 20.0)  # default-ish threshold
    path = _fake_pptx_with_noisy_image(200, 150)  # tiny file, well under 20 MB
    try:
        before = os.path.getsize(path)
        result = compress_pptx(path)
        after = os.path.getsize(path)
        assert result.get("skipped_reason") == "too_small"
        assert after == before  # untouched
    finally:
        os.unlink(path)


def test_on_progress_callback_fires(monkeypatch):
    monkeypatch.setattr(compress_mod, "MIN_FILE_MB", 0.0001)
    monkeypatch.setattr(compress_mod, "MIN_PIC_BYTES", 1000)
    path = _fake_pptx_with_noisy_image(3000, 2000)
    messages = []
    try:
        compress_pptx(path, on_progress=messages.append)
        assert len(messages) >= 2
        assert any("Compress" in m for m in messages)
    finally:
        os.unlink(path)


def test_corrupt_zip_falls_back_gracefully(monkeypatch):
    monkeypatch.setattr(compress_mod, "MIN_FILE_MB", 0.0001)
    fd, path = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(b"not a real zip file" * 100000)
    try:
        result = compress_pptx(path)
        assert result.get("skipped_reason") == "error"
        assert os.path.exists(path)  # original left in place
    finally:
        os.unlink(path)
