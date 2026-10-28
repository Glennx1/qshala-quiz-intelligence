from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models.question import Question
from backend.app.models.quiz import Quiz, GeneratedQuestion, RetrievalSource
from backend.app.services.prompt_quiz import engine

router = APIRouter(prefix="/prompt-quiz", tags=["Prompt Quiz"])

STARTERS = [
    "10 evergreen questions on Indian startups",
    "A tough 15-question finals round on banking and money",
    "Warm-up quiz on brands and logos, no images",
    "20 questions on cricket and the IPL, school safe",
    "A fintech and UPI round, 8 questions",
    "Something fun on food and festivals for a family night",
]


class DraftReq(BaseModel):
    prompt: str = Field(..., min_length=2, max_length=600)
    count: Optional[int] = Field(default=None, ge=1, le=50)
    options: Dict[str, Any] = {}


class SwapReq(BaseModel):
    prompt: str
    question_id: str
    keep_ids: List[str] = []
    options: Dict[str, Any] = {}


class SaveReq(BaseModel):
    title: Optional[str] = None
    prompt: str
    question_ids: List[str] = Field(..., min_length=1, max_length=50)


@router.get("/starters")
def starters():
    return {"starters": STARTERS}


@router.post("/draft")
def draft(req: DraftReq, db: Session = Depends(get_db)):
    return engine.build_draft(db, req.prompt, req.count, req.options)


@router.post("/swap")
def swap(req: SwapReq, db: Session = Depends(get_db)):
    q = engine.swap_one(db, req.prompt, req.question_id, req.keep_ids, req.options)
    if not q:
        raise HTTPException(status_code=404, detail="No other matching question found")
    return q


@router.post("/save")
def save(req: SaveReq, db: Session = Depends(get_db)):
    rows = {q.id: q for q in db.query(Question).filter(Question.id.in_(req.question_ids)).all()}
    ordered = [rows[i] for i in req.question_ids if i in rows]
    if not ordered:
        raise HTTPException(status_code=400, detail="None of those questions exist")
    topics = [q.topic for q in ordered if q.topic]
    topic = max(set(topics), key=topics.count) if topics else "General"
    quiz = Quiz(title=(req.title or req.prompt)[:120], topic=topic, question_count=len(ordered),
                generation_mode="HISTORICAL", raw_prompt=req.prompt, status="READY")
    db.add(quiz)
    db.flush()
    for i, q in enumerate(ordered, 1):
        g = GeneratedQuestion(
            quiz_id=quiz.id, order_index=i, question_text=q.question_text, options=q.options,
            answer=q.answer, explanation=q.explanation, difficulty=q.difficulty or "Medium",
            grade_min=q.grade_min, grade_max=q.grade_max, topic=q.topic,
            question_type=q.question_type or "SLIDE_QA",
            image_refs=list(q.image_refs or []),
            question_images=list(q.question_images or []),
            answer_images=list(q.answer_images or []),
            raw_media_refs=list(getattr(q, "raw_media_refs", []) or []),
            visual_clues=q.visual_clues)
        db.add(g)
        db.flush()
        db.add(RetrievalSource(generated_question_id=g.id, historical_question_id=q.id,
                               document_id=q.document_id, relevance_score=1.0,
                               rationale="Picked by prompt-quiz engine"))
    db.commit()
    return {"quiz_id": quiz.id, "count": len(ordered)}
