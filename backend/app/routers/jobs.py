import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models.job import IngestionJob
from backend.app.services.jobs.job_queue import get_job_queue_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Ingestion Jobs"])

def to_job_dict(job: IngestionJob) -> Dict[str, Any]:
    step_data = job.step_data or {}
    return {
        "id": job.id,
        "source_type": job.source_type,
        "source_file_id": job.source_file_id,
        "filename": job.filename,
        "blob_url": job.blob_url,
        "status": job.status,
        "current_step": job.current_step,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "error_message": job.error_message,
        "document_id": job.document_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "step_summary": {
            "slides_count": len(step_data.get("slides", [])),
            "media_count": len(step_data.get("media_manifest", [])),
            "media_cursor": step_data.get("media_cursor", 0),
            "questions_count": len(step_data.get("canonical_questions", [])),
            "exact_duplicates": step_data.get("exact_duplicates_count", 0),
        }
    }

@router.get("")
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status: PENDING, PROCESSING, COMPLETED, FAILED"),
    source_type: Optional[str] = Query(None, description="Filter by source_type: SHAREPOINT, MANUAL_UPLOAD"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List background ingestion jobs with status and step data summaries."""
    query = db.query(IngestionJob)
    if status:
        query = query.filter(IngestionJob.status == status)
    if source_type:
        query = query.filter(IngestionJob.source_type == source_type)

    total = query.count()
    items = query.order_by(IngestionJob.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "jobs": [to_job_dict(j) for j in items]
    }

@router.get("/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Fetch full details for an individual background ingestion job."""
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return to_job_dict(job)

@router.post("/process-next")
async def process_next_job_endpoint(db: Session = Depends(get_db)):
    """
    Worker invocation endpoint.
    Processes the next available step of the oldest pending/processing job.
    Designed for recurring cron triggers or client-side polling loops.
    """
    service = get_job_queue_service()
    try:
        job = await service.process_next_job(db)
        if not job:
            return {"status": "NO_JOBS_PENDING", "job": None}
        return {"status": "SUCCESS", "job": to_job_dict(job)}
    except Exception as e:
        logger.exception(f"Error processing next job: {e}")
        return {"status": "ERROR", "error": str(e)}

@router.post("/{job_id}/retry")
async def retry_job(job_id: str, db: Session = Depends(get_db)):
    """Resets a failed job to PENDING with reset retry count."""
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")

    job.status = "PENDING"
    job.retry_count = 0
    job.error_message = None
    db.commit()
    db.refresh(job)
    return {"message": "Job re-queued successfully", "job": to_job_dict(job)}

@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """Cancels a job and marks it as FAILED."""
    job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")

    job.status = "FAILED"
    job.error_message = "Cancelled by user"
    db.commit()
    db.refresh(job)
    return {"message": "Job cancelled", "job": to_job_dict(job)}
