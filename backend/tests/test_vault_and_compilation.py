import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import SessionLocal, engine, Base
from backend.app.models.document import Document, Slide
from backend.app.models.question import Question
from backend.app.models.quiz import Quiz, GeneratedQuestion
from backend.app.services.tagging.auto_tagger import AutoTagger
from backend.app.services.tagging.difficulty_engine import DifficultyEngine
from backend.app.services.deduplication.deduplicator import Deduplicator
from backend.app.services.export.exporter import QuizExporter
from backend.app.routers.questions import list_vault_topics, get_topic_summary

def test_auto_tagger():
    print("\n--- Testing AutoTagger ---")
    tagger = AutoTagger()
    res = tagger.tag_question(
        question_text="Who was the navigator aboard HMS Endeavour who mapped Australia in 1770?",
        answer_text="Captain James Cook",
        explanation="Cook sailed to Botany Bay in 1770 under royal commission."
    )
    print("AutoTagger result:", res)
    assert res["primary_topic"] == "Australian History & Culture"
    assert "Australian History & Culture" in res["topics"]
    assert any("Cook" in tag or "Endeavour" in tag for tag in res["tags"])
    print("[PASS] AutoTagger accurately classifies topic and entities!")

def test_difficulty_engine():
    print("\n--- Testing DifficultyEngine ---")
    engine = DifficultyEngine()
    
    # Simple recall question
    res_easy = engine.evaluate(
        question_text="What color is the sun?",
        answer_text="Yellow"
    )
    print("Easy Question score:", res_easy["difficulty_score"], res_easy["difficulty"])
    assert res_easy["difficulty"] == "Easy"
    
    # Complex multi-step synthesis question
    res_hard = engine.evaluate(
        question_text="What links the 1854 Ballarat miners' revolt against British colonial taxation to the birth of Australian constitutional democracy?",
        answer_text="The Eureka Stockade",
        explanation="Miners took the oath under the Southern Cross flag which led directly to parliamentary electoral representation."
    )
    print("Hard Question score:", res_hard["difficulty_score"], res_hard["difficulty"])
    assert res_hard["difficulty"] in ["Medium", "Hard"]
    assert res_hard["difficulty_score"] > res_easy["difficulty_score"]
    print("[PASS] DifficultyEngine scores cognitive depth and entity obscurity correctly!")

def test_deduplicator():
    print("\n--- Testing Deduplicator Intra-batch & Canonical Hash ---")
    db = SessionLocal()
    dedup = Deduplicator()

    cand1 = {
        "question_text": "Who was the first Prime Minister of Australia?",
        "answer": "Sir Edmund Barton",
        "primary_topic": "Australian History & Culture"
    }
    cand2 = {
        "question_text": "Who was the FIRST prime minister of Australia???",
        "answer": "Sir Edmund Barton!",
        "primary_topic": "Australian History & Culture"
    }

    hash1 = dedup.compute_hash(cand1["question_text"], cand1["answer"])
    hash2 = dedup.compute_hash(cand2["question_text"], cand2["answer"])
    assert hash1 == hash2, "Canonical normalization failed to produce matching hash"

    unique, duplicates = dedup.deduplicate_batch(
        db=db,
        candidates=[cand1, cand2],
        candidate_embeddings=[],
        doc_id="test-batch-doc"
    )
    print(f"Unique candidates: {len(unique)}, Duplicates: {len(duplicates)}")
    assert len(unique) == 1, f"Expected 1 unique item, got {len(unique)}"
    assert len(duplicates) == 1, f"Expected 1 duplicate item, got {len(duplicates)}"
    print("[PASS] Deduplicator caught duplicate via canonical normalization!")

def test_topics_api():
    print("\n--- Testing Vault Topics API ---")
    db = SessionLocal()
    topics = list_vault_topics(db)
    print(f"Vault topics list: {topics}")
    assert len(topics) > 0, "No topics returned from vault"

    top_topic = topics[0]["topic"]
    summary = get_topic_summary(top_topic, db)
    print(f"Topic Summary for '{top_topic}':")
    print(f"  Total questions: {summary['total_questions']}")
    print(f"  Difficulty breakdown: {summary['difficulty_breakdown']}")
    print(f"  Subtopics: {summary['subtopics']}")
    print(f"  Grade range: {summary['grade_min']}-{summary['grade_max']}")
    assert summary["total_questions"] > 0
    print("[PASS] Vault Topics API works accurately!")

def test_pptx_export():
    print("\n--- Testing QShala Branded PPTX Export ---")
    db = SessionLocal()
    quiz = db.query(Quiz).first()
    assert quiz is not None, "No quiz found in database"

    pptx_bytes = QuizExporter.to_pptx(quiz)
    print(f"Generated PPTX size: {len(pptx_bytes)} bytes")
    assert len(pptx_bytes) > 5000, "PPTX file appears too small or corrupt"
    print("[PASS] QShala Branded PPTX export generated successfully!")

if __name__ == "__main__":
    print("=== RUNNING VAULT & COMPILATION TEST SUITE ===")
    test_auto_tagger()
    test_difficulty_engine()
    test_deduplicator()
    test_topics_api()
    test_pptx_export()
    print("\n=== ALL TEST SUITE CHECKS COMPLETED AND VERIFIED! ===")
