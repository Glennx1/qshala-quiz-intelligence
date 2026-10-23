"""Shrink the pictures inside a .pptx so it uploads and processes faster.

    python scripts/compress_pptx.py "C:\\path\\to\\deck.pptx"
    python scripts/compress_pptx.py "C:\\path\\to\\folder"          # every .pptx in the folder
    python scripts/compress_pptx.py deck.pptx --max-side 1600 --quality 75

The original is never changed. A copy named "<name>_compressed.pptx" is written next to it.
Pictures keep their file type (so slide links still work); photos are re-saved as smaller JPEGs and
large pictures are scaled down. Audio and video are left alone. Needs: pip install pillow
"""
import argparse
import io
import sys
import zipfile
from pathlib import Path

from PIL import Image

MIN_BYTES = 150 * 1024          # leave small pictures alone


def shrink_image(data: bytes, ext: str, max_side: int, quality: int) -> bytes:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return data
    resized = False
    if max(img.size) > max_side:
        scale = max_side / float(max(img.size))
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
        resized = True
    out = io.BytesIO()
    try:
        if ext in (".jpg", ".jpeg"):
            img.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)
        elif ext == ".png":
            img.save(out, "PNG", optimize=True)
        else:
            return data
    except Exception:
        return data
    new = out.getvalue()
    # Only keep the result if it is actually smaller (a re-save can make a tiny PNG bigger).
    return new if len(new) < len(data) or resized and len(new) < len(data) * 1.0 else data


def compress(src: Path, max_side: int, quality: int) -> Path:
    dst = src.with_name(src.stem + "_compressed.pptx")
    before = src.stat().st_size
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            ext = Path(item.filename).suffix.lower()
            if item.filename.startswith("ppt/media/") and ext in (".jpg", ".jpeg", ".png") and len(data) >= MIN_BYTES:
                data = shrink_image(data, ext, max_side, quality)
            zout.writestr(item, data, compress_type=zipfile.ZIP_STORED if ext in (".mp4", ".mov", ".mp3", ".m4a") else zipfile.ZIP_DEFLATED)
    after = dst.stat().st_size
    print(f"{src.name}: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB ({100 - after * 100 // max(before, 1)}% smaller) -> {dst.name}")
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--max-side", type=int, default=1920, help="longest picture side in pixels (default 1920)")
    ap.add_argument("--quality", type=int, default=80, help="JPEG quality 1-95 (default 80)")
    a = ap.parse_args()
    p = Path(a.path)
    files = sorted(p.glob("*.pptx")) if p.is_dir() else [p]
    files = [f for f in files if not f.stem.endswith("_compressed")]
    if not files:
        print("No .pptx files found.")
        return 1
    for f in files:
        try:
            compress(f, a.max_side, a.quality)
        except Exception as e:
            print(f"{f.name}: failed ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
