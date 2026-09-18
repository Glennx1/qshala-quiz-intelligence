from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from backend.app.database import get_db
from backend.app.models.document import Document, Slide
from backend.app.models.question import Question
from backend.app.models.quiz import Quiz
from backend.app.schemas.stats import DashboardStatsResponse

router = APIRouter(prefix="/stats", tags=["Dashboard Stats"])

@router.get("", response_model=DashboardStatsResponse)
def get_stats(db: Session = Depends(get_db)):
    doc_count = db.query(Document).count()
    slide_count = db.query(Slide).count()
    question_count = db.query(Question).count()
    quiz_count = db.query(Quiz).count()

    # Distinct topics count
    distinct_topics = db.query(Question.topic).distinct().count()

    recent_docs = db.query(Document).order_by(Document.created_at.desc()).limit(5).all()
    recent_quizzes = db.query(Quiz).order_by(Quiz.created_at.desc()).limit(5).all()

    # Top topics with question counts
    top_topics_query = db.query(Question.topic, func.count(Question.id).label("count")).\
        group_by(Question.topic).\
        order_by(func.count(Question.id).desc()).\
        limit(6).all()

    return DashboardStatsResponse(
        total_documents=doc_count,
        total_slides=slide_count,
        total_questions=question_count,
        total_topics=distinct_topics,
        total_quizzes=quiz_count,
        recent_documents=[
            {
                "id": d.id,
                "title": d.title,
                "filename": d.filename,
                "slide_count": d.slide_count,
                "question_count": d.question_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "status": d.processing_status
            }
            for d in recent_docs
        ],
        recent_quizzes=[
            {
                "id": q.id,
                "title": q.title,
                "topic": q.topic,
                "question_count": q.question_count,
                "difficulty": q.difficulty,
                "grade_range": f"Grades {q.grade_min}–{q.grade_max}" if (q.grade_min and q.grade_max) else ((q.audience_type or "general").replace("_", " ").title()),
                "created_at": q.created_at.isoformat() if q.created_at else None
            }
            for q in recent_quizzes
        ],
        top_topics=[
            {"topic": t[0], "count": t[1]}
            for t in top_topics_query
        ]
    )
