"""Edit Tags API: everything the question's tag screen reads and writes.

  GET    /questions/{id}/detail            all tags, deck details, repeated list, images
  PUT    /questions/{id}/meta              edit deck/traits/geography/year/audience fields
  PUT    /questions/{id}/topic-paths       replace the Theme > Subtopic > keywords paths
  PUT    /questions/{id}/hashtags          replace the hashtags
  GET    /questions/{id}/repeats           the Repeated tag
  PATCH  /questions/{id}/repeats/{rid}     fix a Repeated entry
  DELETE /questions/{id}/repeats/{rid}     remove a Repeated entry
  GET    /questions/{id}/history           edit history
  POST   /questions/{id}/retag             run the tagger again
  GET    /taxonomy                         themes, subtopics, custom additions, option lists
  GET    /documents/{id}/deck-meta         deck details
  PUT    /documents/{id}/deck-meta         edit deck details (flows down to questions not hand-edited)
"""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.document import Document
from backend.app.models.qshala_tag import QshalaQuestionMetadata
from backend.app.models.question import Question
from backend.app.models.question_meta import (
    DeckMetadata, QuestionEditHistory, QuestionRepeat, QuestionTopicPath,
)
from backend.app.services import backfill_v6, question_meta_service as svc
from backend.app.services.ingestion.deck_metadata import QUESTION_FORMATS
from backend.app.services.tagging import topic_paths

router = APIRouter(tags=["Question Tags (v6)"])

PRIMARY_AUDIENCES = ["College", "School", "Corporate", "Open", "Family"]


class MetaUpdate(BaseModel):
    changes: Dict[str, Any]
    actor: Optional[str] = None


class PathIn(BaseModel):
    l1: Optional[str] = None
    l2: Optional[str] = None
    keywords: List[str] = []


class PathsUpdate(BaseModel):
    paths: List[PathIn]
    actor: Optional[str] = None


class HashtagsUpdate(BaseModel):
    hashtags: List[str]
    actor: Optional[str] = None


class RepeatPatch(BaseModel):
    quiz_name: Optional[str] = None
    round_number: Optional[int] = None
    question_in_round: Optional[int] = None
    question_number: Optional[int] = None
    actor: Optional[str] = None


class DeckUpdate(BaseModel):
    changes: Dict[str, Any]
    actor: Optional[str] = None


def _question(db: Session, qid: str) -> Question:
    q = db.query(Question).filter(Question.id == qid).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    return q


def split_tags(q: Question, paths: List[Dict[str, Any]]) -> List[str]:
    """Hashtags = the question's tags that are not keywords of one of its topic paths."""
    kw = {k.lower() for p in paths for k in (p.get("keywords") or [])}
    return [t for t in (q.tags or []) if isinstance(t, str) and t.lower() not in kw]


def _tag_error(db: Session, qid: str) -> Optional[str]:
    row = (db.query(QuestionEditHistory)
           .filter(QuestionEditHistory.question_id == qid, QuestionEditHistory.kind == "TAG_ERROR")
           .order_by(QuestionEditHistory.changed_at.desc()).first())
    return row.new_value if row else None


def build_detail(db: Session, q: Question) -> Dict[str, Any]:
    doc = db.query(Document).filter(Document.id == q.document_id).first()
    meta = db.query(QshalaQuestionMetadata).filter(QshalaQuestionMetadata.question_id == q.id).first()
    deck = db.query(DeckMetadata).filter(DeckMetadata.document_id == q.document_id).first()
    paths = topic_paths.get_paths(db, q.id)
    return {
        "id": q.id,
        "question_text": q.question_text,
        "answer": q.answer,
        "difficulty": q.difficulty,
        "difficulty_score": q.difficulty_score,
        "document": {"id": q.document_id, "title": doc.title if doc else None,
                     "filename": doc.filename if doc else None},
        "source_slide_range": q.source_slide_range,
        "question_images": q.question_images or [],
        "answer_images": q.answer_images or [],
        "visual_clues": q.visual_clues,
        "meta": svc.meta_to_dict(meta),
        "deck": svc.deck_to_dict(deck, doc),
        "topic_paths": paths,
        "hashtags": split_tags(q, paths),
        "repeated": svc.get_repeats(db, q.id),
        "topic": q.topic,
        "subtopic": q.subtopic,
        "tag_error": _tag_error(db, q.id) if not paths else None,
    }


