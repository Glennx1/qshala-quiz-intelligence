import csv
import re
from pathlib import Path
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent
GOLD_CSV = ROOT / "backend" / "eval_data" / "gold_labels_145.csv"
RESERVE_CSV = ROOT / "backend" / "eval_data" / "zvq_reserve_extracted.csv"
TAGGED_CSV = ROOT / "backend" / "eval_data" / "zvq_reserve_tagged.csv"

def is_image_dependent(q_text, ans_text):
    # Regex to catch visual-dependent clues
    visual_patterns = [
        r"\b(in the (picture|image|photo)|seen (here|in the image|in the picture)|on the screen)\b",
        r"\bthis (photo|image|picture|logo|building|advertisement|ad|cartoon|chart|graph|collection|tribute|monument|painting)\b",
        r"\b(who is this|whose logo|which logo|identify the (person|brand|logo|building|monument))\b",
        r"\b(pictured here|shown here|depicted here|in this image|in this photo|in this visual)\b",
        r"\b(which product is blurred|what is blanked out|fill in the blank from the logo)\b"
    ]
    full_text = f"{q_text} {ans_text}".lower()
    for pat in visual_patterns:
        if re.search(pat, full_text, re.IGNORECASE):
            return True
    # If question text is extremely short and has no subject, e.g. "Identify." or "Who?"
    if len(q_text.strip().split()) <= 4 and ("identify" in full_text or "who" in full_text or "which" in full_text):
        return True
    return False

def run_dedupe():
    with open(GOLD_CSV, encoding="utf-8-sig") as f:
        gold_rows = list(csv.DictReader(f))
    gold_texts = [f"{r['question_text']}" for r in gold_rows]

    with open(RESERVE_CSV, encoding="utf-8-sig") as f:
        reserve_rows = list(csv.DictReader(f))

    print(f"Total reserve questions extracted: {len(reserve_rows)}")

    # Step 1: Filter out image-dependent
    text_taggable = []
    dropped_image = []
    for r in reserve_rows:
        q = r["question_text"]
        a = r["answer"]
        if is_image_dependent(q, a):
            dropped_image.append(r)
        else:
            text_taggable.append(r)

    print(f"Dropped image-dependent questions: {len(dropped_image)}")
    print(f"Text-taggable candidate questions: {len(text_taggable)}")

    # Step 2: Dedupe against 145 gold questions (token_set_ratio > 90)
    survivors_gold = []
    dropped_gold_dups = []
    for r in text_taggable:
        q = r["question_text"]
        max_score = 0.0
        best_match = ""
        for gq in gold_texts:
            score = fuzz.token_set_ratio(q, gq)
            if score > max_score:
                max_score = score
                best_match = gq
        if max_score > 90.0:
            dropped_gold_dups.append((r, max_score, best_match))
        else:
            survivors_gold.append(r)

    print(f"Dropped duplicates against 145 gold (score > 90): {len(dropped_gold_dups)}")
    print(f"Survivors after gold dedupe: {len(survivors_gold)}")

    # Step 3: Dedupe against each other (intra-reserve deduplication)
    final_survivors = []
    dropped_intra_dups = []
    for r in survivors_gold:
        q = r["question_text"]
        is_dup = False
        for s in final_survivors:
            sq = s["question_text"]
            score = fuzz.token_set_ratio(q, sq)
            if score > 90.0:
                dropped_intra_dups.append((r, score, sq))
                is_dup = True
                break
        if not is_dup:
            final_survivors.append(r)

    print(f"Dropped intra-reserve duplicates (score > 90): {len(dropped_intra_dups)}")
    print(f"FINAL CLEAN UNIQUE NON-IMAGE SURVIVORS: {len(final_survivors)}")

if __name__ == "__main__":
    run_dedupe()
