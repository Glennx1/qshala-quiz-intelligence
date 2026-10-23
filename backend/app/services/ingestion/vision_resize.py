"""Shrink a single image in memory before sending it to the vision model.

Used only at the point of use (right before a Gemini describe_image call),
never as a pass over the whole deck — keeps memory and request payload down
on image-heavy decks without adding a slow pre-processing stage.
"""
import io
import logging
import os
import sys
import threading
import concurrent.futures
import asyncio
from typing import Tuple, Optional

from PIL import Image

logger = logging.getLogger(__name__)

MAX_SIDE: int = 1600
JPEG_QUALITY: int = 82
MIN_BYTES: int = 60 * 1024  # don't bother re-encoding small images

# Decoding a picture costs width x height x 4 bytes of RAM (an 8192x4608 PNG is ~150 MB).
# On a 512 MB server that is the difference between working and being killed, so:
#  - anything that would decode to more than MAX_DECODE_PIXELS is sent as-is instead of shrunk
#    (a bigger upload to the vision model beats an out-of-memory crash);
#  - only one large decode runs at a time, however many vision calls are in flight.
MAX_DECODE_PIXELS: int = int(os.getenv("VISION_MAX_DECODE_PIXELS", "24000000"))
_BIG_DECODE_PIXELS: int = 4_000_000
_big_decode_gate = threading.Semaphore(1)


def shrink_for_vision(data: bytes, mime_type: str) -> Tuple[bytes, str]:
    """Returns (possibly smaller) bytes and the mime type to send.

    Falls back to the original bytes/mime on any failure — never raises,
    never blocks a vision call over a resize problem.
    """
    if len(data) < MIN_BYTES:
        return data, mime_type

    try:
        img = Image.open(io.BytesIO(data))   # lazy: reads the header only
        width, height = img.size
    except Exception as e:
        logger.debug("vision_resize: could not open image, using original (%s)", e)
        return data, mime_type

    if max(width, height) <= MAX_SIDE:
        return data, mime_type               # already small enough: nothing decoded

    gate = None
    try:
        scale = MAX_SIDE / float(max(width, height))
        target = (max(1, int(width * scale)), max(1, int(height * scale)))
        if img.format == "JPEG":
            # Lets the JPEG decoder skip straight to a 1/2, 1/4 or 1/8 size image: far less memory and time.
            img.draft("RGB", target)
        decode_pixels = img.size[0] * img.size[1]
        if decode_pixels > MAX_DECODE_PIXELS:
            logger.info("vision_resize: %dx%d is too large to decode safely here, sending original", width, height)
            return data, mime_type
        if decode_pixels > _BIG_DECODE_PIXELS:
            gate = _big_decode_gate
            gate.acquire()
        img.load()
        img = img.resize(target, Image.LANCZOS)
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
    finally:
        if gate is not None:
            gate.release()


def shrink_file_worker(file_path: str, mime_type: str) -> Tuple[bytes, str]:
    """Worker executed in throwaway subprocess: reads file, shrinks it, returns small bytes and mime."""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        return shrink_for_vision(data, mime_type)
    except Exception as e:
        logger.debug("shrink_file_worker failed for %s: %s", file_path, e)
        return b"", mime_type


def shrink_data_worker(data: bytes, mime_type: str) -> Tuple[bytes, str]:
    """Worker executed in throwaway subprocess: shrinks bytes, returns small bytes and mime."""
    try:
        return shrink_for_vision(data, mime_type)
    except Exception as e:
        logger.debug("shrink_data_worker failed: %s", e)
        return data, mime_type


def _use_subprocess() -> bool:
    """Use throwaway subprocess on Linux/macOS to enforce memory return to OS."""
    return not sys.platform.startswith("win")


async def shrink_for_vision_subprocess(
    file_path: Optional[str] = None,
    data: Optional[bytes] = None,
    mime_type: str = "image/jpeg"
) -> Tuple[bytes, str]:
    """Shrink image in a throwaway subprocess so decode memory returns to OS upon exit.

    Passes file path directly to the child if present, keeping full-res bytes out of the parent process.
    Falls back to in-process shrink_for_vision on any exception.
    """
    if _use_subprocess():
        if file_path and os.path.exists(file_path):
            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1) as pool:
                    result = await loop.run_in_executor(pool, shrink_file_worker, str(file_path), mime_type)
                    if result and result[0]:
                        return result
            except Exception as exc:
                logger.debug("Subprocess shrink failed (%s), falling back to in-process", exc)
        elif data:
            try:
                loop = asyncio.get_running_loop()
                with concurrent.futures.ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1) as pool:
                    result = await loop.run_in_executor(pool, shrink_data_worker, data, mime_type)
                    if result and result[0]:
                        return result
            except Exception as exc:
                logger.debug("Subprocess shrink failed (%s), falling back to in-process", exc)

    # In-process fallback
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            return shrink_for_vision(raw_bytes, mime_type)
        except Exception as read_exc:
            logger.debug("Fallback file read failed: %s", read_exc)
            return b"", mime_type
    elif data:
        return shrink_for_vision(data, mime_type)

    return b"", mime_type
