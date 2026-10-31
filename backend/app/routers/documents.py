import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models.document import Document, Slide
from backend.app.schemas.document import DocumentResponse, IngestionStatusResponse, SlideResponse
from backend.app.services.ingestion.pipeline import IngestionPipeline, INGESTION_STATUS_REGISTRY
from backend.app.config import settings
from backend.app.services.ingestion.cancellation import (
    valid_upload_id,
    request_upload_cancel,
    upload_cancel_requested,
    remove_chunk_dir,
    request_doc_cancel,
    purge_document,
)

logger = logging.getLogger(__name__)


def _schedule_ingestion(doc, db: Session, background_tasks: BackgroundTasks, raw_already_in_r2: bool = False) -> None:
    """Start ingestion for an uploaded deck.

    Three modes, in priority order:
      1. INGESTION_MODE=cloud_run_job -- offload to a separate Cloud Run Job execution (worker.py)
         so a heavy deck can't starve the API process's own request handling or memory. See
         job_trigger.py. Opt-in; default is unchanged (in_process below).
      2. UPLOAD_QUEUE_ENABLED (default on) -- enqueue a job and let the single serial worker
         process it over time — several uploads then ingest one-at-a-time instead of all at once
         (which OOMs a small host).
      3. Neither -- the old immediate per-upload background task, in-process.

    `raw_already_in_r2` is set by /upload-chunk when it streamed the slices straight into an R2
    multipart upload as they arrived (see _upload_chunk_direct_to_r2) -- in that case the raw deck
    is already sitting at the exact key this function would otherwise stage it to, so the
    read-local-file-and-re-upload step below is skipped entirely.
    """
    if settings.INGESTION_MODE == "cloud_run_job":
        from backend.app.services.ingestion.job_trigger import trigger_ingestion_job, IngestionJobTriggerError
        from backend.app.services.storage.r2_storage import get_r2_service
        # Deliberately does NOT write to INGESTION_STATUS_REGISTRY: that dict is this process's
        # own memory, but the pipeline runs inside a separate worker container for this mode. An
        # entry written here would never be updated again -- the worker can't see this process's
        # memory any more than this process can see the worker's -- which would permanently mask
        # the real status behind a frozen "just started" snapshot. (This was a real bug in the
        # first version of this code path: every poll kept returning this stale entry instead of
        # falling through to live data.) The /status endpoint's existing DB fallback
        # (Document.processing_status/slide_count/question_count/processing_error, all written
        # by the pipeline itself regardless of which process runs it) is what actually reflects
        # progress here -- the same fallback that already covers "a document this process never
        # saw ingestion start for," e.g. after a restart.

        # The raw deck this process just streamed to local disk (doc.storage_path) lives only in
        # THIS container's own ephemeral filesystem -- the worker Job runs in a completely
        # separate container with its own empty disk and never sees it (this caused every
        # cloud_run_job upload to fail with FileNotFoundError in pptx_parser). Stage it in R2
        # under a key the worker can derive from doc.id/extension, so worker.py can fetch it
        # before handing off to the unmodified pipeline, which still just reads doc.storage_path.
        r2 = get_r2_service()
        if not r2.is_configured:
            logger.error(
                "[UPLOAD] INGESTION_MODE=cloud_run_job requires R2 to hand the raw deck to the "
                "worker, but R2 isn't configured (doc_id=%s)", doc.id,
            )
            doc.processing_status = "FAILED"
            doc.processing_error = (
                "Server misconfiguration: R2 storage must be configured for Cloud Run Job "
                "ingestion mode (the worker can't otherwise see the uploaded file)."
            )
            db.commit()
            return
        if raw_already_in_r2:
            logger.info("[UPLOAD] raw deck already staged in R2 via chunk-streamed multipart upload: doc_id=%s", doc.id)
        else:
            try:
                raw_key = f"raw-uploads/{doc.id}{os.path.splitext(doc.storage_path)[1]}"
                r2.upload_file(raw_key, doc.storage_path)
                logger.info("[UPLOAD] staged raw deck in R2 for worker: doc_id=%s key=%s", doc.id, raw_key)
            except Exception as e:
                logger.exception("[UPLOAD] failed to stage raw deck in R2 for doc_id=%s: %s", doc.id, e)
                doc.processing_status = "FAILED"
                doc.processing_error = f"Failed to stage upload for ingestion worker: {e}"
                db.commit()
                return

        try:
            trigger_ingestion_job(doc.id)
            logger.info("[UPLOAD] Cloud Run Job triggered for doc_id=%s", doc.id)
        except IngestionJobTriggerError as e:
            # Fail loudly and visibly rather than leaving the deck stuck at PENDING with no
            # indication why -- same philosophy as the rest of this priority plan's fixes.
            logger.error("[UPLOAD] failed to start ingestion job for doc_id=%s: %s", doc.id, e)
            doc.processing_status = "FAILED"
            doc.processing_error = str(e)
            db.commit()
        return
    if settings.UPLOAD_QUEUE_ENABLED:
        from backend.app.services.ingestion import upload_queue
        job = upload_queue.enqueue_upload(db, document_id=doc.id, filename=doc.filename)
        pos = upload_queue.queue_position(db, job)
        INGESTION_STATUS_REGISTRY[doc.id] = {
            "document_id": doc.id, "status": "QUEUED", "progress_percentage": 0,
            "current_step": f"Queued (position {pos + 1}) — processing one deck at a time",
            "slides_processed": 0, "questions_extracted": 0, "error": None,
        }
        # Kick a drainer so the queue is actually worked off, without relying on the long-lived
        # background worker (which may not run under some deployments). Serial + idempotent: if a
        # drainer is already going, this one exits immediately.
        background_tasks.add_task(upload_queue.drain)
        logger.info("[UPLOAD] queued doc_id=%s (job=%s, position=%d)", doc.id, job.id, pos)
    else:
        INGESTION_STATUS_REGISTRY[doc.id] = {
            "document_id": doc.id, "status": "PROCESSING", "progress_percentage": 5,
            "current_step": "1. Extracting content", "slides_processed": 0,
            "questions_extracted": 0, "error": None,
        }
        background_tasks.add_task(IngestionPipeline().run, doc.id)
        logger.info("[UPLOAD] background ingestion scheduled for doc_id=%s", doc.id)


