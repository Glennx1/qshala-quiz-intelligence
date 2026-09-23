from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, desc, asc
from backend.app.database import get_db
from backend.app.models.question import Question
from backend.app.models.document import Document, Slide
from backend.app.schemas.question import QuestionResponse
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever

router = APIRouter(prefix="/questions", tags=["Knowledge Base Questions"])

def to_question_response(q: Question, doc: Optional[Document], slide: Optional[Slide]) -> QuestionResponse:
    return QuestionResponse(
        id=q.id,
        content_hash=getattr(q, "content_hash", None),
        document_id=q.document_id,
        slide_id=q.slide_id,
        answer_slide_id=q.answer_slide_id,
        question_text=q.question_text,
        answer=q.answer,
        options=q.options,
        explanation=q.explanation,
        topic=q.topic,
        subtopic=q.subtopic,
        topics=getattr(q, "topics", []) or [q.topic],
        tags=getattr(q, "tags", []) or [],
        difficulty=q.difficulty or "Medium",
        difficulty_score=getattr(q, "difficulty_score", 0.50) or 0.50,
        cognitive_level=getattr(q, "cognitive_level", "Recall / Remember") or "Recall / Remember",
        grade_min=q.grade_min or 3,
        grade_max=q.grade_max or 12,
        audience_suitability=getattr(q, "audience_suitability", []) or [],
        question_hook=getattr(q, "question_hook", "DIRECT_TRIVIA") or "DIRECT_TRIVIA",
        curiosity_score=getattr(q, "curiosity_score", 7) or 7,
        temporal_nature=getattr(q, "temporal_nature", "EVERGREEN") or "EVERGREEN",
        occurrence_count=getattr(q, "occurrence_count", 1) or 1,
        provenance_decks=getattr(q, "provenance_decks", []) or [],
        round_number=getattr(q, "round_number", None),
        question_type=q.question_type or "SLIDE_QA",
        source_year=q.source_year,
        created_at=q.created_at,
        document_title=doc.title if doc else None,
        slide_number=slide.slide_number if slide else None
    )

@router.get("/topics", response_model=List[Dict[str, Any]])
def list_vault_topics(db: Session = Depends(get_db)):
    """
    Returns all distinct topics currently stored in the Question Vault along with their counts.
    Used for predictive topic autocomplete and topic browsing.
    """
    results = (
        db.query(Question.topic, func.count(Question.id).label("count"))
        .filter(Question.topic.isnot(None))
        .group_by(Question.topic)
        .order_by(desc("count"))
        .all()
    )
    return [{"topic": r[0], "count": r[1]} for r in results]

@router.get("/topics/{topic}/summary", response_model=Dict[str, Any])
def get_topic_summary(topic: str, db: Session = Depends(get_db)):
    """
    Returns deep pedagogical metadata for a given topic in the vault:
    total questions, difficulty breakdown, subtopics, grade coverage, and previews.
    """
    questions = (
        db.query(Question)
        .filter(or_(Question.topic.ilike(f"%{topic}%"), Question.subtopic.ilike(f"%{topic}%")))
        .all()
    )

    if not questions:
        return {
            "topic": topic,
            "total_questions": 0,
            "difficulty_breakdown": {"Easy": 0, "Medium": 0, "Hard": 0},
            "subtopics": [],
            "grade_min": None,
            "grade_max": None,
            "sample_questions": []
        }

    diff_counts = {"Easy": 0, "Medium": 0, "Hard": 0}
    subtopics = set()
    grade_mins = []
    grade_maxs = []

    for q in questions:
        d = q.difficulty or "Medium"
        diff_counts[d] = diff_counts.get(d, 0) + 1
        if q.subtopic:
            subtopics.add(q.subtopic)
        if q.grade_min:
            grade_mins.append(q.grade_min)
        if q.grade_max:
            grade_maxs.append(q.grade_max)

    samples = [
        {"question_text": q.question_text, "difficulty": q.difficulty, "answer": q.answer}
        for q in questions[:3]
    ]

    return {
        "topic": topic,
        "total_questions": len(questions),
        "difficulty_breakdown": diff_counts,
        "subtopics": sorted(list(subtopics)),
        "grade_min": min(grade_mins) if grade_mins else 3,
        "grade_max": max(grade_maxs) if grade_maxs else 12,
        "sample_questions": samples
    }

@router.get("", response_model=List[QuestionResponse])
async def search_questions(
    query: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    subtopic: Optional[str] = Query(None),
    grade_min: Optional[int] = Query(None),
    grade_max: Optional[int] = Query(None),
    difficulty: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("created_at"),
    sort_order: Optional[str] = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    if query:
        # Perform semantic/hybrid search
        retriever = HybridRetriever(db)
        results = await retriever.search(
            query=query,
            topic=topic,
            grade_min=grade_min,
            grade_max=grade_max,
            difficulty=difficulty,
            limit=limit
        )
        output = []
        for r in results:
            output.append(to_question_response(r["question"], r["document"], r["slide"]))
        return output

    # Direct query with rich metadata filters
    q_builder = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id)

    if topic:
        q_builder = q_builder.filter(
            or_(
                Question.topic.ilike(f"%{topic}%"),
                Question.subtopic.ilike(f"%{topic}%")
            )
        )
    if subtopic:
        q_builder = q_builder.filter(Question.subtopic.ilike(f"%{subtopic}%"))
    if difficulty:
        q_builder = q_builder.filter(Question.difficulty.ilike(difficulty))
    if grade_min is not None:
        q_builder = q_builder.filter(Question.grade_min >= grade_min)
    if grade_max is not None:
        q_builder = q_builder.filter(Question.grade_max <= grade_max)

    # Sorting
    sort_col = getattr(Question, sort_by, Question.created_at)
    if sort_order == "asc":
        q_builder = q_builder.order_by(asc(sort_col))
    else:
        q_builder = q_builder.order_by(desc(sort_col))

    items = q_builder.offset(offset).limit(limit).all()

    output = []
    for q, doc, slide in items:
        output.append(to_question_response(q, doc, slide))
    return output

@router.get("/{question_id}", response_model=QuestionResponse)
def get_question(question_id: str, db: Session = Depends(get_db)):
    item = db.query(Question, Document, Slide).\
        join(Document, Question.document_id == Document.id).\
        outerjoin(Slide, Question.slide_id == Slide.id).\
        filter(Question.id == question_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Question not found")

    q, doc, slide = item
    return to_question_response(q, doc, slide)
