#!/usr/bin/env python3
"""
QShala Deck Media Optimizer & Stripper
--------------------------------------
Converts massive (1 GB - 3 GB) QShala presentation decks with embedded
tournament videos, audio clips, and uncompressed media into clean, lightweight
(< 5 MB) decks ready for Vercel upload and instant AI ingestion.

Retains 100% of:
- Slide text, questions, answers, and options
- Shape structures and tables
- Slide titles and layout sequence
- Presenter speaker notes
"""

import os
import sys
import zipfile
import argparse
from pathlib import Path

# Configure utf-8 encoding for Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Media extensions that make presentation decks gigantic (often 99% of file size)
HEAVY_MEDIA_EXTS = {
    ".mp4", ".mov", ".avi", ".wmv", ".m4v", ".flv", ".webm",  # Videos
    ".mp3", ".wav", ".m4a", ".aac", ".wma", ".ogg",           # Audio
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}

def optimize_pptx(input_path: str, output_path: str, max_image_mb: float = 1.0) -> dict:
    """
    Strips heavy video and audio streams from a PPTX zip container,
    replacing them with empty stubs, and generates a lightweight copy.
    """
    in_file = Path(input_path)
    out_file = Path(output_path)
    
    if not in_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    original_size = in_file.stat().st_size
    original_mb = original_size / (1024 * 1024)

    print(f"\n=======================================================")
    print(f"📦 QShala Deck Optimizer: {in_file.name}")
    print(f"   Original Size: {original_mb:.1f} MB ({original_size:,} bytes)")
    print(f"=======================================================")

    stripped_media_count = 0
    preserved_files_count = 0
    saved_bytes = 0

    with zipfile.ZipFile(in_file, "r") as zin:
        with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                filename = item.filename
                ext = Path(filename).suffix.lower()

                # Case 1: Video or Audio stream inside ppt/media/
                if "ppt/media/" in filename and ext in HEAVY_MEDIA_EXTS:
                    # Replace with 0-byte stub to preserve XML relationship references
                    zout.writestr(item, b"")
                    stripped_media_count += 1
                    saved_bytes += item.file_size
                    print(f"   ✂️ Stripped video/audio: {Path(filename).name} ({item.file_size / (1024 * 1024):.1f} MB)")
                
                # Case 2: Extremely large image (> max_image_mb)
                elif "ppt/media/" in filename and ext in IMAGE_EXTS and item.file_size > (max_image_mb * 1024 * 1024):
                    # Keep tiny 1x1 transparent GIF/stub to avoid breaking presentation
                    stub_png = (
                        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
                        b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
                    )
                    zout.writestr(item, stub_png)
                    stripped_media_count += 1
                    saved_bytes += (item.file_size - len(stub_png))
                    print(f"   🖼️ Stripped giant image: {Path(filename).name} ({item.file_size / (1024 * 1024):.1f} MB)")

                # Case 3: Essential XML, slides, notes, text, relationships, and normal graphics
                else:
                    data = zin.read(filename)
                    zout.writestr(item, data)
                    preserved_files_count += 1

    new_size = out_file.stat().st_size
    new_mb = new_size / (1024 * 1024)
    reduction_pct = (1.0 - (new_size / original_size)) * 100 if original_size > 0 else 0

    print(f"\n✅ Optimization Complete!")
    print(f"   New File: {out_file.name}")
    print(f"   New Size: {new_mb:.2f} MB ({new_size:,} bytes)")
    print(f"   Size Reduction: -{reduction_pct:.1f}%")
    print(f"   Stripped Media Assets: {stripped_media_count}")
    print(f"   Preserved XML/Slide Assets: {preserved_files_count}")

    if new_mb <= 4.5:
        print(f"   🎉 Ready for Vercel upload! (Under 4.5 MB limit)")
    else:
        print(f"   ℹ️ If still above 4.5 MB, use scripts/ingest_large_corpus.py for direct local ingestion.")

    return {
        "original_mb": original_mb,
        "new_mb": new_mb,
        "reduction_pct": reduction_pct,
        "stripped_count": stripped_media_count,
        "output_path": str(out_file)
    }

def main():
    parser = argparse.ArgumentParser(description="Strip video/audio media from massive QShala PPTX decks for Vercel compatibility.")
    parser.add_argument("--input", "-i", required=True, help="Path to input .pptx file")
    parser.add_argument("--output", "-o", help="Path to output .pptx file (default: input_optimized.pptx)")
    parser.add_argument("--max-image-mb", type=float, default=1.5, help="Strip images larger than this size in MB (default: 1.5)")

    args = parser.parse_args()
    
    in_path = Path(args.input)
    if not args.output:
        out_path = in_path.parent / f"{in_path.stem}_optimized{in_path.suffix}"
    else:
        out_path = Path(args.output)

    optimize_pptx(str(in_path), str(out_path), max_image_mb=args.max_image_mb)

if __name__ == "__main__":
    main()
