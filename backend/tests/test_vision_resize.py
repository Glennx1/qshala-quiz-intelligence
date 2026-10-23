"""shrink_for_vision: downsizes a picture in memory before a vision call, never raises."""
import io

import numpy as np
from PIL import Image

from backend.app.services.ingestion.vision_resize import shrink_for_vision


def _noisy_jpeg_bytes(w: int, h: int) -> bytes:
    arr = (np.random.rand(h, w, 3) * 255).astype("uint8")
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_large_image_is_shrunk():
    data = _noisy_jpeg_bytes(3000, 2000)
    out, mime = shrink_for_vision(data, "image/jpeg")
    assert len(out) < len(data)
    assert mime == "image/jpeg"
    img = Image.open(io.BytesIO(out))
    assert max(img.size) <= 1600


def test_small_image_passed_through():
    data = _noisy_jpeg_bytes(50, 50)
    out, mime = shrink_for_vision(data, "image/jpeg")
    assert out == data
    assert mime == "image/jpeg"


def test_garbage_bytes_fall_back_safely():
    data = b"not an image" * 10000
    out, mime = shrink_for_vision(data, "image/png")
    assert out == data
    assert mime == "image/png"


def test_png_stays_png():
    arr = (np.random.rand(2000, 3000, 3) * 255).astype("uint8")
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    out, mime = shrink_for_vision(data, "image/png")
    assert mime == "image/png"
    out_img = Image.open(io.BytesIO(out))
    assert max(out_img.size) <= 1600
