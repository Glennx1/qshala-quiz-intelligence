"""HTTP API for the QShala-domain tagger.

Endpoints:
  POST /qshala/tag/{question_id}          — run the tagger on one question. Returns inserted row.
  GET  /qshala/tag/{question_id}          — current confirmed tag + history for one question.
  POST /qshala/tag/{question_id}/human    — store human-authored tag; supersedes current one.
  POST /qshala/batch-tag                  — chunked batch tagging for a deck or question list.
  GET  /qshala/review-queue               — draft rows that need review, lowest confidence first.
  POST /qshala/review/bulk-accept         — bulk accept multiple draft tags.
  POST /qshala/review/{tag_id}/action     — review action (accept, change, skip) on single tag.
  GET  /qshala/deck/{doc_id}/tag-summary  — aggregated cost, tokens, and status for a deck.
  GET  /qshala/taxonomy                   — active v4 taxonomy hierarchy and descriptions.
  GET  /qshala/questions                  — search/filter questions by taxonomy and metadata.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, cast, String

from backend.app.database import SessionLocal
from backend.app.models.qshala_tag import QshalaTag, QshalaTagChange, QshalaQuestionMetadata
from backend.app.models.question import Question
from backend.app.services.tagging.qshala_tagger import QshalaTagger

router = APIRouter(prefix="/qshala", tags=["qshala-tagging"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class HumanTagIn(BaseModel):
    subtopic_l2: str
    secondary_l2: List[str] = Field(default_factory=list)
    keywords_l3: List[str] = Field(default_factory=list)
    entity_type: Optional[str] = None
    india_international: Optional[str] = None
    city_name: Optional[str] = None
    geo_region: Optional[str] = None
    shelf_life: Optional[str] = None
    sensitivity: Optional[str] = None
    fit: Optional[str] = "good"
    search_summary: Optional[str] = None
    fact_check_url: Optional[str] = None
    actor: str = "human"
    notes: Optional[str] = None


class BatchTagIn(BaseModel):
    document_id: Optional[str] = None
    question_ids: Optional[List[str]] = None
    chunk_size: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)
    throttle_seconds: float = Field(default=1.0, ge=0.0, le=10.0)
    actor: str = "system"


class BulkAcceptIn(BaseModel):
    tag_ids: List[str]
    actor: str = "reviewer"
    notes: Optional[str] = None


class ReviewActionIn(BaseModel):
    action: str  # "accept" | "change" | "skip"
    actor: str = "reviewer"
    new_subtopic_l2: Optional[str] = None
    notes: Optional[str] = None


class ClarifyIn(BaseModel):
    hint: str
    actor: str = "quizmaster"
    accept: bool = True          # True: confirm the re-tag as the quiz master's call


def _tag_to_dict(t: QshalaTag) -> Dict[str, Any]:
    return {
        "id": t.id,
        "question_id": t.question_id,
        "source": t.source,
        "status": t.status,
        "model_version": t.model_version,
        "taxonomy_version": t.taxonomy_version,
        "topic_l1": t.topic_l1,
        "subtopic_l2": t.subtopic_l2,
        "keywords_l3": t.keywords_l3 or [],
        "secondary_l2": t.secondary_l2 or [],
        "entity_type": t.entity_type,
        "city_name": t.city_name,
        "geo_region": t.geo_region,
        "india_international": t.india_international,
        "shelf_life": t.shelf_life,
        "sensitivity": t.sensitivity,
        "fit": t.fit,
        "search_summary": t.search_summary,
        "confidence": t.confidence,
        "verified_by": t.verified_by,
        "verified_at": t.verified_at.isoformat() if t.verified_at else None,
        "verification_notes": t.verification_notes,
        "fact_check_url": t.fact_check_url,
        "tokens_in": t.tokens_in,
        "tokens_out": t.tokens_out,
        "thinking_tokens": t.thinking_tokens,
        "latency_ms": t.latency_ms,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.post("/tag/{question_id}")
async def tag_question(question_id: str, actor: str = Query("system"), db: Session = Depends(get_db)):
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "question not found")
    tagger = QshalaTagger()
    try:
        row = await tagger.tag(
            db,
            question_id=q.id,
            question_text=q.question_text,
            answer=q.answer,
            actor=actor,
            commit=True,
        )
    except Exception as e:
        raise HTTPException(502, f"tagger failed: {e}")
    return _tag_to_dict(row)


@router.get("/tag/{question_id}")
def get_tag_history(question_id: str, db: Session = Depends(get_db)):
    current = QshalaTagger.current(db, question_id)
    history = (
        db.query(QshalaTag)
        .filter(QshalaTag.question_id == question_id)
        .order_by(QshalaTag.created_at.desc())
        .all()
    )
    changes = (
        db.query(QshalaTagChange)
        .filter(QshalaTagChange.question_id == question_id)
        .order_by(QshalaTagChange.changed_at.desc())
        .all()
    )
    return {
        "current": _tag_to_dict(current) if current else None,
        "history": [_tag_to_dict(t) for t in history],
        "changes": [
            {
                "id": c.id,
                "change_type": c.change_type,
                "actor": c.actor,
                "reason": c.reason,
                "from_tag_id": c.from_tag_id,
                "to_tag_id": c.to_tag_id,
                "changed_at": c.changed_at.isoformat() if c.changed_at else None,
            }
            for c in changes
        ],
    }


@router.post("/tag/{question_id}/human")
def human_tag(question_id: str, body: HumanTagIn, db: Session = Depends(get_db)):
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "question not found")
    tagger = QshalaTagger()
    payload = body.model_dump(exclude={"actor", "notes"})
    row = tagger.human_override(
        db,
        question_id=q.id,
        new_tags=payload,
        actor=body.actor,
        notes=body.notes,
        commit=True,
    )
    return _tag_to_dict(row)


@router.post("/batch-tag")
async def batch_tag(
    body: Optional[BatchTagIn] = None,
    limit: int = Query(100, le=500),
    force: bool = Query(False),
    actor: str = Query("system"),
    db: Session = Depends(get_db)
):
    """Chunked batch tagging for a presentation deck, question IDs, or all untagged questions.

    Guarantees:
    - Never overwrites HUMAN-confirmed rows.
    - Isolates failures per question.
    - Honors throttling between API calls.
    - Returns progress counters for incremental UI polling and batch scripts.
    """
    if body and (body.document_id or body.question_ids):
        query = db.query(Question)
        if body.document_id:
            query = query.filter(Question.document_id == body.document_id)
        elif body.question_ids:
            query = query.filter(Question.id.in_(body.question_ids))
        total_matching = query.count()
        questions = query.order_by(Question.id.asc()).offset(body.offset).limit(body.chunk_size).all()
        actor_name = body.actor
        throttle_seconds = body.throttle_seconds
        doc_id = body.document_id
        offset_val = body.offset
        chunk_val = body.chunk_size
    else:
        if force:
            query = db.query(Question)
        else:
            tagged = db.query(QshalaTag.question_id).distinct()
            query = db.query(Question).filter(~Question.id.in_(tagged))
        total_matching = query.count()
        questions = query.order_by(Question.id.asc()).limit(limit).all()
        actor_name = actor
        throttle_seconds = 0.0
        doc_id = None
        offset_val = 0
        chunk_val = limit

    tagger = QshalaTagger()
    results = []

    for q in questions:
        if not q.question_text or not q.answer:
            results.append({
                "question_id": q.id,
                "status": "SKIPPED_EMPTY_TEXT_OR_ANSWER"
            })
            continue

        # Never overwrite a human-confirmed tag!
        curr = QshalaTagger.current(db, q.id)
        if curr and curr.source == "HUMAN" and curr.status == "confirmed":
            results.append({
                "question_id": q.id,
                "status": "SKIPPED_HUMAN_CONFIRMED",
                "tag": _tag_to_dict(curr)
            })
            continue

        try:
            row = await tagger.tag(
                db,
                question_id=q.id,
                question_text=q.question_text,
                answer=q.answer,
                actor=actor_name,
                commit=True
            )
            results.append({
                "question_id": q.id,
                "status": "TAGGED",
                "tag": _tag_to_dict(row)
            })
        except Exception as exc:
            results.append({
                "question_id": q.id,
                "status": "FAILED",
                "error": str(exc)
            })

        if throttle_seconds > 0:
            await asyncio.sleep(throttle_seconds)

    out_tagged = sum(1 for r in results if r["status"] == "TAGGED")
    out_skipped = sum(1 for r in results if "SKIPPED" in r["status"])
    out_failed = sum(1 for r in results if r["status"] == "FAILED")
    errors = [{"question_id": r["question_id"], "error": r.get("error")} for r in results if r["status"] == "FAILED"]

    return {
        "document_id": doc_id,
        "offset": offset_val,
        "chunk_size": chunk_val,
        "total": total_matching,
        "total_questions": len(questions),
        "processed": len(results),
        "tagged": out_tagged,
        "skipped": out_skipped,
        "failed": out_failed,
        "remaining": max(0, total_matching - (offset_val + len(results))),
        "errors": errors,
        "results": results
    }


@router.get("/review-queue")
def review_queue(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    """Draft rows that need a human look, lowest confidence first."""
    rows = (
        db.query(QshalaTag, Question)
        .join(Question, QshalaTag.question_id == Question.id)
        .filter(QshalaTag.status == "draft")
        .order_by(QshalaTag.confidence.asc(), QshalaTag.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "tag": _tag_to_dict(t),
            "question": {
                "id": q.id,
                "question_text": q.question_text,
                "answer": q.answer,
                "document_id": q.document_id,
            }
        }
        for t, q in rows
    ]


@router.post("/review/bulk-accept")
def bulk_accept(body: BulkAcceptIn, db: Session = Depends(get_db)):
    """Bulk accept multiple draft tags as confirmed in a single transaction."""
    now = datetime.now(timezone.utc)
    accepted_count = 0
    for tag_id in body.tag_ids:
        tag = db.query(QshalaTag).filter(QshalaTag.id == tag_id).first()
        if not tag or tag.status != "draft":
            continue

        curr = db.query(QshalaTag).filter(
            QshalaTag.question_id == tag.question_id,
            QshalaTag.status == "confirmed"
        ).first()
        if curr:
            curr.status = "superseded"

        tag.status = "confirmed"
        tag.verified_by = body.actor
        tag.verified_at = now
        tag.verification_notes = body.notes or "Bulk accepted in review queue"

        change = QshalaTagChange(
            question_id=tag.question_id,
            from_tag_id=curr.id if curr else None,
            to_tag_id=tag.id,
            change_type="BULK_ACCEPT",
            actor=body.actor,
            reason=body.notes or "Bulk accepted"
        )
        db.add(change)
        accepted_count += 1

    db.commit()
    return {"status": "ok", "accepted": accepted_count}


@router.post("/review/{tag_id}/action")
def review_action(tag_id: str, body: ReviewActionIn, db: Session = Depends(get_db)):
    """Execute single review action on a tag: accept, change, or skip."""
    tag = db.query(QshalaTag).filter(QshalaTag.id == tag_id).first()
    if not tag:
        raise HTTPException(404, "Tag not found")

    now = datetime.now(timezone.utc)
    curr = db.query(QshalaTag).filter(
        QshalaTag.question_id == tag.question_id,
        QshalaTag.status == "confirmed"
    ).first()

    if body.action == "accept":
        if curr and curr.id != tag.id:
            curr.status = "superseded"
        tag.status = "confirmed"
        tag.verified_by = body.actor
        tag.verified_at = now
        tag.verification_notes = body.notes or "Accepted in review UI"
        db.add(QshalaTagChange(
            question_id=tag.question_id,
            from_tag_id=curr.id if curr else None,
            to_tag_id=tag.id,
            change_type="ACCEPT_DRAFT",
            actor=body.actor,
            reason=body.notes or "Accepted"
        ))
        db.commit()
        return {"status": "ok", "action": "accept", "tag": _tag_to_dict(tag)}

    elif body.action == "change":
        if not body.new_subtopic_l2:
            raise HTTPException(400, "new_subtopic_l2 required for change action")
        tagger = QshalaTagger()
        tax = tagger.taxonomy
        parent_l1 = tax["l2_to_l1"].get(body.new_subtopic_l2, tag.topic_l1)
        override_row = tagger.human_override(
            db,
            question_id=tag.question_id,
            new_tags={
                "topic_l1": parent_l1,
                "subtopic_l2": body.new_subtopic_l2,
                "secondary_l2": tag.secondary_l2 or [],
                "keywords_l3": tag.keywords_l3 or [],
                "entity_type": tag.entity_type,
                "india_international": tag.india_international,
                "shelf_life": tag.shelf_life,
                "sensitivity": tag.sensitivity,
                "fit": "good"
            },
            actor=body.actor,
            notes=body.notes or f"Changed from {tag.subtopic_l2} to {body.new_subtopic_l2}",
            commit=True
        )
        return {"status": "ok", "action": "change", "tag": _tag_to_dict(override_row)}

    elif body.action == "skip":
        return {"status": "ok", "action": "skip", "tag_id": tag_id}

    else:
        raise HTTPException(400, f"Unsupported action: {body.action}")


@router.post("/review/{question_id}/clarify")
async def clarify_question(question_id: str, body: ClarifyIn, db: Session = Depends(get_db)):
    """Re-tag one question using a quiz-master hint. The hint is authoritative in the prompt.
    If accept=True the result is stored HUMAN-confirmed (and becomes a future few-shot example)."""
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(404, "question not found")

    tagger = QshalaTagger()
    row = await tagger.tag(db, question_id=question_id, question_text=q.question_text or "",
                           answer=q.answer or "", actor=body.actor, commit=False,
                           visual_clues=getattr(q, "visual_clues", "") or "",
                           clarification=body.hint, question=q)

    if body.accept:
        new_tags = {"subtopic_l2": row.subtopic_l2, "keywords_l3": row.keywords_l3,
                    "secondary_l2": row.secondary_l2, "entity_type": row.entity_type,
                    "india_international": row.india_international, "geo_region": row.geo_region,
                    "shelf_life": row.shelf_life, "sensitivity": row.sensitivity, "fit": "good"}
        db.rollback()   # drop the uncommitted draft; human_override writes the authoritative row
        human = tagger.human_override(db, question_id=question_id, new_tags=new_tags,
                                      actor=body.actor, notes=f"clarified: {body.hint[:300]}")
        return {"status": "ok", "confirmed": True, "tag": _tag_to_dict(human)}

    db.commit()
    return {"status": "ok", "confirmed": False, "tag": _tag_to_dict(row)}


@router.get("/deck/{document_id}/tag-summary")
def deck_tag_summary(document_id: str, db: Session = Depends(get_db)):
    """Aggregate token usage, estimated INR cost, and confirmed/draft stats for a deck."""
    questions = db.query(Question).filter(Question.document_id == document_id).all()
    q_ids = [q.id for q in questions]
    total_q = len(q_ids)
    if total_q == 0:
        return {
            "document_id": document_id,
            "total_questions": 0,
            "confirmed": 0,
            "draft": 0,
            "untagged": 0,
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_latency_ms": 0,
            "estimated_cost_inr": 0.0
        }

    tags = db.query(QshalaTag).filter(QshalaTag.question_id.in_(q_ids)).all()
    q_tags: Dict[str, List[QshalaTag]] = {}
    for t in tags:
        q_tags.setdefault(t.question_id, []).append(t)

    confirmed_count = 0
    draft_count = 0
    untagged_count = 0
    tokens_in = 0
    tokens_out = 0
    latency_ms = 0

    for qid in q_ids:
        tlist = q_tags.get(qid, [])
        if not tlist:
            untagged_count += 1
            continue
        active = next((t for t in tlist if t.status == "confirmed"), None)
        if active:
            confirmed_count += 1
        else:
            draft_count += 1
        for t in tlist:
            tokens_in += t.tokens_in or 0
            tokens_out += t.tokens_out or 0
            latency_ms += t.latency_ms or 0

    # Pricing for Gemini 3.5 Flash-Lite: $0.075 / 1M in, $0.30 / 1M out, $1 = ₹87
    cost_usd = (tokens_in / 1_000_000 * 0.075) + (tokens_out / 1_000_000 * 0.30)
    cost_inr = round(cost_usd * 87.0, 2)

    return {
        "document_id": document_id,
        "total_questions": total_q,
        "confirmed": confirmed_count,
        "draft": draft_count,
        "untagged": untagged_count,
        "total_tokens_in": tokens_in,
        "total_tokens_out": tokens_out,
        "total_latency_ms": latency_ms,
        "estimated_cost_inr": cost_inr
    }


@router.get("/taxonomy")
def get_taxonomy():
    """Return the active QShala taxonomy (v4) with 8 L1s, 38 L2s, and descriptions."""
    from backend.app.services.tagging.qshala_tagger import _load_taxonomy, TAXONOMY_VERSION
    tax = _load_taxonomy()
    return {
        "version": TAXONOMY_VERSION,
        "domains": [
            {
                "l1": grp["name"],
                "subtopics": [
                    {"l2": item["name"], "description": item.get("description", "")}
                    for item in grp.get("level2", [])
                ],
            }
            for grp in tax["raw"]["level1"]
        ],
        "l1": tax["l1"],
        "l2": tax["l2"],
        "l2_to_l1": tax["l2_to_l1"],
        "l2_descriptions": {
            item["name"]: item.get("description", "")
            for grp in tax["raw"]["level1"]
            for item in grp.get("level2", [])
        },
    }


@router.get("/questions")
def search_questions(
    topic_l1: Optional[str] = Query(None),
    subtopic_l2: Optional[str] = Query(None),
    india_international: Optional[str] = Query(None),
    shelf_life: Optional[str] = Query(None),
    sensitivity: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    status: Optional[str] = Query("confirmed"),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Search/filter questions by current tag, topic, geo, entity, shelf life, and text."""
    query = (
        db.query(Question, QshalaTag)
        .join(QshalaTag, Question.id == QshalaTag.question_id)
    )
    if status:
        query = query.filter(QshalaTag.status == status)
    if topic_l1:
        query = query.filter(QshalaTag.topic_l1 == topic_l1)
    if subtopic_l2:
        query = query.filter(QshalaTag.subtopic_l2 == subtopic_l2)
    if india_international:
        query = query.filter(QshalaTag.india_international == india_international)
    if shelf_life:
        query = query.filter(QshalaTag.shelf_life == shelf_life)
    if sensitivity:
        query = query.filter(QshalaTag.sensitivity == sensitivity)
    if entity_type:
        query = query.filter(QshalaTag.entity_type == entity_type)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                Question.question_text.ilike(search_filter),
                Question.answer.ilike(search_filter),
                QshalaTag.search_summary.ilike(search_filter),
            )
        )
    total = query.count()
    rows = (
        query.order_by(QshalaTag.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "question": {
                    "id": q.id,
                    "question_text": q.question_text,
                    "answer": q.answer,
                    "document_id": q.document_id,
                },
                "tag": _tag_to_dict(t),
            }
            for q, t in rows
        ],
    }


