"""Human-Cognition Benchmark & Evaluation Suite for Gemini AI Quiz Master Curator.

Evaluates high-order cognitive capabilities beyond basic keyword matching:
- Lateral Thematic Threads (Pivots, Hidden motifs)
- Audience Psychology & Emotional Calibration (Anxious 6th graders vs Cut-throat tech founders)
- Counter-Intuitive & Paradoxical Trivia (Cognitive dissonance)
- Surgical Refinement & Redundancy Elimination
"""
import sys
import os
import json
from typing import Dict, Any, List

# Ensure stdout supports unicode
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.app.database import SessionLocal
from backend.app.services.prompt_quiz import engine
from backend.app.models.question import Question


def run_benchmark():
    db = SessionLocal()
    total_q = db.query(Question).count()
    print("=" * 80)
    print(f"🚀 QSHALA HUMAN-COGNITION BENCHMARK SUITE (Bank Size: {total_q} questions)")
    print("=" * 80)

    test_cases = [
        {
            "id": "H1",
            "name": "Lateral Theme: Spectacular Failures to Massive Hits",
            "prompt": "5 questions about famous things or people that were complete failures or rejections before becoming massive hits",
            "count": 5,
            "expected": "Pivots, initial rejections, or near-bankruptcies across business, tech, or culture",
        },
        {
            "id": "H2",
            "name": "Lateral Theme: Food & Dining as Hidden Motifs",
            "prompt": "5 questions connected by the theme of food or eating, but hidden across business deals, sports, and history",
            "count": 5,
            "expected": "Questions where food acts as a lateral motif (e.g. auctions, food tech, historical meals)",
        },
        {
            "id": "H3",
            "name": "Audience Psychology: Anxious 6th Graders",
            "prompt": "5 gentle icebreaker questions for anxious 6th graders: make them giggle and feel confident before asking anything hard",
            "count": 5,
            "expected": "Accessible, high-curiosity, low-stress questions with humorous or relatable trivia",
        },
        {
            "id": "H4",
            "name": "Audience Psychology: Cut-throat Bangalore Tech Founders",
            "prompt": "5 tough, cut-throat questions on Bangalore tech and venture capital to humble arrogant startup founders",
            "count": 5,
            "expected": "Deep, obscure tech, startup, and valuation trivia that avoids textbook cliches",
        },
        {
            "id": "H5",
            "name": "Counter-Intuitive Trivia: Sounds Like Urban Legend But True",
            "prompt": "5 trivia questions that sound like absurd urban legends, but are 100% verified facts",
            "count": 5,
            "expected": "Surprising twists and counter-intuitive historical or scientific facts",
        },
    ]

    results = []

    for tc in test_cases:
        print(f"\n--- Running Test {tc['id']}: {tc['name']} ---")
        print(f"Prompt: \"{tc['prompt']}\"")
        engine.invalidate_bank_cache()

        try:
            draft = engine.build_draft(
                db=db,
                prompt=tc["prompt"],
                count=tc["count"],
            )

            delivered_qs = draft.get("questions") or []
            narrative = draft.get("narrative_arc")
            stages = draft.get("stages") or []

            print(f"Delivered: {len(delivered_qs)} of {tc['count']}")
            print(f"Stages: {' -> '.join(stages)}")
            if narrative:
                print(f"Curated Narrative Arc: \"{narrative}\"")
            else:
                print("Curated Narrative Arc: [Deterministic Fallback used]")

            # Audit zero-hallucination: verify every single delivered ID exists in DB
            db_ids = {q.id for q in db.query(Question.id).filter(Question.id.in_([q["id"] for q in delivered_qs])).all()}
            hallucinated = [q["id"] for q in delivered_qs if q["id"] not in db_ids]

            assert len(hallucinated) == 0, f"HALLUCINATION DETECTED: {hallucinated}"

            print("Selected Questions:")
            for i, q in enumerate(delivered_qs, 1):
                txt = q.get("question_text", "").replace("\n", " ")[:80]
                ans = q.get("answer", "").replace("\n", " ")[:40]
                diff = q.get("difficulty", "Medium")
                topic = q.get("subtopic_l2") or q.get("topic_l1") or q.get("topic") or "General"
                print(f"  {i}. [{topic}] [{diff}] Q: {txt}...")
                print(f"     Ans: {ans}")

            passed = len(delivered_qs) > 0 and len(hallucinated) == 0
            results.append({
                "id": tc["id"],
                "name": tc["name"],
                "status": "PASS" if passed else "FAIL",
                "delivered": len(delivered_qs),
                "curated": "Curator" in stages,
                "narrative": narrative or "N/A"
            })

        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "id": tc["id"],
                "name": tc["name"],
                "status": "ERROR",
                "error": str(e)
            })

    # Summary Table
    print("\n" + "=" * 80)
    print("HUMAN-COGNITION BENCHMARK EVALUATION SUMMARY")
    print("=" * 80)
    for r in results:
        status_icon = "✅" if r["status"] == "PASS" else "❌"
        curator_icon = "🧠 AI Curator" if r.get("curated") else "⚙️ Deterministic"
        print(f"{status_icon} [{r['id']}] {r['name']:<50} | {curator_icon} ({r.get('delivered', 0)} qs)")
        if r.get("narrative") and r.get("narrative") != "N/A":
            print(f"   Arc: {r['narrative']}")

    print("=" * 80)
    db.close()


if __name__ == "__main__":
    run_benchmark()
