import re
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
    # Refinement: pass the `brief` from a prior /draft response alongside a follow-up prompt
    # ("make it harder", "swap cricket for tech", "give me 5 more") to refine instead of restart.
    previous_brief: Optional[Dict[str, Any]] = None
    keep_ids: List[str] = []
    exclude_ids: List[str] = []
    current_questions: Optional[List[Dict[str, Any]]] = None


class SwapReq(BaseModel):
    prompt: str
    question_id: str
    keep_ids: List[str] = []
    options: Dict[str, Any] = {}


class SaveReq(BaseModel):
    title: Optional[str] = None
    prompt: str
    question_ids: List[str] = Field(..., min_length=1, max_length=50)
    brief: Optional[Dict[str, Any]] = None


@router.get("/starters")
def starters():
    return {"starters": STARTERS}


@router.post("/draft")
def draft(req: DraftReq, db: Session = Depends(get_db)):
    # 1. Single slot targeted replacement check:
    # e.g., "replace question 3 with fintech", "change card 10 to tech", "swap question 5"
    slot_match = re.search(
        r"\b(?:replace|change|swap)\s+(?:question|slot|card|#)?\s*(\d{1,2})\b(?:\s+(?:with|for|to)\s+(.*))?",
        req.prompt,
        re.I
    )
    if slot_match and req.current_questions:
        slot_num = int(slot_match.group(1))
        if 1 <= slot_num <= len(req.current_questions):
            target_q = req.current_questions[slot_num - 1]
            target_id = target_q.get("id")
            other_ids = [q["id"] for i, q in enumerate(req.current_questions) if i != slot_num - 1 and "id" in q]
            sub_topic = (slot_match.group(2) or "").strip()

            swap_prompt = sub_topic if sub_topic else (
                (req.previous_brief or {}).get("query") or req.prompt
            )
            effective_exclude = set(other_ids) | {target_id} | set(req.exclude_ids or [])

            new_q = engine.swap_one(db, swap_prompt, target_id, keep_ids=other_ids, options=req.options)
            if not new_q:
                sub_res = engine.build_draft(
                    db, swap_prompt, count=1, options=req.options, exclude_ids=effective_exclude
                )
                if sub_res.get("questions"):
                    new_q = sub_res["questions"][0]

            if new_q:
                bank = engine._load_bank(db)
                bank_by_id = {b["id"]: engine._view(b) for b in bank}
                updated_questions = []
                for i, q in enumerate(req.current_questions):
                    if i == slot_num - 1:
                        updated_questions.append(new_q)
                    else:
                        qid = q.get("id")
                        updated_questions.append(bank_by_id.get(qid, q))

                topic_desc = f"with a {sub_topic} question" if sub_topic else "with another question"
                prev_b = req.previous_brief or {"query": swap_prompt, "count": len(updated_questions)}
                return {
                    "brief": prev_b,
                    "questions": updated_questions,
                    "message": f"Replaced question {slot_num} {topic_desc} while keeping the rest of the quiz.",
                    "bank_size": len(bank),
                    "stages": ["Interpreter", "Librarian", "Guardian", "Editor", "Host"],
                    "fulfillment": {
                        "requested": len(updated_questions),
                        "delivered": len(updated_questions),
                        "short": False,
                        "note": f"Replaced question {slot_num}."
                    }
                }

    # 2. General refinement or new draft:
    effective_exclude = set(req.keep_ids) | set(req.exclude_ids or [])
    res = engine.build_draft(
        db, req.prompt, req.count, req.options, req.previous_brief,
        exclude_ids=effective_exclude,
        current_questions=req.current_questions
    )

    # 3. Merging logic:
    target_count = res["brief"]["count"]
    bank = engine._load_bank(db)
    bank_by_id = {b["id"]: engine._view(b) for b in bank}
    new_candidates = res["questions"]

    if req.keep_ids:
        # User explicitly locked certain questions
        kept_set = set(req.keep_ids)
        if req.current_questions:
            # Preserve locked questions in their exact slots
            result_slots = [None] * min(len(req.current_questions), target_count)
            cand_idx = 0
            for i, q in enumerate(req.current_questions):
                if i < len(result_slots) and q.get("id") in kept_set:
                    qid = q.get("id")
                    result_slots[i] = bank_by_id.get(qid, q)
            for i in range(len(result_slots)):
                if result_slots[i] is None:
                    if cand_idx < len(new_candidates):
                        result_slots[i] = new_candidates[cand_idx]
                        cand_idx += 1
            combined = [q for q in result_slots if q is not None]
            while len(combined) < target_count and cand_idx < len(new_candidates):
                combined.append(new_candidates[cand_idx])
                cand_idx += 1
        else:
            kept = [bank_by_id[qid] for qid in req.keep_ids if qid in bank_by_id]
            kept_ids = {q["id"] for q in kept}
            remaining = [q for q in new_candidates if q["id"] not in kept_ids]
            combined = (kept + remaining)[:target_count]

        res["questions"] = combined
        kept_len = len([q for q in combined if q["id"] in kept_set])
        replaced_len = len(combined) - kept_len
        res["message"] = f"Refined quiz: kept {kept_len} locked question{'s' if kept_len != 1 else ''} and updated {replaced_len}."

    elif req.previous_brief:
        # Refinement without explicit locks: check if count addition was requested
        p_lower = req.prompt.lower()
        more_m = re.search(r"\b(?:add|give\s+me\s+)?(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+more\b", p_lower)
        if more_m and req.current_questions:
            # Append new questions to the current quiz
            curr_ids = {q["id"] for q in req.current_questions if "id" in q}
            curr_qs = [bank_by_id.get(q["id"], q) for q in req.current_questions if "id" in q]
            fresh = [q for q in new_candidates if q["id"] not in curr_ids]
            combined = (curr_qs + fresh)[:target_count]
            res["questions"] = combined
            res["message"] = f"Expanded quiz to {len(combined)} questions."
        else:
            res["message"] = f"Refined quiz: updated questions based on '{req.prompt}'."

    if "fulfillment" in res:
        res["fulfillment"]["delivered"] = len(res["questions"])
        res["fulfillment"]["short"] = len(res["questions"]) < target_count

    return res


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