@router.get("/search")
def search_vault(
    q: Optional[str] = Query(None, description="Free-text query to search question_text, keywords_l3, search_summary, subtopic_l2, secondary_l2"),
    topic_l1: Optional[str] = Query(None, description="Filter by L1 topic"),
    india_international: Optional[str] = Query(None, description="IN | INTL | MIXED"),
    shelf_life: Optional[str] = Query(None, description="EVERGREEN | REVIEW_YEARLY | TIME_SENSITIVE"),
    sensitivity: Optional[str] = Query(None, description="NONE | POLITICAL | MATURE_REFERENCE"),
    exclude_image_dependent: bool = Query(False, description="Exclude image-dependent questions"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Retrieval query for quiz-prompt search.

    Given free text + optional filters (topic_l1, india_international, shelf_life, sensitivity,
    exclude image-dependent), returns matching questions.
    Matches if text hits question_text, keywords_l3, search_summary, subtopic_l2 OR secondary_l2.
    Uses the latest tag row per question regardless of confirmed/draft.
    """
    # 1. Subquery to find latest tag per question
    latest_subq = (
        db.query(
            QshalaTag.question_id,
            func.max(QshalaTag.created_at).label("max_created_at")
        )
        .group_by(QshalaTag.question_id)
        .subquery()
    )

    query = (
        db.query(Question, QshalaTag, QshalaQuestionMetadata)
        .join(latest_subq, Question.id == latest_subq.c.question_id)
        .join(
            QshalaTag,
            (QshalaTag.question_id == latest_subq.c.question_id) &
            (QshalaTag.created_at == latest_subq.c.max_created_at)
        )
        .outerjoin(QshalaQuestionMetadata, Question.id == QshalaQuestionMetadata.question_id)
    )

    # 2. Free-text matching across question_text, keywords_l3, search_summary, subtopic_l2, secondary_l2
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Question.question_text.ilike(term),
                Question.answer.ilike(term),
                QshalaTag.search_summary.ilike(term),
                QshalaTag.subtopic_l2.ilike(term),
                cast(QshalaTag.secondary_l2, String).ilike(term),
                cast(QshalaTag.keywords_l3, String).ilike(term),
            )
        )

    # 3. Optional filters
    if topic_l1:
        query = query.filter(QshalaTag.topic_l1 == topic_l1)
    if india_international:
        query = query.filter(QshalaTag.india_international == india_international)
    if shelf_life:
        query = query.filter(QshalaTag.shelf_life == shelf_life)
    if sensitivity:
        query = query.filter(QshalaTag.sensitivity == sensitivity)

    # 4. Exclude image-dependent
    if exclude_image_dependent:
        query = query.filter(
            or_(Question.image_refs.is_(None), cast(Question.image_refs, String) == "[]"),
            or_(Question.question_images.is_(None), cast(Question.question_images, String) == "[]"),
        )
        visual_patterns = [
            "%in the picture%", "%in the photo%", "%in the image%",
            "%seen here%", "%on the screen%", "%this logo%", "%whose logo%",
            "%identify the logo%", "%this photo%", "%this image%"
        ]
        for pat in visual_patterns:
            query = query.filter(Question.question_text.notilike(pat))

    total = query.count()
    rows = (
        query.order_by(QshalaTag.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = []
    for q_obj, tag_obj, meta in rows:
        results.append({
            "id": q_obj.id,
            "question_text": q_obj.question_text,
            "answer": q_obj.answer,
            "document_id": q_obj.document_id,
            "difficulty": q_obj.difficulty,
            "difficulty_score": q_obj.difficulty_score,
            "cognitive_level": q_obj.cognitive_level,
            "grade_min": q_obj.grade_min,
            "grade_max": q_obj.grade_max,
            "options": q_obj.options,
            "explanation": q_obj.explanation,

            # Taxonomy & Tags (v5.1)
            "topic_l1": tag_obj.topic_l1,
            "subtopic_l2": tag_obj.subtopic_l2,
            "secondary_l2": tag_obj.secondary_l2 or [],
            "keywords_l3": tag_obj.keywords_l3 or [],
            "entity_type": tag_obj.entity_type,
            "search_summary": tag_obj.search_summary,
            "fit": tag_obj.fit,
            "confidence": tag_obj.confidence,
            "status": tag_obj.status,
            "tag_id": tag_obj.id,

            # Geographic & Temporal Metadata
            "city_name": tag_obj.city_name or (meta.city_name if hasattr(meta, "city_name") else None),
            "geo_region": tag_obj.geo_region or (meta.geo_region if hasattr(meta, "geo_region") else None),
            "india_international": tag_obj.india_international,
            "shelf_life": tag_obj.shelf_life,
            "sensitivity": tag_obj.sensitivity,

            # Base Excel / Ingestion Metadata (Presentation Details)
            "star_marked": meta.star_marked if meta else False,
            "question_number": meta.question_number if meta else None,
            "answer_type": meta.answer_type if meta else None,
            "media_type": meta.media_type if meta else None,
            "clue_media_url": meta.clue_media_url if meta else None,
            "reveal_media_url": meta.reveal_media_url if meta else None,
            "round_stage": meta.round_stage if meta else None,
            "question_format": meta.question_format if meta else None,
            "college_institution": meta.college_institution if meta else None,
            "quiz_name": meta.quiz_name if meta else None,
            "source_presentation": meta.source_presentation if meta else (f"{q_obj.document_id}.pptx" if q_obj.document_id else None),
            "primary_audience": meta.primary_audience if meta else None,
            "secondary_audience": meta.secondary_audience if meta else None,
            "language": meta.language if meta else "English",

            # Verification & Audit Details
            "fact_check_url": tag_obj.fact_check_url,
            "verified_by": tag_obj.verified_by,
            "verified_at": tag_obj.verified_at.isoformat() if tag_obj.verified_at else None,
            "verification_notes": tag_obj.verification_notes,
            "created_at": tag_obj.created_at.isoformat() if tag_obj.created_at else None,
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "query": q,
        "filters": {
            "topic_l1": topic_l1,
            "india_international": india_international,
            "shelf_life": shelf_life,
            "sensitivity": sensitivity,
            "exclude_image_dependent": exclude_image_dependent,
        },
        "results": results,
    }
