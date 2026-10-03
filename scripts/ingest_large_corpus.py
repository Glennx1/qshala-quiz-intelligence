#!/usr/bin/env python3
"""
QShala Large Corpus & Batch Ingestion Engine
---------------------------------------------
Directly ingests large presentation decks (1 GB - 5 GB+), folders of PPTX/PDFs,
or bulk ZIP archives straight into the local/server Question Vault.

Bypasses:
- Vercel's 4.5 MB request payload limit
- Browser upload timeouts and network bandwidth
- Serverless function 10-60 second execution limits

Runs the complete 7-stage QShala ingestion pipeline:
1. Slide & Notes Extraction
2. Contextual Slide Classification (Question vs Answer vs Clue vs Title)
3. Question & Option Extraction
4. Configurable Multi-Topic Taxonomy Tagging
5. Pedagogical Difficulty Scoring (PDI) & Cognitive Depth
6. Canonical Two-Tier Deduplication & Provenance Linking
7. Database Registration
"""

import os
import sys
import uuid
import shutil
import zipfile
import asyncio
import argparse
from pathlib import Path

# Configure utf-8 encoding for Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.database import SessionLocal, engine, Base
from backend.app.models.document import Document
from backend.app.services.ingestion.pipeline import IngestionPipeline
from backend.app.config import settings

def find_decks(target_path: Path):
    """Finds all PPTX, PPT, and PDF files in a file, folder, or zip archive."""
    deck_files = []
    
    if target_path.is_file():
        ext = target_path.suffix.lower()
        if ext in [".pptx", ".ppt", ".pdf"]:
            deck_files.append(target_path)
        elif ext == ".zip":
            extract_dir = settings.UPLOAD_DIR / f"unzipped_{uuid.uuid4().hex[:8]}"
            extract_dir.mkdir(parents=True, exist_ok=True)
            print(f"📦 Unpacking ZIP archive: {target_path.name} -> {extract_dir}")
            with zipfile.ZipFile(target_path, "r") as z:
                z.extractall(extract_dir)
            for root, _, files in os.walk(extract_dir):
                for f in files:
                    if Path(f).suffix.lower() in [".pptx", ".ppt", ".pdf"]:
                        deck_files.append(Path(root) / f)
    elif target_path.is_dir():
        for root, _, files in os.walk(target_path):
            for f in files:
                if Path(f).suffix.lower() in [".pptx", ".ppt", ".pdf"]:
                    deck_files.append(Path(root) / f)
                    
    return deck_files

async def ingest_single_deck(pipeline: IngestionPipeline, deck_path: Path, year: int = 2024):
    """Ingests a single presentation deck through the QShala pipeline."""
    db = SessionLocal()
    try:
        doc_id = str(uuid.uuid4())
        ext = deck_path.suffix.lower()
        save_filename = f"{doc_id}{ext}"
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest_path = settings.UPLOAD_DIR / save_filename

        # Copy to storage
        shutil.copy2(deck_path, dest_path)
        file_size = dest_path.stat().st_size
        clean_title = deck_path.stem.replace("_", " ").title()

        doc = Document(
            id=doc_id,
            filename=deck_path.name,
            title=clean_title,
            year=year,
            file_type=ext.replace(".", ""),
            storage_path=str(dest_path),
            file_size_bytes=file_size,
            processing_status="PROCESSING"
        )
        db.add(doc)
        db.commit()

        print(f"\n🚀 Ingesting: {deck_path.name} ({file_size / (1024 * 1024):.1f} MB)")
        
        # Execute pipeline
        await pipeline.run(doc_id)

        # Query result stats
        db.refresh(doc)
        print(f"   ✅ Finished '{doc.title}':")
        print(f"      - Slides Processed: {doc.slide_count}")
        print(f"      - Questions Extracted: {doc.question_count}")
        print(f"      - Status: {doc.processing_status}")

        return {
            "title": doc.title,
            "slides": doc.slide_count,
            "questions": doc.question_count,
            "status": doc.processing_status
        }
    except Exception as e:
        print(f"   ❌ Failed to ingest {deck_path.name}: {e}")
        return {"title": deck_path.name, "error": str(e), "status": "FAILED"}
    finally:
        db.close()

async def main():
    parser = argparse.ArgumentParser(description="Directly ingest large presentation files/folders into QShala repository.")
    parser.add_argument("--path", "-p", required=True, help="Path to .pptx/.pdf file, folder of decks, or .zip archive")
    parser.add_argument("--year", "-y", type=int, default=2024, help="Tournament or academic year (default: 2024)")

    args = parser.parse_args()
    target = Path(args.path)

    if not target.exists():
        print(f"❌ Error: Path does not exist: {args.path}")
        sys.exit(1)

    print(f"\n=======================================================")
    print(f"📚 QShala Bulk Ingestion Engine")
    print(f"   Target: {target}")
    print(f"=======================================================")

    decks = find_decks(target)
    if not decks:
        print(f"⚠️ No .pptx, .ppt, or .pdf files found in {target}")
        sys.exit(0)

    print(f"Found {len(decks)} presentation deck(s) to process.")

    db = SessionLocal()
    pipeline = IngestionPipeline(db)

    total_questions = 0
    total_slides = 0
    successful = 0

    for idx, deck in enumerate(decks, start=1):
        print(f"\n[{idx}/{len(decks)}] Processing deck...")
        res = await ingest_single_deck(pipeline, deck, year=args.year)
        if res.get("status") == "COMPLETED":
            successful += 1
            total_questions += (res.get("questions") or 0)
            total_slides += (res.get("slides") or 0)

    db.close()

    print(f"\n=======================================================")
    print(f"🏁 Bulk Ingestion Summary:")
    print(f"   - Decks Processed: {successful} / {len(decks)}")
    print(f"   - Total Slides: {total_slides}")
    print(f"   - Total Questions Added to Vault: {total_questions}")
    print(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(main())
