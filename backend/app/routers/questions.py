from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from backend.app.database import get_db
from backend.app.models.question import Question
from backend.app.models.document import Document, Slide
from backend.app.schemas.question import QuestionResponse
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever

router = APIRouter(prefix="/questions", tags=["Knowledge Base Questions"])

@router.get("", response_model=List[QuestionResponse])
async def search_questions(
    query: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    grade_min: Optional[int] = Query(None),
    grade_max: Optional[int] = Query(None),
    difficulty: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
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
            q = r["question"]
            doc = r["document"]
            slide = r["slide"]
            output.append(QuestionResponse(
                id=q.id,
                document_id=q.document_id,
                slide_id=q.slide_id,
                answer_slide_id=q.answer_slide_id,
                question_text=q.question_text,
                answer=q.answer,
                options=q.options,
                explanation=q.explanation,
                topic=q.topic,
                subtopic=q.subtopic,
                difficulty=q.difficulty,
                grade_min=q.grade_min,
                grade_max=q.grade_max,
                question_type=q.question_type,
                source_year=q.source_year,
                created_at=q.created_at,
                document_title=doc.title if doc else None,
                slide_number=slide.slide_number if slide else None
            ))
        return output

    # Direct query with filters
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
    if difficulty:
        q_builder = q_builder.filter(Question.difficulty.ilike(difficulty))
    if grade_min is not None:
        q_builder = q_builder.filter(Question.grade_min >= grade_min)
    if grade_max is not None:
        q_builder = q_builder.filter(Question.grade_max <= grade_max)

    items = q_builder.order_by(Question.created_at.desc()).offset(offset).limit(limit).all()

    output = []
    for q, doc, slide in items:
        output.append(QuestionResponse(
            id=q.id,
            document_id=q.document_id,
            slide_id=q.slide_id,
            answer_slide_id=q.answer_slide_id,
            question_text=q.question_text,
            answer=q.answer,
            options=q.options,
            explanation=q.explanation,
            topic=q.topic,
            subtopic=q.subtopic,
            difficulty=q.difficulty,
            grade_min=q.grade_min,
            grade_max=q.grade_max,
            question_type=q.question_type,
            source_year=q.source_year,
            created_at=q.created_at,
            document_title=doc.title if doc else None,
            slide_number=slide.slide_number if slide else None
        ))
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
    return QuestionResponse(
        id=q.id,
        document_id=q.document_id,
        slide_id=q.slide_id,
        answer_slide_id=q.answer_slide_id,
        question_text=q.question_text,
        answer=q.answer,
        options=q.options,
        explanation=q.explanation,
        topic=q.topic,
        subtopic=q.subtopic,
        difficulty=q.difficulty,
        grade_min=q.grade_min,
        grade_max=q.grade_max,
        question_type=q.question_type,
        source_year=q.source_year,
        created_at=q.created_at,
        document_title=doc.title if doc else None,
        slide_number=slide.slide_number if slide else None
    )
