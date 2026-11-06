"""CLI script to heal specialized question formats in the database."""
import os
import sys
sys.path.insert(0, os.path.abspath("."))

from backend.app.database import SessionLocal
from backend.app.services.ingestion.heal_specialized import heal_specialized_questions

def main():
    print("Starting specialized question format heal...")
    db = SessionLocal()
    try:
        stats = heal_specialized_questions(db)
        print("Heal completed successfully!")
        print(f"Results:")
        print(f"  - Stepped Clue questions healed: {stats['stepped_healed']}")
        print(f"  - Connect 4 questions healed: {stats['connect4_healed']}")
        print(f"  - Reclassified to Arrange Order: {stats['reclassified_arrange']}")
        print(f"  - Reclassified to Visual Clue: {stats['reclassified_visual']}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
