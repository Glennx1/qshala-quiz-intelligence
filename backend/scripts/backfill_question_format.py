"""
One-time backfill: re-classify all existing questions with the new
multi-signal format classifier.

Usage:
    python backend/scripts/backfill_question_format.py

Prints a summary of how many questions were reclassified per format.
Does NOT re-tag topics — only sets question_format and format_data.
"""
import sys
from pathlib import Path

# Add root and backend to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

from backend.app.database import SessionLocal
from backend.app.models.question import Question
from backend.app.services.tagging.format_classifier import classify_and_extract, STANDARD_QA

def main():
    counts = {"STANDARD_QA": 0, "CONNECT_4": 0, "STEPPED_CLUE": 0, "ARRANGE_ORDER": 0}

    session = SessionLocal()
    try:
        questions = session.query(Question).all()
        print(f"Backfilling {len(questions)} questions...")

        for q in questions:
            # Check existing round info or deck round
            round_name = None
            if q.round_number:
                round_name = f"Round {q.round_number}"

            fmt, fdata = classify_and_extract(
                q.question_text or "",
                q.answer or "",
                question_images=q.question_images,
                answer_images=q.answer_images,
                round_name=round_name,
            )

            # Preserve pre-existing high-precision ARRANGE_ORDER / STEPPED_CLUE classifications
            if q.question_type == "ARRANGE_ORDER" and fmt == STANDARD_QA:
                fmt = "ARRANGE_ORDER"
            elif q.question_type == "STEPPED_CLUE" and fmt == STANDARD_QA:
                fmt = "STEPPED_CLUE"

            q.question_format = fmt
            if fdata is not None:
                q.format_data = fdata
            elif q.format_payload is not None:
                q.format_data = q.format_payload

            # Sync format_payload if missing
            if q.format_payload is None and q.format_data is not None:
                q.format_payload = q.format_data

            counts[fmt] = counts.get(fmt, 0) + 1

        session.commit()
    finally:
        session.close()

    print("\n=== Backfill Results ===")
    for fmt, count in sorted(counts.items()):
        if count > 0:
            print(f"  {fmt}: {count}")
    print(f"  Total: {sum(counts.values())}")

if __name__ == "__main__":
    main()
