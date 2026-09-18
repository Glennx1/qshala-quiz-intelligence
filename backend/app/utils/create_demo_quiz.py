import asyncio
from backend.app.database import SessionLocal
from backend.app.services.generator.quiz_generator import QuizGenerator
from backend.app.schemas.quiz import QuizGenerateRequest

async def make_demo_quiz():
    db = SessionLocal()
    generator = QuizGenerator(db)
    req = QuizGenerateRequest(
        topic="Australian History",
        grade_min=3,
        grade_max=5,
        difficulty="Medium",
        question_count=10,
        question_types=["MULTIPLE_CHOICE"],
        generation_mode="NEW",
        style="QSHALA_HISTORICAL"
    )
    quiz = await generator.generate_quiz(req)
    print(f"Generated Demo Quiz: ID={quiz.id}, Title='{quiz.title}', Questions={len(quiz.questions)}")
    db.close()

if __name__ == "__main__":
    asyncio.run(make_demo_quiz())
