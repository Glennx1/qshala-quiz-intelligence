import asyncio
import sys
from pathlib import Path
from collections import Counter

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import SessionLocal, engine, Base
from backend.app.models.quiz import Quiz, GeneratedQuestion
from backend.app.services.generator.quiz_generator import QuizGenerator
from backend.app.schemas.quiz import QuizGenerateRequest

async def run_scenario(generator, scenario_num, name, req_kwargs, expected):
    print(f"\n=======================================================")
    print(f"RUNNING SCENARIO {scenario_num}: {name}")
    print(f"=======================================================")
    req = QuizGenerateRequest(**req_kwargs)
    quiz = await generator.generate_quiz(req)

    print(f"Quiz Title: {quiz.title}")
    print(f"Audience Type: {quiz.audience_type}")
    print(f"Grades: {quiz.grades}")
    print(f"Question Count: {len(quiz.questions)}")
    print(f"Saved Distribution: {quiz.difficulty_distribution}")

    diff_counts = Counter(q.difficulty for q in quiz.questions)
    print(f"Actual Question Difficulties: {dict(diff_counts)}")

    # Verification assertions
    assert len(quiz.questions) == expected["total_questions"], (
        f"Expected {expected['total_questions']} questions, got {len(quiz.questions)}"
    )
    assert diff_counts.get("Easy", 0) == expected["easy"], (
        f"Expected {expected['easy']} Easy, got {diff_counts.get('Easy', 0)}"
    )
    assert diff_counts.get("Medium", 0) == expected["medium"], (
        f"Expected {expected['medium']} Medium, got {diff_counts.get('Medium', 0)}"
    )
    assert diff_counts.get("Hard", 0) == expected["hard"], (
        f"Expected {expected['hard']} Hard, got {diff_counts.get('Hard', 0)}"
    )

    if expected.get("audience_type"):
        assert quiz.audience_type == expected["audience_type"], (
            f"Expected audience {expected['audience_type']}, got {quiz.audience_type}"
        )

    # Verify each question has valid provenance and validation status
    for idx, q in enumerate(quiz.questions, 1):
        assert q.validation_status in ["PASSED", "WARNING"], f"Question {idx} failed validation: {q.validation_status}"
        assert len(q.options or []) == 4, f"Question {idx} should have 4 MCQ options"
        assert q.answer, f"Question {idx} missing answer"

    print(f"[PASS] Scenario {scenario_num} passed all assertions!")
    return quiz

async def main():
    print("=== QSHALA AUDIENCE & DIFFICULTY DISTRIBUTION SCENARIO TESTS ===")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    generator = QuizGenerator(db)

    # Scenario 1: Grades 3–5, 20 questions, 5 Easy / 10 Medium / 5 Hard
    await run_scenario(
        generator=generator,
        scenario_num=1,
        name="Grades 3–5, 20 Qs (5 Easy / 10 Med / 5 Hard)",
        req_kwargs={
            "topic": "Australian History",
            "audience_type": "primary",
            "grades": [3, 4, 5],
            "grade_min": 3,
            "grade_max": 5,
            "difficulty": "Balanced",
            "difficulty_distribution": {"easy": 5, "medium": 10, "hard": 5},
            "question_count": 20,
            "question_types": ["MULTIPLE_CHOICE"],
            "generation_mode": "NEW"
        },
        expected={"total_questions": 20, "easy": 5, "medium": 10, "hard": 5, "audience_type": "primary"}
    )

    # Scenario 2: Grades 1–2, 10 questions, 3 Easy / 5 Medium / 2 Hard
    await run_scenario(
        generator=generator,
        scenario_num=2,
        name="Grades 1–2, 10 Qs (3 Easy / 5 Med / 2 Hard)",
        req_kwargs={
            "topic": "Australian Wildlife & History",
            "audience_type": "primary",
            "grades": [1, 2],
            "grade_min": 1,
            "grade_max": 2,
            "difficulty": "Balanced",
            "difficulty_distribution": {"easy": 3, "medium": 5, "hard": 2},
            "question_count": 10,
            "question_types": ["MULTIPLE_CHOICE"],
            "generation_mode": "NEW"
        },
        expected={"total_questions": 10, "easy": 3, "medium": 5, "hard": 2, "audience_type": "primary"}
    )

    # Scenario 3: Grades 11–12, 20 questions, 5 Easy / 10 Medium / 5 Hard
    await run_scenario(
        generator=generator,
        scenario_num=3,
        name="Grades 11–12, 20 Qs (5 Easy / 10 Med / 5 Hard)",
        req_kwargs={
            "topic": "Australian Modern History",
            "audience_type": "high_school",
            "grades": [11, 12],
            "grade_min": 11,
            "grade_max": 12,
            "difficulty": "Balanced",
            "difficulty_distribution": {"easy": 5, "medium": 10, "hard": 5},
            "question_count": 20,
            "question_types": ["MULTIPLE_CHOICE"],
            "generation_mode": "NEW"
        },
        expected={"total_questions": 20, "easy": 5, "medium": 10, "hard": 5, "audience_type": "high_school"}
    )

    # Scenario 4: College, 20 questions, 2 Easy / 10 Medium / 8 Hard
    await run_scenario(
        generator=generator,
        scenario_num=4,
        name="College / University, 20 Qs (2 Easy / 10 Med / 8 Hard)",
        req_kwargs={
            "topic": "Australian Constitutional History",
            "audience_type": "college",
            "difficulty": "Hard-heavy",
            "difficulty_distribution": {"easy": 2, "medium": 10, "hard": 8},
            "question_count": 20,
            "question_types": ["MULTIPLE_CHOICE"],
            "generation_mode": "NEW"
        },
        expected={"total_questions": 20, "easy": 2, "medium": 10, "hard": 8, "audience_type": "college"}
    )

    # Scenario 5: Adults, 10 questions, 2 Easy / 5 Medium / 3 Hard
    await run_scenario(
        generator=generator,
        scenario_num=5,
        name="Adults, 10 Qs (2 Easy / 5 Med / 3 Hard)",
        req_kwargs={
            "topic": "Australian Cultural Trivia",
            "audience_type": "adult",
            "difficulty": "Custom",
            "difficulty_distribution": {"easy": 2, "medium": 5, "hard": 3},
            "question_count": 10,
            "question_types": ["MULTIPLE_CHOICE"],
            "generation_mode": "NEW"
        },
        expected={"total_questions": 10, "easy": 2, "medium": 5, "hard": 3, "audience_type": "adult"}
    )

    print("\n=======================================================")
    print("ALL 5 REQUIRED SCENARIOS SUCCESSFULLY TESTED AND PASSED!")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(main())