@router.get("/questions/{question_id}/detail")
def get_detail(question_id: str, db: Session = Depends(get_db)):
    return build_detail(db, _question(db, question_id))


@router.put("/questions/{question_id}/meta")
def put_meta(question_id: str, body: MetaUpdate, db: Session = Depends(get_db)):
    q = _question(db, question_id)
    try:
        svc.update_question_metadata(db, question_id, body.changes, actor=body.actor or "user")
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    return build_detail(db, q)


@router.put("/questions/{question_id}/topic-paths")
def put_topic_paths(question_id: str, body: PathsUpdate, db: Session = Depends(get_db)):
    q = _question(db, question_id)
    paths = [p.model_dump() for p in body.paths]
    if not topic_paths.normalise_paths(paths) and paths:
        raise HTTPException(status_code=422, detail="Each path needs a theme or a subtopic")
    topic_paths.replace_paths(db, question_id, paths, source="HUMAN", actor=body.actor or "user", question=q)
    db.commit()
    return build_detail(db, q)


@router.put("/questions/{question_id}/hashtags")
def put_hashtags(question_id: str, body: HashtagsUpdate, db: Session = Depends(get_db)):
    q = _question(db, question_id)
    paths = topic_paths.get_paths(db, question_id)
    kws = [k for p in paths for k in (p.get("keywords") or [])]
    old_tags = split_tags(q, paths)
    new_tags = topic_paths.clean_keywords(body.hashtags)
    merged: List[str] = []
    seen = set()
    for t in kws + new_tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            merged.append(t)
    q.tags = merged
    svc.log_edit(db, question_id, "hashtags", old_tags, new_tags, kind="EDIT", actor=body.actor or "user")
    db.commit()
    return build_detail(db, q)


@router.get("/questions/{question_id}/repeats")
def list_repeats(question_id: str, db: Session = Depends(get_db)):
    _question(db, question_id)
    return svc.get_repeats(db, question_id)


