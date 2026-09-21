import asyncio
import os
import sys
import shutil
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.app.database import SessionLocal, engine, Base
from backend.app.models.document import Document
from backend.app.services.ingestion.pipeline import IngestionPipeline
from backend.app.config import settings

async def seed(force: bool = False):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    pipeline = IngestionPipeline(db)

    sample_dir = Path(__file__).resolve().parent.parent.parent / "sample_decks"
    files_to_seed = [
        ("Australian_History_Quiz_2022.pptx", "Australian History & Explorers Tournament (Grades 3-5)", 2022),
        ("World_Geography_and_Oceans_2023.pptx", "QShala Junior Explorers: World Wonders & Oceans", 2023),
    ]

    for fname, title, year in files_to_seed:
        src = sample_dir / fname
        if not src.exists():
            print(f"Skipping {fname} (not found)")
            continue

        existing = db.query(Document).filter(Document.filename == fname).first()
        if existing:
            if force:
                print(f"Re-seeding {fname}...")
                db.delete(existing)
                db.commit()
            else:
                print(f"Document {fname} already seeded.")
                continue

        dest = settings.UPLOAD_DIR / fname
        shutil.copyfile(src, dest)

        doc = Document(
            filename=fname,
            title=title,
            year=year,
            file_type="pptx",
            storage_path=str(dest),
            file_size_bytes=dest.stat().st_size,
            processing_status="PROCESSING"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        print(f"Ingesting {fname} into QShala knowledge base...")
        await pipeline.run(doc.id)
        db.refresh(doc)
        print(f" -> {fname}: Status={doc.processing_status}, Slides={doc.slide_count}, Questions={doc.question_count}")

    db.close()
    print("Seeding complete.")

if __name__ == "__main__":
    asyncio.run(seed(force=True))
