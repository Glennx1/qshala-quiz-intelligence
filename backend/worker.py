"""Standalone ingestion worker (QShala priority plan: ingestion split out of the API monolith).

Runs ONE document's ingestion pipeline to completion, then exits. Meant to run as a Cloud Run
Job execution -- each execution processes exactly one deck, triggered by job_trigger.py from the
API service, which passes which document to process as the DOCUMENT_ID env var (a per-execution
container override, not a static env var on the Job resource itself).

Usage:
    DOCUMENT_ID=<uuid> python -m backend.worker          # how Cloud Run Jobs invokes it
    python -m backend.worker <uuid>                       # CLI arg, for local testing

This does NOT change how the API service processes uploads by default -- INGESTION_MODE stays
"in_process" unless explicitly set to "cloud_run_job" (see config.py and job_trigger.py). This
file is simply unreachable/unused in the default configuration.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Same sys.path bootstrap as main.py, so `backend.app.*` imports resolve when this file is run
# directly (python -m backend.worker) rather than imported from inside the FastAPI app.
import types
_current_file = Path(__file__).resolve()
_backend_dir = _current_file.parent
_project_root = _backend_dir.parent

if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

if "backend" not in sys.modules:
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(_backend_dir)]
    sys.modules["backend"] = backend_pkg

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("qshala.worker")

CANCEL_POLL_INTERVAL_S = 5.0


async def _poll_cancel(document_id: str, stop_event: asyncio.Event) -> None:
    """Mirrors Document.cancel_requested (set cross-process by the cancel API endpoint) into the
    in-memory CANCELLED_DOCS set that the pipeline's raise_if_cancelled() checks throughout --
    the existing cancellation mechanism, unmodified, just fed from the DB instead of only from
    an in-process API call. Stops once the pipeline finishes (stop_event) or cancellation fires.
    """
    from backend.app.database import SessionLocal
    from backend.app.models.document import Document
    from backend.app.services.ingestion.cancellation import request_doc_cancel

    while not stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                doc = db.query(Document).filter(Document.id == document_id).first()
                if doc is not None and doc.cancel_requested:
                    logger.info("[WORKER] cancel_requested detected for doc_id=%s", document_id)
                    request_doc_cancel(document_id)
                    return
            finally:
                db.close()
        except Exception as e:
            logger.warning("[WORKER] cancel poll failed (continuing): %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CANCEL_POLL_INTERVAL_S)
        except asyncio.TimeoutError:
            pass


PROGRESS_SYNC_INTERVAL_S = 2.0


def _sync_progress_once(document_id: str) -> None:
    """Copies the pipeline's live in-process progress snapshot (current step, % done, the
    activity log, this container's memory use) out to Document.progress_detail, so the API
    process -- which can't see this worker container's own memory any more than it can see the
    worker's filesystem (see the R2 raw-upload fix) -- has something to hand back from /status
    besides the coarse PROCESSING/COMPLETED/FAILED column. The upload page already renders all
    of this (detail, activity log, "server memory X of 2048 MB"); it just needs the worker to
    actually publish it somewhere cross-process-visible instead of leaving it to die with the
    container when the execution exits.
    """
    from backend.app.services.ingestion.pipeline import INGESTION_STATUS_REGISTRY

    snapshot = INGESTION_STATUS_REGISTRY.get(document_id)
    if not snapshot:
        return
    # Shallow-copy the dict AND its events list: pipeline.py keeps appending to that same list
    # object on the main event loop while this runs on a worker thread (asyncio.to_thread), and
    # json-serializing a list another thread is mutating mid-append is a real (if rare) race.
    # The individual event dicts are never mutated after creation, so copying just these two
    # containers is enough to fully isolate this snapshot from further pipeline writes.
    safe_snapshot = dict(snapshot)
    if isinstance(safe_snapshot.get("events"), list):
        safe_snapshot["events"] = list(safe_snapshot["events"])

    from backend.app.database import SessionLocal
    from backend.app.models.document import Document

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is not None:
            doc.progress_detail = safe_snapshot
            db.commit()
    except Exception as e:
        logger.warning("[WORKER] progress sync failed (continuing): %s", e)
    finally:
        db.close()


async def _sync_progress_to_db(document_id: str, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(_sync_progress_once, document_id)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=PROGRESS_SYNC_INTERVAL_S)
        except asyncio.TimeoutError:
            pass


def _fetch_raw_deck(document_id: str) -> None:
    """Downloads the raw deck from R2 to doc.storage_path if it isn't already on this
    container's local disk. The API service staged it there (see documents.py's
    _schedule_ingestion, cloud_run_job branch) under a deterministic key precisely because this
    worker runs in its own container with an empty filesystem -- doc.storage_path is only a
    meaningful local path again once this runs. A no-op for every other ingestion mode, and for
    local/manual testing where the file is already sitting on disk.
    """
    from backend.app.database import SessionLocal
    from backend.app.models.document import Document
    from backend.app.services.storage.r2_storage import get_r2_service

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is None:
            raise RuntimeError(f"Document {document_id} not found")
        if doc.storage_path and os.path.exists(doc.storage_path):
            return
        r2 = get_r2_service()
        if not r2.is_configured:
            raise RuntimeError(
                "R2 is not configured, but the raw deck isn't on local disk -- nothing to process"
            )
        raw_key = f"raw-uploads/{doc.id}{os.path.splitext(doc.storage_path)[1]}"
        dest = Path(doc.storage_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        r2.download_to_file(raw_key, dest)
        logger.info("[WORKER] fetched raw deck from R2: doc_id=%s key=%s", document_id, raw_key)
    finally:
        db.close()


async def _run(document_id: str) -> None:
    from backend.app.services.ingestion.pipeline import IngestionPipeline

    stop_event = asyncio.Event()
    poller = asyncio.create_task(_poll_cancel(document_id, stop_event))
    syncer = asyncio.create_task(_sync_progress_to_db(document_id, stop_event))
    try:
        logger.info("[WORKER] starting ingestion for doc_id=%s", document_id)
        await asyncio.to_thread(_fetch_raw_deck, document_id)
        await IngestionPipeline().run(document_id)
        logger.info("[WORKER] finished ingestion for doc_id=%s", document_id)
    finally:
        stop_event.set()
        poller.cancel()
        syncer.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass
        try:
            await syncer
        except asyncio.CancelledError:
            pass
        # One last sync so the final "Finishing up" / completion detail and activity log entries
        # the pipeline wrote in its last moments aren't lost to the PROGRESS_SYNC_INTERVAL_S gap.
        await asyncio.to_thread(_sync_progress_once, document_id)


def main() -> int:
    document_id = os.environ.get("DOCUMENT_ID") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if not document_id:
        logger.error("[WORKER] no DOCUMENT_ID env var or CLI arg given -- nothing to process")
        return 1
    try:
        asyncio.run(_run(document_id))
        return 0
    except Exception as e:
        # The pipeline itself already marks the Document row FAILED with processing_error on
        # exception (see pipeline.py's top-level except block) -- this is a last-resort net so a
        # truly unexpected crash (e.g. a DB connection the pipeline couldn't reach at all) still
        # shows up as a failed Cloud Run Job execution instead of silently exiting 0.
        logger.exception("[WORKER] unhandled error processing doc_id=%s: %s", document_id, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