# Determine environment: Vercel serverless has a hard 4.5 MB request ceiling.
# Off Vercel (Railway, a VM, local dev) the app streams the upload straight to disk,
# so the ceiling is configurable via the MAX_UPLOAD_MB env var (default 2048 MB = 2 GB).
# Both the direct and chunked upload paths enforce this same ceiling.
is_vercel = bool(os.environ.get("VERCEL"))

def _max_upload_bytes() -> int:
    if is_vercel:
        return 4 * 1024 * 1024 + 512 * 1024  # 4.5 MB hard platform limit on Vercel serverless
    try:
        mb = int(os.environ.get("MAX_UPLOAD_MB", "2048"))
    except (TypeError, ValueError):
        mb = 2048
    return max(mb, 1) * 1024 * 1024

MAX_FILE_SIZE_BYTES = _max_upload_bytes()
MAX_FILE_SIZE_MB = MAX_FILE_SIZE_BYTES / (1024 * 1024)

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
                    limit_desc = "4.5 MB on Vercel Serverless" if is_vercel else f"{MAX_FILE_SIZE_MB:.0f} MB"
                    logger.warning(f"[UPLOAD] file exceeds size limit: {file_size} > {MAX_FILE_SIZE_BYTES}")
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File exceeds maximum allowed upload size ({limit_desc}). "
                            f"Received {file_size / (1024 * 1024):.1f} MB. "
                            + ("To upload via Vercel, run 'python scripts/optimize_qshala_deck.py -i <deck.pptx>' "
                               "to strip heavy media, or raise MAX_UPLOAD_MB on the backend and upload directly."
                               if is_vercel else
                               "Raise the MAX_UPLOAD_MB environment variable on the backend to allow a larger file.")
                        )
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
            year=year or datetime.now().year,
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

    _schedule_ingestion(doc, db, background_tasks)
    return doc

