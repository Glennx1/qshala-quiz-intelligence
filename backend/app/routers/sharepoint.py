import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from backend.app.database import get_db
from backend.app.models.sharepoint import SharePointSyncState, SharePointFile
from backend.app.models.job import IngestionJob
from backend.app.services.sharepoint.graph_client import get_sharepoint_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sharepoint", tags=["sharepoint"])

class SharePointSyncResponse(BaseModel):
    status: str
    pages_processed: int
    discovered_files_count: int
    enqueued_jobs_count: int
    deleted_files_count: int
    enqueued_job_ids: List[str]
    delta_token: Optional[str] = None

@router.post("/sync", response_model=SharePointSyncResponse)
async def trigger_sharepoint_sync(
    drive_id: Optional[str] = None,
    sync_state_id: str = "qshala_main_library",
    db: Session = Depends(get_db)
):
    """
    Triggers an incremental delta sync from Microsoft SharePoint document library.
    Discovers new/updated .pptx and .pdf decks, streams them to Vercel Blob,
    and enqueues background processing jobs.
    """
    client = get_sharepoint_client()
    try:
        result = await client.sync_delta(db, drive_id=drive_id, sync_state_id=sync_state_id)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception(f"SharePoint sync error: {e}")
        raise HTTPException(status_code=500, detail=f"SharePoint sync failed: {str(e)}")

@router.get("/status")
def get_sharepoint_sync_status(
    sync_state_id: str = "qshala_main_library",
    db: Session = Depends(get_db)
):
    """
    Returns current sync state, last sync timestamp, tracked file count, and health status.
    """
    state = db.query(SharePointSyncState).filter(SharePointSyncState.id == sync_state_id).first()
    if not state:
        return {
            "id": sync_state_id,
            "status": "NOT_CONFIGURED",
            "last_sync_at": None,
            "total_files_tracked": 0,
            "last_error": None
        }

    return {
        "id": state.id,
        "site_id": state.site_id,
        "drive_id": state.drive_id,
        "status": state.status,
        "last_sync_at": state.last_sync_at.isoformat() if state.last_sync_at else None,
        "total_files_tracked": state.total_files_tracked,
        "last_error": state.last_error
    }

@router.get("/files")
def list_sharepoint_files(
    sync_status: Optional[str] = Query(None, description="Filter by status: DISCOVERED, QUEUED, COMPLETED, FAILED, DELETED"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Lists files discovered in SharePoint along with their synchronization and ingestion status.
    """
    query = db.query(SharePointFile)
    if sync_status:
        query = query.filter(SharePointFile.sync_status == sync_status)

    total = query.count()
    items = query.order_by(SharePointFile.last_modified_date_time.desc().nullslast()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "files": [
            {
                "id": f.id,
                "name": f.name,
                "web_url": f.web_url,
                "file_size_bytes": f.file_size_bytes,
                "last_modified_date_time": f.last_modified_date_time.isoformat() if f.last_modified_date_time else None,
                "blob_url": f.blob_url,
                "sync_status": f.sync_status,
                "error_message": f.error_message
            }
            for f in items
        ]
    }

@router.post("/files/{file_id}/re-queue")
def requeue_sharepoint_file(
    file_id: str,
    db: Session = Depends(get_db)
):
    """
    Re-queues a failed or pending SharePoint file for ingestion.
    """
    sp_file = db.query(SharePointFile).filter(SharePointFile.id == file_id).first()
    if not sp_file:
        raise HTTPException(status_code=404, detail="SharePoint file not found")

    if not sp_file.blob_url:
        raise HTTPException(status_code=400, detail="File has no blob_url yet; run sync first")

    # Create new job
    job = IngestionJob(
        source_type="SHAREPOINT",
        source_file_id=sp_file.id,
        filename=sp_file.name,
        blob_url=sp_file.blob_url,
        status="PENDING",
        current_step="DOWNLOAD",
        step_data={"sharepoint_item_id": sp_file.id}
    )
    sp_file.sync_status = "QUEUED"
    sp_file.error_message = None
    db.add(job)
    db.commit()
    db.refresh(job)

    return {"message": "File re-queued successfully", "job_id": job.id}
