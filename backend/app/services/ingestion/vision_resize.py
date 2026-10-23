"""Shrink a single image in memory before sending it to the vision model.

Used only at the point of use (right before a Gemini describe_image call),
never as a pass over the whole deck — keeps memory and request payload down
on image-heavy decks without adding a slow pre-processing stage.
"""
import io
import logging
from typing import Tuple

from PIL import Image

logger = logging.getLogger(__name__)

MAX_SIDE: int = 1600
JPEG_QUALITY: int = 82
MIN_BYTES: int = 60 * 1024  # don't bother re-encoding small images


def shrink_for_vision(data: bytes, mime_type: str) -> Tuple[bytes, str]:
    """Returns (possibly smaller) bytes and the mime type to send.

    Falls back to the original bytes/mime on any failure — never raises,
    never blocks a vision call over a resize problem.
    """
    if len(data) < MIN_BYTES:
        return data, mime_type

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        logger.debug("vision_resize: could not open image, using original (%s)", e)
        return data, mime_type

    if max(img.size) <= MAX_SIDE:
        return data, mime_type

    try:
        scale = MAX_SIDE / float(max(img.size))
        img = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.LANCZOS,
        )
        buf = io.BytesIO()
        if mime_type == "image/png":
            img.save(buf, "PNG", optimize=True)
        else:
            img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
            mime_type = "image/jpeg"
        out = buf.getvalue()
        return (out, mime_type) if len(out) < len(data) else (data, mime_type)
    except Exception as e:
        logger.debug("vision_resize: resize failed, using original (%s)", e)
        return data, mime_type