_MULTIPART_STATE_FILE = "r2_multipart_state.json"


async def _upload_chunk_direct_to_r2(
    chunk_dir, chunk: UploadFile, upload_id: str, chunk_index: int, total_chunks: int,
    ext: str, filename: str, title: Optional[str], year: Optional[int],
    r2, db: Session, background_tasks: BackgroundTasks,
):
    """The cloud_run_job+R2 path for /upload-chunk: every slice goes straight into an R2
    multipart upload (one part per slice -- the frontend's 24 MB slices are already well above
    S3/R2's 5 MB minimum part size, and the last part is exempt from that minimum anyway).

    State (the doc id, R2's own multipart UploadId, and the ETag of each part received so far)
    lives in a small JSON file under the same tmp_chunks/<upload_id> directory the old local-disk
    path used for its .part files -- that's a few hundred bytes of bookkeeping, not the deck
    itself, and `remove_chunk_dir` already cleans it up on completion or cancellation. Keyed by
    part number rather than assumed-sequential, since retries or concurrent requests could land
    parts out of order; R2/S3 multipart doesn't require them in order either.

    Carries over the same MAX_FILE_SIZE_BYTES ceiling the old stitch-then-check path enforced,
    checked cumulatively per part instead of once at the end (there's no final stitched file to
    measure here).
    """
    state_path = chunk_dir / _MULTIPART_STATE_FILE

    if not state_path.exists():
        if chunk_index != 0:
            # The chunk that would have created this state (index 0) hasn't landed here yet --
            # most likely still in flight, or it landed on a different Cloud Run instance (the
            # old local-disk path has this exact same single-instance assumption, so this isn't
            # a new limitation). The frontend's chunk upload already retries on failure.
            raise HTTPException(
                status_code=409,
                detail="Upload not yet initialized for this slice; retrying should resolve it.",
            )
        doc_id = str(uuid.uuid4())
        raw_key = f"raw-uploads/{doc_id}{ext}"
        r2_upload_id = r2.create_multipart_upload(raw_key)
        state = {
            "doc_id": doc_id, "raw_key": raw_key, "r2_upload_id": r2_upload_id,
            "filename": filename, "title": title, "year": year,
            "parts": {}, "total_bytes": 0,
        }
    else:
        state = json.loads(state_path.read_text())

    body = await chunk.read()
    new_total = state["total_bytes"] + len(body)
    if new_total > MAX_FILE_SIZE_BYTES:
        r2.abort_multipart_upload(state["raw_key"], state["r2_upload_id"])
        remove_chunk_dir(upload_id)
        raise HTTPException(
            status_code=413,
            detail=(f"Upload ({new_total / (1024 * 1024):.1f} MB so far) exceeds the maximum "
                    f"upload size ({MAX_FILE_SIZE_MB:.0f} MB). Raise MAX_UPLOAD_MB on the backend."),
        )

    etag = r2.upload_part(state["raw_key"], state["r2_upload_id"], chunk_index + 1, body)
    state["parts"][str(chunk_index + 1)] = etag
    state["total_bytes"] = new_total
    state_path.write_text(json.dumps(state))

    # A cancel may have landed while this slice was still uploading: discard everything.
    if upload_cancel_requested(upload_id):
        r2.abort_multipart_upload(state["raw_key"], state["r2_upload_id"])
        remove_chunk_dir(upload_id)
        raise HTTPException(status_code=409, detail="Upload was cancelled.")

    if len(state["parts"]) < total_chunks:
        return {
            "status": "CHUNK_RECEIVED",
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "progress_percentage": round((len(state["parts"]) / total_chunks) * 100),
        }

    # All parts received -- finish the multipart upload. The raw deck now exists in R2 and
    # nothing was ever written to local disk.
    parts = [{"PartNumber": int(pn), "ETag": tag} for pn, tag in state["parts"].items()]
    r2.complete_multipart_upload(state["raw_key"], state["r2_upload_id"], parts)

    doc_id = state["doc_id"]
    save_filename = f"{doc_id}{ext}"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Never actually written here -- worker.py's _fetch_raw_deck downloads the R2 object to this
    # exact local path before ingestion runs, same as it already does for a cancelled-mid-way
    # local upload. Kept as the same path shape as the local-disk path purely so every other
    # piece of code that reads doc.storage_path (extension sniffing, cleanup on delete, etc.)
    # keeps working unchanged.
    storage_path = str(settings.UPLOAD_DIR / save_filename)

    try:
        remove_chunk_dir(upload_id)
    except Exception as e:
        logger.warning(f"[UPLOAD-CHUNK] failed to remove temporary state dir {chunk_dir}: {e}")

    clean_title = state.get("title") or os.path.splitext(state["filename"])[0].replace("_", " ").title()

    try:
        doc = Document(
            id=doc_id,
            filename=state["filename"],
            title=clean_title,
            year=state.get("year") or datetime.now().year,
            file_type=ext.replace(".", ""),
            storage_path=storage_path,
            file_size_bytes=state["total_bytes"],
            processing_status="PROCESSING",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as e:
        logger.exception(f"[UPLOAD-CHUNK] database record creation failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error while registering document.")

    logger.info(f"[UPLOAD-CHUNK] file streamed directly to R2: doc_id={doc_id} key={state['raw_key']}")

    _schedule_ingestion(doc, db, background_tasks, raw_already_in_r2=True)

    return {
        "status": "COMPLETED",
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "title": doc.title,
            "year": doc.year,
            "file_type": doc.file_type,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "storage_path": doc.storage_path,
            "file_size_bytes": doc.file_size_bytes,
            "slide_count": doc.slide_count,
            "question_count": doc.question_count,
            "processing_status": doc.processing_status,
            "processing_error": doc.processing_error,
        },
    }


