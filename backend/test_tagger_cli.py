"""
Interactive QShala Tagging & Difficulty Test CLI
Usage:
  python backend/test_tagger_cli.py
Or:
  python backend/test_tagger_cli.py "Question text" "Answer text" "Optional explanation"
"""
import sys
import json
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.services.tagging.auto_tagger import AutoTagger
from backend.app.services.tagging.difficulty_engine import DifficultyEngine

def test_question(q_text: str, ans_text: str, exp_text: str = ""):
    tagger = AutoTagger()
    engine = DifficultyEngine()

    tags = tagger.tag_question(
        question_text=q_text,
        answer_text=ans_text,
        explanation=exp_text
    )

    diff = engine.evaluate(
        question_text=q_text,
        answer_text=ans_text,
        explanation=exp_text
    )

    print("\n" + "=" * 60)
    print("QUESTION :", q_text)
    print("ANSWER   :", ans_text)
    if exp_text:
        print("STORY    :", exp_text)
    print("-" * 60)
    print("PRIMARY TOPIC       :", tags["primary_topic"])
    print("ALL MATCHED TOPICS  :", ", ".join(tags["topics"]))
    print("EXTRACTED ENTITIES  :", tags["tags"])
    print("PEDAGOGICAL HOOK    :", tags["question_hook"])
    print("CURIOSITY SCORE     :", f"{tags['curiosity_score']} / 10")
    print("TEMPORAL NATURE     :", tags["temporal_nature"])
    print("-" * 60)
    print("DIFFICULTY CATEGORY :", diff["difficulty"])
    print("PDI SCORE           :", diff["difficulty_score"])
    print("COGNITIVE LEVEL     :", diff["cognitive_level"])
    print("GRADE BAND          :", f"Grades {diff['grade_min']}–{diff['grade_max']}")
    print("AUDIENCE            :", ", ".join(diff["audience_suitability"]))
    print("PDI BREAKDOWN       :", json.dumps(diff["breakdown"]))
    print("=" * 60 + "\n")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        q = sys.argv[1]
        a = sys.argv[2]
        e = sys.argv[3] if len(sys.argv) > 3 else ""
        test_question(q, a, e)
    else:
        # Run demo cases
        demo_cases = [
            (
                "Which flightless native Australian bird can sprint at speeds up to 50 km/h across the outback?",
                "Emu",
                "Emus are the second-tallest living birds in the world after the ostrich."
            ),
            (
                "Why did penicillin discovery revolutionize modern medicine in 1928?",
                "Alexander Fleming discovered it by accidental mold contamination in his Petri dish",
                "Fleming noticed a halo of inhibited bacterial growth around Penicillium notatum mold."
            ),
            (
                "What links the Mariana Trench in the Pacific Ocean to Mount Everest in the Himalayas?",
                "Tectonic plate boundaries and geological extremes",
                "Both representing the deepest oceanic depression and highest altitude point on Earth formed by plate tectonics."
            )
        ]
        for q, a, e in demo_cases:
            test_question(q, a, e)
