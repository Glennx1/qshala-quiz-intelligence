import logging
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

logger = logging.getLogger(__name__)

# Maximum file size allowed by Vercel Serverless Functions payload (4.5 MB)
MAX_FILE_SIZE_BYTES = 4 * 1024 * 1024 + 512 * 1024  # 4.5 MB

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    logger.info(f"[UPLOAD] request received: filename={file.filename}, content_type={file.content_type}")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pptx", ".ppt", ".pdf"]:
        logger.warning(f"[UPLOAD] rejected unsupported extension: {ext}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Only PDF and PowerPoint (PPT, PPTX) files are supported."
        )

    doc_id = str(uuid.uuid4())
    save_filename = f"{doc_id}{ext}"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = str(settings.UPLOAD_DIR / save_filename)

    logger.info(f"[UPLOAD] storage started: doc_id={doc_id}, dest={storage_path}")

    # Stream file to disk with strict size limit enforcement
    file_size = 0
    try:
        with open(storage_path, "wb") as buffer:
            chunk_size = 64 * 1024  # 64 KB chunks
            while chunk := await file.read(chunk_size):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE_BYTES:
                    buffer.close()
                    if os.path.exists(storage_path):
                        os.remove(storage_path)
                    logger.warning(f"[UPLOAD] file exceeds size limit: {file_size} > {MAX_FILE_SIZE_BYTES}")
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum allowed upload size of 4.5 MB on Vercel Serverless Functions (received {file_size / (1024 * 1024):.1f} MB)."
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[UPLOAD] failed while saving file: {e}")
        if os.path.exists(storage_path):
            try:
                os.remove(storage_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")

    logger.info(f"[UPLOAD] storage completed: doc_id={doc_id}, size={file_size} bytes")
    clean_title = title or os.path.splitext(file.filename)[0].replace("_", " ").title()

    try:
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
    except Exception as e:
        logger.exception(f"[UPLOAD] database record creation failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error while registering document.")

    logger.info(f"[UPLOAD] document record created: id={doc_id}, status=PROCESSING")

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

    # Run ingestion pipeline asynchronously with its own database session
    pipeline = IngestionPipeline()
    background_tasks.add_task(pipeline.run, doc_id)
    logger.info(f"[UPLOAD] background ingestion scheduled for doc_id={doc_id}")

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
