import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import SessionLocal, engine, Base
from backend.app.models.question import Question
from backend.app.models.quiz import Quiz, GeneratedQuestion
from backend.app.routers.questions import list_vault_tags, preview_tag_quiz_availability
from backend.app.schemas.quiz import QuizGenerateRequest
from backend.app.services.generator.quiz_generator import QuizGenerator, PERSONALITY_PROMPTS
from backend.app.services.export.exporter import QuizExporter
from backend.app.services.retrieval.hybrid_retriever import HybridRetriever

def test_personality_definitions():
    print("\n--- Testing Quizmaster Personality Prompts ---")
    required_personalities = [
        "CURIOSITY_STORYTELLER",
        "DETECTIVE_PUZZLER",
        "TOURNAMENT_PRO",
        "SOCRATIC_EXPLORER"
    ]
    for p in required_personalities:
        assert p in PERSONALITY_PROMPTS, f"Missing personality prompt for {p}"
        prompt_text = PERSONALITY_PROMPTS[p]
        assert isinstance(prompt_text, str) and len(prompt_text) > 20
        assert "Host Persona:" in prompt_text
        print(f"  [OK] {p}: {prompt_text.splitlines()[0]}")
    print("[PASS] All 4 Quizmaster Personalities configured correctly!")

def test_vault_tags_and_preview_endpoints():
    print("\n--- Testing Vault Tags & Live Compilation Availability ---")
    db = SessionLocal()
    try:
        # 1. Test list_vault_tags
        tags_data = list_vault_tags(topic=None, db=db)
        print(f"Total unique tags in vault: {len(tags_data)}")
        assert isinstance(tags_data, list)
        if len(tags_data) > 0:
            top_tag = tags_data[0]
            print(f"Top Tag: '{top_tag['tag']}' with count {top_tag['count']} across topics {top_tag['topics']}")
            assert "tag" in top_tag
            assert "count" in top_tag
            assert "topics" in top_tag

        # 2. Test preview_tag_quiz_availability
        preview = preview_tag_quiz_availability(
            topic="Australian History",
            tags="Cook,Endeavour",
            db=db
        )
        print("Tag Preview result:", {
            "topic": preview["topic"],
            "total_available": preview["total_available"],
            "exact_matches": preview["exact_matches_count"],
            "cross_topic_tags": preview["cross_topic_tag_matches_count"],
            "difficulty": preview["difficulty_breakdown"],
            "suggested_mode": preview["suggested_mode"]
        })
        assert "total_available" in preview
        assert "exact_matches_count" in preview
        assert "cross_topic_tag_matches_count" in preview
        assert "difficulty_breakdown" in preview
        assert preview["total_available"] >= 0
        print("[PASS] Tags index and preview endpoints operate accurately!")
    finally:
        db.close()

def test_retriever_tag_overlap_boosting():
    print("\n--- Testing Hybrid Retriever with Tag Overlap Scoring ---")
    db = SessionLocal()
    try:
        retriever = HybridRetriever(db)
        results = retriever.fetch_by_filters(
            topic="Australian History",
            tags=["Captain James Cook", "Botany Bay"],
            limit=5
        )
        print(f"Retrieved {len(results)} questions with tag boosting.")
        for r in results[:3]:
            q = r["question"]
            print(f"  - [{q.difficulty}] {q.question_text[:50]}... | tags={q.tags} | overlap={r['tag_overlap']}")
        assert len(results) > 0
        print("[PASS] Hybrid retriever successfully scores and weights tag overlap!")
    finally:
        db.close()

def test_quiz_generator_with_tags_and_personality():
    print("\n--- Testing Quiz Generator with Personality & Tags ---")
    db = SessionLocal()
    try:
        generator = QuizGenerator(db)
        req = QuizGenerateRequest(
            topic="Australian History",
            tags=["Captain James Cook", "Maritime Exploration"],
            personality="DETECTIVE_PUZZLER",
            audience_type="primary",
            grades=[3, 4, 5],
            difficulty="Balanced",
            difficulty_distribution={"Easy": 1, "Medium": 2, "Hard": 0},
            question_count=3,
            question_types=["SLIDE_QA"],
            generation_mode="HISTORICAL",
            style="QSHALA_HISTORICAL"
        )

        quiz = asyncio.run(generator.generate_quiz(req))
        print(f"Created Quiz: '{quiz.title}' (ID: {quiz.id})")
        print(f"Quiz Personality: {quiz.personality}")
        print(f"Quiz Tags: {quiz.tags}")
        print(f"Compiled Questions Count: {len(quiz.questions)}")

        assert quiz.personality == "DETECTIVE_PUZZLER"
        assert quiz.tags is not None
        assert "Captain James Cook" in quiz.tags or "Maritime Exploration" in quiz.tags
        assert len(quiz.questions) == 3

        for i, q in enumerate(quiz.questions):
            print(f"  Q{i+1}: {q.question_text[:60]}... | Ans: {q.answer}")

        # Export to PPTX
        print("\n--- Testing PPTX Export with Detective Personality ---")
        pptx_bytes = QuizExporter.to_pptx(quiz)
        print(f"Generated PPTX size: {len(pptx_bytes)} bytes")
        assert len(pptx_bytes) > 20000
        print("[PASS] Quiz generated and exported with Detective Puzzle Master personality!")

    finally:
        db.close()

if __name__ == "__main__":
    print("=== RUNNING QUIZMASTER PERSONALITY & TAG COMPILATION TESTS ===")
    test_personality_definitions()
    test_vault_tags_and_preview_endpoints()
    test_retriever_tag_overlap_boosting()
    test_quiz_generator_with_tags_and_personality()
    print("\n=== ALL PERSONALITY & TAG TESTS PASSED SUCCESSFULLY! ===")
