"""Serial upload queue for deck ingestion.

Goal: let a user drop several decks and have them processed one at a time, over time, without
breaking the site. On a 512 MB host, processing decks in parallel is what causes OOM crashes, so the
whole point here is that exactly ONE deck ingests at a time.

How it works
------------
- Upload endpoints call `enqueue_upload()` instead of running the pipeline inline. That inserts an
  `IngestionJob` (source_type=MANUAL_UPLOAD, status=PENDING) and marks the Document `QUEUED`. The
  HTTP request returns immediately.
- A single background worker (`run_worker_loop`, started once at app startup) polls for the oldest
  PENDING job and runs the modern `IngestionPipeline` on it — but only when no MANUAL_UPLOAD job is
  already PROCESSING, so concurrency is capped at 1 across the whole app even if several worker
  loops exist.
- Each job gets its own short-lived DB sessions; the worker never holds a transaction across the
  pipeline run (the pipeline manages its own session).
- A job left PROCESSING by a crash/restart is reconciled on startup: marked FAILED with a clear
  message (never silently re-run, which would duplicate slides). A deliberate retry purges the
  deck's partial artifacts first (see `purge_artifacts`) and re-queues.

This path drives the current `IngestionPipeline.run()`, not the older serverless JobQueueService.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.models.document import Document, Slide
from backend.app.models.job import IngestionJob
from backend.app.models.question import Question

logger = logging.getLogger(__name__)

SOURCE = "MANUAL_UPLOAD"
_worker_task: "asyncio.Task | None" = None


def _now():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------- enqueue / status

def enqueue_upload(db: Session, *, document_id: str, filename: str) -> IngestionJob:
    """Create a PENDING ingestion job for an uploaded deck and mark the document QUEUED."""
    job = IngestionJob(source_type=SOURCE, filename=filename, document_id=document_id,
                       status="PENDING", current_step="QUEUED",
                       max_retries=settings.UPLOAD_QUEUE_MAX_RETRIES)
    db.add(job)
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is not None:
        doc.processing_status = "QUEUED"
    db.commit()
    db.refresh(job)
    logger.info("[QUEUE] enqueued %s (doc=%s), position=%d", job.id, document_id, queue_position(db, job))
    return job


def queue_position(db: Session, job: IngestionJob) -> int:
    """How many PENDING jobs are ahead of this one (0 = next up)."""
    return (db.query(IngestionJob)
            .filter(IngestionJob.source_type == SOURCE, IngestionJob.status == "PENDING",
                    IngestionJob.created_at < job.created_at)
            .count())


# --------------------------------------------------------------------- artifact purge (for safe retry/resume)

def purge_artifacts(db: Session, document_id: str) -> None:
    """Delete the slides/questions/tags produced for a document WITHOUT deleting the Document row or
    the uploaded file, so the pipeline can re-run cleanly. Children are deleted explicitly (not via
    DB cascade) so it works the same on Postgres and on SQLite with foreign keys off."""
    q_ids = [r[0] for r in db.query(Question.id).filter(Question.document_id == document_id).all()]
    if q_ids:
        # Best-effort import of every per-question child table; skip any that aren't present.
        children = []
        try:
            from backend.app.models.qshala_tag import QshalaTag, QshalaTagChange
            children += [QshalaTagChange, QshalaTag]
        except Exception:
            pass
        try:
            from backend.app.models.question_meta import (
                QuestionTopicPath, QuestionRepeat, QuestionEditHistory)
            children += [QuestionTopicPath, QuestionRepeat, QuestionEditHistory]
        except Exception:
            pass
        try:
            from backend.app.models.qshala_tag import QshalaQuestionMetadata
            children += [QshalaQuestionMetadata]
        except Exception:
            pass
        for model in children:
            try:
                db.query(model).filter(model.question_id.in_(q_ids)).delete(synchronize_session=False)
            except Exception as e:
                logger.warning("[QUEUE] purge child %s failed: %s", getattr(model, "__name__", model), e)
        db.query(Question).filter(Question.document_id == document_id).delete(synchronize_session=False)
    db.query(Slide).filter(Slide.document_id == document_id).delete(synchronize_session=False)
    db.commit()


# --------------------------------------------------------------------- claim / run

def claim_next(db: Session) -> "IngestionJob | None":
    """Claim the oldest PENDING upload job, but only if none is already PROCESSING (serial cap=1)."""
    busy = (db.query(IngestionJob)
            .filter(IngestionJob.source_type == SOURCE, IngestionJob.status == "PROCESSING")
            .count())
    if busy:
        return None
    job = (db.query(IngestionJob)
           .filter(IngestionJob.source_type == SOURCE, IngestionJob.status == "PENDING")
           .order_by(IngestionJob.created_at)
           .first())
    if job is None:
        return None
    job.status = "PROCESSING"
    job.current_step = "INGESTING"
    job.updated_at = _now()
    db.commit()
    return job


async def _run_job(job_id: str, document_id: str) -> None:
    """Run the modern pipeline for one job and record the outcome. Own sessions only."""
    from backend.app.services.ingestion.pipeline import IngestionPipeline
    ok, err = True, None
    try:
        await IngestionPipeline().run(document_id)            # manages its own DB session
    except Exception as e:                                    # pragma: no cover - defensive
        ok, err = False, str(e)[:500]
        logger.exception("[QUEUE] pipeline crashed for doc=%s", document_id)

    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        doc = db.query(Document).filter(Document.id == document_id).first()
        doc_ok = bool(doc) and doc.processing_status == "COMPLETED"
        if job:
            if ok and doc_ok:
                job.status, job.current_step, job.completed_at = "COMPLETED", "DONE", _now()
            else:
                job.status = "FAILED"
                job.error_message = err or (doc.processing_error if doc else None) or "ingestion did not complete"
            job.updated_at = _now()
        db.commit()
    finally:
        db.close()


async def process_one() -> bool:
    """Claim and run a single queued deck if one is available. Returns True if it processed one.
    Exposed for tests and for a cron/HTTP trigger; the loop below just calls it on a timer."""
    db = SessionLocal()
    try:
        job = claim_next(db)
        if job is None:
            return False
        job_id, document_id = job.id, job.document_id
    finally:
        db.close()
    await _run_job(job_id, document_id)
    return True


async def run_worker_loop() -> None:
    poll = max(1, int(settings.UPLOAD_QUEUE_POLL_SECONDS))
    logger.info("[QUEUE] upload worker started (poll=%ss, serial)", poll)
    while True:
        try:
            did = await process_one()
        except asyncio.CancelledError:
            logger.info("[QUEUE] upload worker stopping")
            raise
        except Exception as e:                                # never let the loop die
            logger.exception("[QUEUE] worker tick error: %s", e)
            did = False
        await asyncio.sleep(0 if did else poll)               # drain fast, idle slow


def reconcile_on_startup(db: Session) -> None:
    """A job left PROCESSING means the process died mid-run. Don't silently re-run (would duplicate
    slides); mark it FAILED with a clear message so the user can retry it deliberately."""
    stuck = (db.query(IngestionJob)
             .filter(IngestionJob.source_type == SOURCE, IngestionJob.status == "PROCESSING")
             .all())
    for job in stuck:
        job.status = "FAILED"
        job.error_message = ("Server restarted mid-ingestion (often the deck is too large for memory). "
                             "Retry it to re-process from a clean slate.")
        job.updated_at = _now()
        doc = db.query(Document).filter(Document.id == job.document_id).first()
        if doc is not None and doc.processing_status not in ("COMPLETED",):
            doc.processing_status = "FAILED"
            doc.processing_error = job.error_message
    if stuck:
        db.commit()
        logger.warning("[QUEUE] reconciled %d interrupted upload job(s) as FAILED", len(stuck))


def start_worker(loop=None) -> None:
    """Start the single worker task (idempotent)."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_task = asyncio.ensure_future(run_worker_loop())


def requeue_job(db: Session, job: IngestionJob) -> None:
    """Deliberate retry: purge partial artifacts, then set the job back to PENDING and doc to QUEUED."""
    if job.document_id:
        purge_artifacts(db, job.document_id)
        doc = db.query(Document).filter(Document.id == job.document_id).first()
        if doc is not None:
            doc.processing_status = "QUEUED"
            doc.processing_error = None
    job.status = "PENDING"
    job.current_step = "QUEUED"
    job.error_message = None
    job.retry_count = (job.retry_count or 0) + 1
    job.updated_at = _now()
    db.commit()