@router.post("/upload-chunk")
async def upload_document_chunk(
    background_tasks: BackgroundTasks,
    chunk: UploadFile = File(...),
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    filename: str = Form(...),
    title: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Receives one slice of a presentation file (the frontend sends 20 MB slices).
    When all slices are received, stitches the complete file together and starts ingestion.
    A cancelled upload_id (see DELETE /upload-chunk/{upload_id}) is refused with 409.
    """
    if not valid_upload_id(upload_id):
        raise HTTPException(status_code=400, detail="Invalid upload_id.")
    if upload_cancel_requested(upload_id):
        remove_chunk_dir(upload_id)
        raise HTTPException(status_code=409, detail="Upload was cancelled.")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".pptx", ".ppt", ".pdf"]:
        logger.warning(f"[UPLOAD-CHUNK] rejected unsupported extension: {ext}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Only PDF and PowerPoint (PPT, PPTX) files are supported."
        )

    chunk_dir = settings.STORAGE_DIR / "tmp_chunks" / upload_id
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # When ingestion runs on a separate Cloud Run Job and R2 is configured, stream each slice
    # straight into an R2 multipart upload as it arrives instead of writing it to local disk and
    # stitching a full copy afterward -- the worker already fetches the raw deck from R2 (see
    # _fetch_raw_deck in worker.py), so a local copy here is pure overhead that mode never needs.
    # Every other mode (in_process, the upload queue, or R2 not configured) falls through to the
    # original local-disk path below completely untouched.
    from backend.app.services.storage.r2_storage import get_r2_service
    r2 = get_r2_service()
    if settings.INGESTION_MODE == "cloud_run_job" and r2.is_configured:
        return await _upload_chunk_direct_to_r2(
            chunk_dir=chunk_dir, chunk=chunk, upload_id=upload_id,
            chunk_index=chunk_index, total_chunks=total_chunks,
            ext=ext, filename=filename, title=title, year=year,
            r2=r2, db=db, background_tasks=background_tasks,
        )

    chunk_path = chunk_dir / f"chunk_{chunk_index:05d}.part"

    # Stream chunk to disk
    with open(chunk_path, "wb") as f:
        while content := await chunk.read(64 * 1024):
            f.write(content)

    # A cancel may have landed while this slice was still streaming in: drop everything.
    if upload_cancel_requested(upload_id):
        remove_chunk_dir(upload_id)
        raise HTTPException(status_code=409, detail="Upload was cancelled.")

    parts = list(chunk_dir.glob("chunk_*.part"))
    if len(parts) < total_chunks:
        return {
            "status": "CHUNK_RECEIVED",
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "progress_percentage": round(((len(parts)) / total_chunks) * 100)
        }

    # All chunks received! Stitch them together
    doc_id = str(uuid.uuid4())
    save_filename = f"{doc_id}{ext}"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = str(settings.UPLOAD_DIR / save_filename)

    file_size = 0
    with open(storage_path, "wb") as outfile:
        for part_file in sorted(chunk_dir.glob("chunk_*.part")):
            with open(part_file, "rb") as infile:
                shutil.copyfileobj(infile, outfile)
            file_size += os.path.getsize(part_file)

    # Enforce the same ceiling as the direct path (chunked bypasses Vercel's limit but
    # must still respect MAX_UPLOAD_MB so a runaway upload can't fill the disk).
    if file_size > MAX_FILE_SIZE_BYTES:
        for p in (storage_path,):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        try:
            shutil.rmtree(chunk_dir)
        except Exception:
            pass
        raise HTTPException(
            status_code=413,
            detail=(f"Reassembled file ({file_size / (1024 * 1024):.1f} MB) exceeds the maximum "
                    f"upload size ({MAX_FILE_SIZE_MB:.0f} MB). Raise MAX_UPLOAD_MB on the backend.")
        )

    # Clean up chunk directory
    try:
        shutil.rmtree(chunk_dir)
    except Exception as e:
        logger.warning(f"[UPLOAD-CHUNK] failed to remove temporary chunk directory {chunk_dir}: {e}")

    clean_title = title or os.path.splitext(filename)[0].replace("_", " ").title()

    try:
        doc = Document(
            id=doc_id,
            filename=filename,
            title=clean_title,
            year=year or datetime.now().year,
            file_type=ext.replace(".", ""),
            storage_path=storage_path,
            file_size_bytes=file_size,
            processing_status="PROCESSING"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as e:
        logger.exception(f"[UPLOAD-CHUNK] database record creation failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error while registering document.")

    logger.info(f"[UPLOAD-CHUNK] file reassembled successfully: doc_id={doc_id}, size={file_size} bytes")

    _schedule_ingestion(doc, db, background_tasks)

    return {
        "status": "COMPLETED",
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "title": doc.title,
            "year": doc.year,
            "file_type": doc.file_type,
            "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            "storage_path": doc.storage_path,
            "file_size_bytes": doc.file_size_bytes,
            "slide_count": doc.slide_count,
            "question_count": doc.question_count,
            "processing_status": doc.processing_status,
            "processing_error": doc.processing_error
        }
    }

@router.delete("/upload-chunk/{upload_id}")
def cancel_chunked_upload(upload_id: str):
    """Cancel an in-progress chunked upload: refuse any further slices and delete what arrived."""
    if not valid_upload_id(upload_id):
        raise HTTPException(status_code=400, detail="Invalid upload_id.")
    request_upload_cancel(upload_id)

    # If this upload was streaming straight into an R2 multipart upload (cloud_run_job mode),
    # abort that too -- otherwise the parts already received linger in R2 as billable incomplete
    # storage forever, since nothing else ever completes or expires them.
    state_path = settings.STORAGE_DIR / "tmp_chunks" / upload_id / _MULTIPART_STATE_FILE
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            from backend.app.services.storage.r2_storage import get_r2_service
            get_r2_service().abort_multipart_upload(state["raw_key"], state["r2_upload_id"])
        except Exception as e:
            logger.warning(f"[UPLOAD-CHUNK] failed to abort R2 multipart upload for {upload_id}: {e}")

    remove_chunk_dir(upload_id)
    logger.info(f"[UPLOAD-CHUNK] upload {upload_id} cancelled by user, slices removed")
    return {"status": "CANCELLED", "upload_id": upload_id}

@router.post("/{document_id}/cancel")
def cancel_ingestion(document_id: str, db: Session = Depends(get_db)):
    """
    Cancel ingestion of a document that is still processing. The pipeline stops at its next
    checkpoint (between slides, between questions, before each stage) and then deletes the
    document row, the stored deck, extracted media and R2 objects.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return {"status": "CANCELLED", "detail": "Document already removed."}
    if doc.processing_status == "COMPLETED":
        raise HTTPException(status_code=409, detail="Ingestion already completed; delete the document instead.")

    request_doc_cancel(document_id)
    # Also set the DB flag: if ingestion is running in a separate worker process (Cloud Run Job
    # mode), the in-memory CANCELLED_DOCS set above is invisible to it -- the worker's cancel
    # poller picks this up instead. Harmless no-op for the in-process path.
    doc.cancel_requested = True
    db.commit()
    reg = INGESTION_STATUS_REGISTRY.get(document_id)
    if reg and reg.get("status") == "PROCESSING":
        reg["current_step"] = "Cancelling..."
        return {"status": "CANCELLING", "document_id": document_id}

    # Nothing is actively running for this id (e.g. server restarted mid-ingest): clean up now.
    purge_document(db, document_id)
    INGESTION_STATUS_REGISTRY[document_id] = {
        "document_id": document_id, "status": "CANCELLED", "progress_percentage": 0,
        "current_step": "Upload cancelled", "slides_processed": 0, "questions_extracted": 0, "error": None,
    }
    return {"status": "CANCELLED", "document_id": document_id}

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
        from backend.app.services.ingestion import progress as _progress
        _progress.update(INGESTION_STATUS_REGISTRY[document_id])   # fresh memory reading on every poll
        return INGESTION_STATUS_REGISTRY[document_id]

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # doc.progress_detail is the cross-process mirror worker.py writes every few seconds under
    # INGESTION_MODE=cloud_run_job (see worker.py's _sync_progress_to_db) -- a periodic snapshot
    # of the same live detail/activity-log/server-memory registry entry that pipeline.py writes
    # continuously, which this process can only read directly when ingestion runs in its own
    # memory (the INGESTION_STATUS_REGISTRY fast path above). Falls back to the coarse
    # PROCESSING/COMPLETED/FAILED-only view when no snapshot has landed yet (e.g. right after the
    # job was triggered, before its first sync tick).
    pd = doc.progress_detail or {}
    return {
        "document_id": doc.id,
        "status": doc.processing_status,
        "progress_percentage": pd.get(
            "progress_percentage", 100 if doc.processing_status == "COMPLETED" else 0
        ),
        "current_step": pd.get("current_step") or (
            "Completed" if doc.processing_status == "COMPLETED" else doc.processing_status
        ),
        "slides_processed": doc.slide_count,
        "questions_extracted": doc.question_count,
        "error": doc.processing_error or pd.get("error"),
        "detail": pd.get("detail"),
        "events": pd.get("events"),
        "memory_mb": pd.get("memory_mb"),
        "peak_memory_mb": pd.get("peak_memory_mb"),
        "memory_limit_mb": pd.get("memory_limit_mb"),
    }

@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    reg = INGESTION_STATUS_REGISTRY.get(document_id)
    if reg and reg.get("status") == "PROCESSING":
        request_doc_cancel(document_id)  # stop the running pipeline instead of orphaning it

    if os.path.exists(doc.storage_path):
        try:
            os.remove(doc.storage_path)
        except Exception:
            pass

    from backend.app.services.question_meta_service import remove_repeats_for_document
    remove_repeats_for_document(db, document_id)  # other questions stop listing this deck as a repeat
    db.delete(doc)
    db.commit()
    return {"message": "Document deleted successfully"}
