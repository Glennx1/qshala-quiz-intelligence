import os
import shutil
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models.document import Document, Slide
from backend.app.schemas.document import DocumentResponse, IngestionStatusResponse, SlideResponse
from backend.app.services.ingestion.pipeline import IngestionPipeline, INGESTION_STATUS_REGISTRY
from backend.app.config import settings

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pptx", ".ppt", ".pdf"]:
        raise HTTPException(status_code=400, detail=f"Unsupported file format '{ext}'. Only PPT, PPTX, and PDF are supported.")

    doc_id = str(uuid.uuid4())
    save_filename = f"{doc_id}{ext}"
    storage_path = str(settings.UPLOAD_DIR / save_filename)

    with open(storage_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = os.path.getsize(storage_path)
    clean_title = title or os.path.splitext(file.filename)[0].replace("_", " ").title()

    doc = Document(
        id=doc_id,
        filename=file.filename,
        title=clean_title,
        year=year or 2024,
        file_type=ext.replace(".", ""),
        storage_path=storage_path,
        file_size_bytes=file_size,
        processing_status="PROCESSING"
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Initialize tracking
    INGESTION_STATUS_REGISTRY[doc_id] = {
        "document_id": doc_id,
        "status": "PROCESSING",
        "progress_percentage": 5,
        "current_step": "1. Extracting content",
        "slides_processed": 0,
        "questions_extracted": 0,
        "error": None
    }

    # Run ingestion pipeline
    pipeline = IngestionPipeline(db)
    background_tasks.add_task(pipeline.run, doc_id)

    return doc

@router.get("", response_model=List[DocumentResponse])
def list_documents(db: Session = Depends(get_db)):
    return db.query(Document).order_by(Document.created_at.desc()).all()

@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

@router.get("/{document_id}/slides", response_model=List[SlideResponse])
def get_document_slides(document_id: str, db: Session = Depends(get_db)):
    slides = db.query(Slide).filter(Slide.document_id == document_id).order_by(Slide.slide_number.asc()).all()
    return slides

@router.get("/{document_id}/status", response_model=IngestionStatusResponse)
def get_ingestion_status(document_id: str, db: Session = Depends(get_db)):
    if document_id in INGESTION_STATUS_REGISTRY:
        return INGESTION_STATUS_REGISTRY[document_id]

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "document_id": doc.id,
        "status": doc.processing_status,
        "progress_percentage": 100 if doc.processing_status == "COMPLETED" else 0,
        "current_step": "Completed" if doc.processing_status == "COMPLETED" else doc.processing_status,
        "slides_processed": doc.slide_count,
        "questions_extracted": doc.question_count,
        "error": doc.processing_error
    }

@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if os.path.exists(doc.storage_path):
        try:
            os.remove(doc.storage_path)
        except Exception:
            pass

    db.delete(doc)
    db.commit()
    return {"message": "Document deleted successfully"}
