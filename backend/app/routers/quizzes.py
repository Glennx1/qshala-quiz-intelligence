from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from backend.app.database import get_db
from backend.app.models.quiz import Quiz, GeneratedQuestion
from backend.app.schemas.quiz import (
    QuizGenerateRequest,
    QuizResponse,
    GeneratedQuestionResponse,
    GeneratedQuestionUpdate,
    QuestionActionRequest,
)
from backend.app.services.generator.quiz_generator import QuizGenerator
from backend.app.services.export.exporter import QuizExporter

router = APIRouter(prefix="/quizzes", tags=["Quizzes"])

@router.post("/generate", response_model=QuizResponse)
async def generate_quiz(
    req: QuizGenerateRequest,
    db: Session = Depends(get_db)
):
    try:
        generator = QuizGenerator(db)
        quiz = await generator.generate_quiz(req)
        return quiz
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quiz generation error: {str(e)}")

@router.get("", response_model=List[QuizResponse])
def list_quizzes(db: Session = Depends(get_db)):
    return db.query(Quiz).order_by(Quiz.created_at.desc()).all()

@router.get("/{quiz_id}", response_model=QuizResponse)
def get_quiz(quiz_id: str, db: Session = Depends(get_db)):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz

@router.patch("/questions/{question_id}", response_model=GeneratedQuestionResponse)
def update_question(
    question_id: str,
    update_data: GeneratedQuestionUpdate,
    db: Session = Depends(get_db)
):
    gen_q = db.query(GeneratedQuestion).filter(GeneratedQuestion.id == question_id).first()
    if not gen_q:
        raise HTTPException(status_code=404, detail="Question not found")

    data_dict = update_data.model_dump(exclude_unset=True)
    for field, value in data_dict.items():
        setattr(gen_q, field, value)

    db.commit()
    db.refresh(gen_q)
    return gen_q

@router.post("/questions/{question_id}/action", response_model=GeneratedQuestionResponse)
async def execute_question_action(
    question_id: str,
    req: QuestionActionRequest,
    db: Session = Depends(get_db)
):
    try:
        generator = QuizGenerator(db)
        updated_q = await generator.execute_question_action(
            question_id=question_id,
            action=req.action,
            custom_instruction=req.custom_instruction
        )
        return updated_q
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/questions/{question_id}")
def delete_question(question_id: str, db: Session = Depends(get_db)):
    gen_q = db.query(GeneratedQuestion).filter(GeneratedQuestion.id == question_id).first()
    if not gen_q:
        raise HTTPException(status_code=404, detail="Question not found")
    
    db.delete(gen_q)
    db.commit()
    return {"message": "Question deleted successfully"}

@router.get("/{quiz_id}/export")
def export_quiz(
    quiz_id: str,
    format: str = Query("json", pattern="^(json|csv|pptx)$"),
    db: Session = Depends(get_db)
):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    if format == "json":
        json_content = QuizExporter.to_json(quiz)
        return Response(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=quiz_{quiz.id[:8]}.json"}
        )
    elif format == "csv":
        csv_content = QuizExporter.to_csv(quiz)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=quiz_{quiz.id[:8]}.csv"}
        )
    elif format == "pptx":
        pptx_bytes = QuizExporter.to_pptx(quiz)
        return Response(
            content=pptx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f"attachment; filename=qshala_quiz_{quiz.id[:8]}.pptx"}
        )
