"""One-off upgrade of questions that were stored before the v6 tag system.

Step 1 (fast, no AI, safe to run again): for every finished deck
  - read the deck details from the file name
  - number the questions and set round, format, star, answer type, language from the stored slides
  - copy the deck details onto each question
  - turn the old `provenance_decks` list into Repeated entries
  - carry an old topic over to the v6 taxonomy when the subtopic name still exists

Step 2 (Gemini, optional, background, cancellable): tag whatever is still without v6 topic paths.
Anything a person edited by hand is never overwritten.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.database import SessionLocal
from backend.app.models.document import Document, Slide
from backend.app.models.qshala_tag import QshalaTag
from backend.app.models.question import Question
from backend.app.models.question_meta import DeckMetadata, QuestionTopicPath
from backend.app.services import question_meta_service as svc
from backend.app.services.deduplication.deduplicator import Deduplicator
from backend.app.services.ingestion.deck_metadata import annotate_questions
from backend.app.services.tagging import topic_paths

logger = logging.getLogger(__name__)

RETAG_CONCURRENCY = 6

STATUS: Dict[str, Any] = {
    "state": "idle",          # idle | structure | tagging | done | cancelled | error
    "decks": 0, "questions": 0, "repeats": 0, "migrated_topics": 0,
    "to_tag": 0, "tagged": 0, "failed": 0, "message": "",
}
_cancel = {"flag": False}


def request_cancel() -> None:
    _cancel["flag"] = True


def _reset() -> None:
    _cancel["flag"] = False
    STATUS.update(state="idle", decks=0, questions=0, repeats=0, migrated_topics=0,
                  to_tag=0, tagged=0, failed=0, message="")


def _v6_lookup() -> Dict[str, tuple]:
    out: Dict[str, tuple] = {}
    for g in topic_paths.taxonomy_v6()["raw"]["level1"]:
        for i in g["level2"]:
            out[i["name"].lower()] = (g["name"], i["name"])
    return out


def _question_dict(q: Question, slide_no: Optional[int]) -> Dict[str, Any]:
    return {
        "question_text": q.question_text, "answer": q.answer, "round_number": q.round_number,
        "slide_number": slide_no, "question_images": q.question_images or [],
        "answer_images": q.answer_images or [], "question_audio": q.question_audio or [],
        "answer_audio": q.answer_audio or [], "question_videos": getattr(q, "question_videos", None) or [],
        "answer_videos": getattr(q, "answer_videos", None) or [],
    }


def run_structure(db: Session) -> Dict[str, int]:
    """Step 1. Returns counters. Idempotent."""
    lookup = _v6_lookup()
    docs = db.query(Document).filter(Document.processing_status == "COMPLETED").all()
    doc_ids = {d.id for d in docs}
    for doc in docs:
        deck_row = svc.upsert_deck_metadata(db, doc, reparse=True)
        slides = db.query(Slide).filter(Slide.document_id == doc.id).order_by(Slide.slide_number).all()
        slide_no = {s.id: s.slide_number for s in slides}
        slide_dicts = [{"slide_number": s.slide_number, "extracted_text": s.extracted_text or "",
                        "slide_type": s.slide_type, "title": s.title,
                        "metadata_json": s.metadata_json or {}} for s in slides]
        qs = db.query(Question).filter(Question.document_id == doc.id).all()
        qs.sort(key=lambda q: (slide_no.get(q.slide_id) or 10 ** 6, q.created_at or 0))
        dicts = [_question_dict(q, slide_no.get(q.slide_id)) for q in qs]
        # annotate strips a star marker from the text, so the same question hashes alike in every deck
        annotate_questions(dicts, slide_dicts, svc.deck_row_to_info(deck_row))
        for q, d in zip(qs, dicts):
            if d["question_text"] != q.question_text:
                q.question_text = d["question_text"]
                q.content_hash = Deduplicator.compute_hash(q.question_text, q.answer or "")
            q.round_number = (d.get("_meta") or {}).get("round_number")
            svc.ensure_question_metadata(db, q, d.get("_meta"), deck_row, doc)
            STATUS["questions"] += 1
            # Repeated entries from the old provenance list
            for p in (q.provenance_decks or []):
                other = p.get("document_id") if isinstance(p, dict) else None
                if other and other != q.document_id and other in doc_ids:
                    if svc.add_repeat(db, q, other, None, None, actor="backfill"):
                        STATUS["repeats"] += 1
            # Old v5.1 topic -> v6 when the subtopic still exists
            if not db.query(QuestionTopicPath).filter(QuestionTopicPath.question_id == q.id).first():
                old = (db.query(QshalaTag).filter(QshalaTag.question_id == q.id)
                       .order_by(QshalaTag.created_at.desc()).first()) if hasattr(QshalaTag, "created_at") else \
                    db.query(QshalaTag).filter(QshalaTag.question_id == q.id).first()
                hit = lookup.get((getattr(old, "subtopic_l2", None) or "").lower()) if old else None
                if hit:
                    kws = [t for t in (q.tags or []) if isinstance(t, str) and "storyteller" not in t.lower()][:6]
                    topic_paths.replace_paths(
                        db, q.id, [{"l1": hit[0], "l2": hit[1], "keywords": kws}],
                        source="LLM", actor="backfill", record_history=False, question=q)
                    STATUS["migrated_topics"] += 1
        STATUS["decks"] += 1
        db.commit()
    return {k: STATUS[k] for k in ("decks", "questions", "repeats", "migrated_topics")}


def untagged_question_ids(db: Session) -> List[str]:
    tagged = {r[0] for r in db.query(QuestionTopicPath.question_id).distinct().all()}
    return [r[0] for r in db.query(Question.id).all() if r[0] not in tagged]


async def run_tagging(ids: List[str]) -> None:
    from backend.app.services.tagging.qshala_tagger import QshalaTagger
    tagger = QshalaTagger()
    sem = asyncio.Semaphore(RETAG_CONCURRENCY)
    STATUS.update(state="tagging", to_tag=len(ids), tagged=0, failed=0)

    async def one(qid: str) -> None:
        if _cancel["flag"]:
            return
        async with sem:
            if _cancel["flag"]:
                return
            db = SessionLocal()
            try:
                q = db.query(Question).filter(Question.id == qid).first()
                if not q:
                    return
                deck = db.query(DeckMetadata).filter(DeckMetadata.document_id == q.document_id).first()
                tag = await tagger.tag(
                    db=db, question_id=q.id, question_text=q.question_text, answer=q.answer, actor="backfill",
                    commit=False, visual_clues=q.visual_clues or "", deck_year=(deck.deck_year if deck else None),
                    question=q)
                svc.apply_tag_to_meta(db, q.id, tag)
                db.commit()
                STATUS["tagged"] += 1
            except Exception as e:  # one bad question never stops the run
                db.rollback()
                STATUS["failed"] += 1
                logger.warning("backfill tag failed for %s: %s", qid, e)
            finally:
                db.close()

    await asyncio.gather(*(one(i) for i in ids))


async def run_all(retag: bool = True) -> None:
    _reset()
    STATUS["state"] = "structure"
    try:
        db = SessionLocal()
        try:
            run_structure(db)
            ids = untagged_question_ids(db) if retag else []
        finally:
            db.close()
        if ids and not _cancel["flag"]:
            await run_tagging(ids)
        STATUS["state"] = "cancelled" if _cancel["flag"] else "done"
        STATUS["message"] = (
            f"{STATUS['decks']} decks, {STATUS['questions']} questions, {STATUS['repeats']} repeated entries, "
            f"{STATUS['migrated_topics']} topics carried over, {STATUS['tagged']} re-tagged, {STATUS['failed']} failed.")
    except Exception as e:
        logger.exception("backfill failed")
        STATUS.update(state="error", message=str(e))