@router.patch("/questions/{question_id}/repeats/{repeat_id}")
def patch_repeat(question_id: str, repeat_id: str, body: RepeatPatch, db: Session = Depends(get_db)):
    r = db.query(QuestionRepeat).filter(QuestionRepeat.id == repeat_id, QuestionRepeat.question_id == question_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Repeated entry not found")
    before = svc.repeat_label(r)
    for f in ("quiz_name", "round_number", "question_in_round", "question_number"):
        v = getattr(body, f)
        if v is not None:
            setattr(r, f, v)
    svc.log_edit(db, question_id, "repeated", before, svc.repeat_label(r), kind="EDIT", actor=body.actor or "user")
    db.commit()
    return svc.repeat_to_dict(r)


@router.delete("/questions/{question_id}/repeats/{repeat_id}")
def delete_repeat(question_id: str, repeat_id: str, actor: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = _question(db, question_id)
    r = db.query(QuestionRepeat).filter(QuestionRepeat.id == repeat_id, QuestionRepeat.question_id == question_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Repeated entry not found")
    svc.log_edit(db, question_id, "repeated", svc.repeat_label(r), None, kind="EDIT", actor=actor or "user")
    db.delete(r)
    db.flush()
    remaining = db.query(QuestionRepeat).filter(QuestionRepeat.question_id == question_id).count()
    q.occurrence_count = 1 + remaining
    db.commit()
    return {"status": "deleted", "repeated": svc.get_repeats(db, question_id)}


@router.get("/questions/{question_id}/history")
def get_history(question_id: str, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    _question(db, question_id)
    rows = (db.query(QuestionEditHistory).filter(QuestionEditHistory.question_id == question_id)
            .order_by(QuestionEditHistory.changed_at.desc()).limit(limit).all())
    return [{
        "id": r.id, "field": r.field, "old_value": r.old_value, "new_value": r.new_value, "kind": r.kind,
        "actor": r.actor, "changed_at": r.changed_at.isoformat() if r.changed_at else None,
    } for r in rows]


@router.post("/questions/{question_id}/retag")
async def retag(question_id: str, force: bool = Query(False), db: Session = Depends(get_db)):
    """Run the tagger again. Topic paths a person set are kept unless force=true."""
    q = _question(db, question_id)
    from backend.app.services.tagging.qshala_tagger import QshalaTagger
    if force:
        db.query(QuestionTopicPath).filter(QuestionTopicPath.question_id == question_id).delete(synchronize_session=False)
        db.flush()
    deck = db.query(DeckMetadata).filter(DeckMetadata.document_id == q.document_id).first()
    try:
        tag = await QshalaTagger().tag(
            db=db, question_id=q.id, question_text=q.question_text, answer=q.answer, actor="retag",
            commit=False, visual_clues=q.visual_clues or "", deck_year=(deck.deck_year if deck else None),
            question=q)
    except Exception as e:
        db.rollback()
        from backend.app.services.tagging.qshala_tagger import safe_error
        raise HTTPException(status_code=502, detail=f"Tagging failed: {safe_error(e)}")
    svc.apply_tag_to_meta(db, q.id, tag)
    svc.log_edit(db, q.id, "retag", None, "re-tagged by AI", kind="RETAG", actor="retag")
    db.commit()
    return build_detail(db, q)


@router.get("/taxonomy")
def get_taxonomy(db: Session = Depends(get_db)):
    tax = topic_paths.taxonomy_v6()
    custom_rows = (db.query(QuestionTopicPath.l1, QuestionTopicPath.l2, func.count(QuestionTopicPath.id))
                   .filter(QuestionTopicPath.is_custom.is_(True))
                   .group_by(QuestionTopicPath.l1, QuestionTopicPath.l2).all())
    return {
        "version": tax["raw"]["version"],
        "themes": [{
            "name": g["name"], "code": g["code"],
            "subtopics": [{"name": i["name"], "code": i["code"], "description": i.get("description", "")}
                          for i in g["level2"]],
        } for g in tax["raw"]["level1"]],
        "custom": [{"l1": r[0], "l2": r[1], "count": r[2]} for r in custom_rows],
        "formats": [
            "QA",
            "CONNECT_4",
            "STEPPED_CLUE",
            "ARRANGE_ORDER",
            "BUZZER",
            "VISUAL_CLUE",
            "AUDIO_CLUE",
            "VIDEO_CLUE",
            "POTPOURRI",
            "IMAGE_REVEAL",
            "LIST_IT",
        ],
        "format_labels": getattr(svc, "FORMAT_LABELS", {}),
        "answer_types": svc.ANSWER_TYPES,
        "geographies": svc.GEOGRAPHIES,
        "audiences": PRIMARY_AUDIENCES,
    }


@router.get("/documents/{document_id}/deck-meta")
def get_deck_meta(document_id: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    row = svc.upsert_deck_metadata(db, doc)
    db.commit()
    return svc.deck_to_dict(row, doc)


@router.put("/documents/{document_id}/deck-meta")
def put_deck_meta(document_id: str, body: DeckUpdate, db: Session = Depends(get_db)):
    try:
        out = svc.update_deck_metadata(db, document_id, body.changes, actor=body.actor or "user")
    except LookupError:
        raise HTTPException(status_code=404, detail="Document not found")
    except (ValueError, TypeError) as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()
    return out


# ---- one-off upgrade of questions stored before v6 ------------------------------------------------
_backfill_task: Dict[str, Any] = {"task": None}


@router.post("/admin/backfill-v6")
async def start_backfill(retag: bool = Query(True)):
    """Fill deck details, numbering and Repeated entries for old questions, then re-tag in the background."""
    t = _backfill_task["task"]
    if t is not None and not t.done():
        raise HTTPException(status_code=409, detail="A backfill is already running")
    _backfill_task["task"] = asyncio.create_task(backfill_v6.run_all(retag=retag))
    return {"status": "started", "retag": retag}


@router.get("/admin/backfill-v6/status")
def backfill_status():
    return dict(backfill_v6.STATUS)


@router.post("/admin/backfill-v6/cancel")
def cancel_backfill():
    backfill_v6.request_cancel()
    return {"status": "cancel requested"}
