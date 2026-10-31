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


async def _run(document_id: str) -> None:
    from backend.app.services.ingestion.pipeline import IngestionPipeline

    stop_event = asyncio.Event()
    poller = asyncio.create_task(_poll_cancel(document_id, stop_event))
    try:
        logger.info("[WORKER] starting ingestion for doc_id=%s", document_id)
        await IngestionPipeline().run(document_id)
        logger.info("[WORKER] finished ingestion for doc_id=%s", document_id)
    finally:
        stop_event.set()
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass


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
