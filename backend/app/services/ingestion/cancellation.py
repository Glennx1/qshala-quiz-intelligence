"""Cooperative cancellation for uploads and ingestion.

A user hitting "Cancel upload" must stop *all* work tied to that upload, not just hide
the progress bar. Two pieces of shared state live here so the router, the pipeline and
the parsers can all see them without importing each other (avoids circular imports):

  * CANCELLED_DOCS    -- document ids whose ingestion should stop at the next checkpoint
  * CANCELLED_UPLOADS -- chunked-upload ids whose remaining chunks must be refused

`purge_document` removes everything a half-finished ingestion leaves behind: the DB row
(slides/questions cascade), the stored deck, extracted media on disk, and media in R2.
"""
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Set

from backend.app.config import settings

logger = logging.getLogger(__name__)

CANCELLED_DOCS: Set[str] = set()
CANCELLED_UPLOADS: Set[str] = set()
_MAX_TRACKED = 1000  # bounded so a long-lived process can't grow these forever

_UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class IngestionCancelled(Exception):
    """Raised inside the pipeline/parsers when the user cancelled this document."""


def valid_upload_id(upload_id: str) -> bool:
    # upload_id becomes a directory name under tmp_chunks/, so it must never contain
    # path separators or "..".
    return bool(_UPLOAD_ID_RE.match(upload_id or ""))


def _remember(bucket: Set[str], item: str) -> None:
    if len(bucket) >= _MAX_TRACKED:
        bucket.pop()
    bucket.add(item)


# A Cloud Run Job worker refreshes its job row every ~2 s while it runs. A PROCESSING job refreshed within this
# many seconds means a live worker owns the document, so a cancel/delete must not purge it from under the worker.
WORKER_ALIVE_WINDOW_S: float = float(os.getenv("WORKER_ALIVE_WINDOW_S", "90"))


def worker_is_alive(db, document_id: str) -> bool:
    """True when a Cloud Run Job worker owns this document: INGESTION_MODE is cloud_run_job and the document's
    ingestion job is PROCESSING with a row refreshed recently. In the other modes the pipeline runs inside this same
    process (cancel is handled through the in-memory flag) and nothing refreshes the job row, so it is always False."""
    if settings.INGESTION_MODE != "cloud_run_job":
        return False
    from datetime import datetime, timezone
    from backend.app.models.job import IngestionJob
    job = (db.query(IngestionJob)
           .filter(IngestionJob.document_id == document_id, IngestionJob.status == "PROCESSING")
           .order_by(IngestionJob.created_at.desc()).first())
    if job is None or job.updated_at is None:
        return False
    stamp = job.updated_at if job.updated_at.tzinfo else job.updated_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() < WORKER_ALIVE_WINDOW_S


def request_doc_cancel(document_id: str) -> None:
    _remember(CANCELLED_DOCS, document_id)


def doc_cancel_requested(document_id: str) -> bool:
    return document_id in CANCELLED_DOCS


def clear_doc_cancel(document_id: str) -> None:
    CANCELLED_DOCS.discard(document_id)


def raise_if_cancelled(document_id: str) -> None:
    if document_id in CANCELLED_DOCS:
        raise IngestionCancelled(document_id)


def request_upload_cancel(upload_id: str) -> None:
    _remember(CANCELLED_UPLOADS, upload_id)


def upload_cancel_requested(upload_id: str) -> bool:
    return upload_id in CANCELLED_UPLOADS


def remove_chunk_dir(upload_id: str) -> None:
    if not valid_upload_id(upload_id):
        return
    shutil.rmtree(settings.STORAGE_DIR / "tmp_chunks" / upload_id, ignore_errors=True)


def purge_document(db, document_id: str) -> None:
    """Delete a document and every artifact produced for it. Safe to call twice."""
    from backend.app.models.document import Document

    doc = db.query(Document).filter(Document.id == document_id).first()
    storage_path = doc.storage_path if doc else None
    if doc is not None:
        try:
            from backend.app.services.question_meta_service import remove_repeats_for_document
            remove_repeats_for_document(db, document_id)  # other questions stop listing this deck as a repeat
            db.delete(doc)  # slides + questions cascade
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(f"[CANCEL] failed to delete DB row for {document_id}")

    if storage_path and os.path.exists(storage_path):
        try:
            os.remove(storage_path)
        except Exception as e:
            logger.warning(f"[CANCEL] could not remove stored deck {storage_path}: {e}")

    media_dirs = [
        settings.SLIDES_DIR / document_id,
        Path(__file__).resolve().parents[4] / "frontend" / "public" / "static" / "slides" / document_id,
    ]
    for d in media_dirs:
        shutil.rmtree(d, ignore_errors=True)

    try:
        from backend.app.services.storage.r2_storage import get_media_storage
        r2 = get_media_storage()
        if r2 is not None:
            r2.delete_prefix(f"slides/{document_id}/")
            if storage_path:
                # The deck itself, staged in R2 for the worker under a deterministic key (documents.py).
                r2.delete_object(f"raw-uploads/{document_id}{os.path.splitext(storage_path)[1]}")
    except Exception as e:
        logger.warning(f"[CANCEL] R2 cleanup failed for {document_id}: {e}")

    logger.info(f"[CANCEL] purged document {document_id}")
