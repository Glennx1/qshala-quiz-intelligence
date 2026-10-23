"""Auto-compress images inside a .pptx before parsing.

Called automatically by the ingestion pipeline. The original upload is
replaced in-place with the compressed copy so the parser sees a smaller
file from the start — less memory, faster image uploads.

Only kicks in when the file is above MIN_FILE_MB (default 20 MB).
Pictures under MIN_PIC_BYTES are left alone.
"""
import io
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

logger = logging.getLogger(__name__)

MIN_FILE_MB: float = float(os.getenv("COMPRESS_MIN_FILE_MB", "20"))
MIN_PIC_BYTES: int = 150 * 1024  # 150 KB — skip tiny pictures
MAX_SIDE: int = int(os.getenv("COMPRESS_MAX_SIDE", "1920"))
JPEG_QUALITY: int = int(os.getenv("COMPRESS_JPEG_QUALITY", "80"))
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def _shrink(data: bytes, ext: str) -> bytes:
    """Re-encode one picture. Returns the original if it can't be shrunk."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return data

    if max(img.size) > MAX_SIDE:
        scale = MAX_SIDE / float(max(img.size))
        img = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.LANCZOS,
        )

    buf = io.BytesIO()
    try:
        if ext in (".jpg", ".jpeg"):
            img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
        elif ext == ".png":
            img.save(buf, "PNG", optimize=True)
        else:
            return data
    except Exception:
        return data

    result = buf.getvalue()
    return result if len(result) < len(data) else data


def compress_pptx(
    src: str,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """Compress images inside *src* (path to a .pptx on disk).

    The file is replaced **in-place** with the compressed version.
    Returns ``{"before_mb": ..., "after_mb": ..., "shrunk": int, "skipped": int}``.
    If the file is below ``MIN_FILE_MB`` the function returns immediately
    with ``{"skipped_reason": "too_small"}``.
    """
    src_path = Path(src)
    before_bytes = src_path.stat().st_size
    before_mb = before_bytes / 1_048_576

    if before_mb < MIN_FILE_MB:
        return {"skipped_reason": "too_small", "before_mb": round(before_mb, 1)}

    if on_progress:
        on_progress(f"Compressing images in the deck ({before_mb:.0f} MB). This speeds up processing.")

    # Work in a temp file next to the source so we can atomically replace.
    fd, tmp_path = tempfile.mkstemp(suffix=".pptx", dir=str(src_path.parent))
    os.close(fd)

    shrunk = 0
    skipped = 0

    try:
        with zipfile.ZipFile(str(src_path)) as zin, \
             zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                ext = Path(item.filename).suffix.lower()

                if (
                    item.filename.startswith("ppt/media/")
                    and ext in IMAGE_EXTS
                    and len(data) >= MIN_PIC_BYTES
                ):
                    new_data = _shrink(data, ext)
                    if len(new_data) < len(data):
                        shrunk += 1
                        data = new_data
                    else:
                        skipped += 1
                else:
                    skipped += 1

                # Don't re-compress media that's already compressed (video/audio).
                ctype = (
                    zipfile.ZIP_STORED
                    if ext in (".mp4", ".mov", ".mp3", ".m4a", ".avi", ".wmv")
                    else zipfile.ZIP_DEFLATED
                )
                zout.writestr(item, data, compress_type=ctype)

        after_bytes = os.path.getsize(tmp_path)
        after_mb = after_bytes / 1_048_576

        # Replace the original only if we actually saved space.
        if after_bytes < before_bytes:
            shutil.move(tmp_path, str(src_path))
            logger.info(
                "Compressed %s: %.1f MB -> %.1f MB (%d images shrunk)",
                src_path.name, before_mb, after_mb, shrunk,
            )
        else:
            os.unlink(tmp_path)
            after_mb = before_mb
            logger.info("Compression of %s saved no space, keeping original", src_path.name)

        if on_progress:
            saved_pct = max(0, int(100 - after_bytes * 100 / max(before_bytes, 1)))
            on_progress(
                f"Compressed: {before_mb:.0f} MB → {after_mb:.0f} MB ({saved_pct}% smaller, {shrunk} images shrunk)"
            )

        return {
            "before_mb": round(before_mb, 1),
            "after_mb": round(after_mb, 1),
            "shrunk": shrunk,
            "skipped": skipped,
        }

    except Exception as e:
        # If anything goes wrong, clean up and leave the original untouched.
        logger.warning("Compression failed for %s: %s — using original", src_path.name, e)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        if on_progress:
            on_progress(f"Compression skipped (error: {e}). Using original file.")
        return {"skipped_reason": "error", "error": str(e), "before_mb": round(before_mb, 1)}
