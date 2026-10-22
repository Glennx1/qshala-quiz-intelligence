import csv
import json
import re
import random
from pathlib import Path
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent
GOLD_CSV = ROOT / "backend" / "eval_data" / "gold_labels_145.csv"
RESERVE_CSV = ROOT / "backend" / "eval_data" / "zvq_reserve_extracted.csv"
TAGGED_CSV = ROOT / "backend" / "eval_data" / "zvq_reserve_tagged.csv"
TAXONOMY_JSON = ROOT / "backend" / "app" / "services" / "tagging" / "qshala_taxonomy_v4.json"
OUT_CSV = ROOT / "backend" / "eval_data" / "test_blind_150.csv"

def is_image_dependent(q_text, ans_text):
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
    if len(q_text.strip().split()) <= 4 and ("identify" in full_text or "who" in full_text or "which" in full_text):
        return True
    return False

def clean_q_text(q):
    # Remove leading slide question numbers like "2. ", "16 . ", "10.* "
    q = re.sub(r'^\s*(\d+[\.\)\*\-]?|[a-zA-Z][\.\)])\s*', '', q).strip()
    return q

def build_stratified_150():
    # 1. Load Gold
    with open(GOLD_CSV, encoding="utf-8-sig") as f:
        gold_rows = list(csv.DictReader(f))
    gold_texts = [r["question_text"] for r in gold_rows]

    # Fit TF-IDF model on 145 gold for fallback prediction
    train_texts = [f"{r['question_text']} {r['answer']}" for r in gold_rows]
    tfidf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    X_gold = tfidf.fit_transform(train_texts)

    # 2. Load existing Tagged Reserve rows for high-quality Gemini predictions
    tagged_map = {}
    if TAGGED_CSV.exists():
        with open(TAGGED_CSV, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                key = clean_q_text(r["question_text"])[:60]
                tagged_map[key] = r["pred_l2"]

    # 3. Load Reserve questions
    with open(RESERVE_CSV, encoding="utf-8-sig") as f:
        reserve_rows = list(csv.DictReader(f))

    # Step 1: Filter out image-dependent
    candidates = []
    dropped_image_count = 0
    for r in reserve_rows:
        q_cleaned = clean_q_text(r["question_text"])
        r["question_text"] = q_cleaned
        if is_image_dependent(q_cleaned, r["answer"]):
            dropped_image_count += 1
        else:
            candidates.append(r)

    # Step 2: Dedupe against 145 gold questions
    survivors_gold = []
    dropped_gold_dups = 0
    for r in candidates:
        q = r["question_text"]
        max_score = max((fuzz.token_set_ratio(q, gq) for gq in gold_texts), default=0.0)
        if max_score > 90.0:
            dropped_gold_dups += 1
        else:
            survivors_gold.append(r)

    # Step 3: Dedupe against each other
    final_survivors = []
    dropped_intra_dups = 0
    for r in survivors_gold:
        q = r["question_text"]
        is_dup = any(fuzz.token_set_ratio(q, s["question_text"]) > 90.0 for s in final_survivors)
        if is_dup:
            dropped_intra_dups += 1
        else:
            final_survivors.append(r)

    print(f"Total reserve questions: {len(reserve_rows)}")
    print(f"Dropped image-dependent: {dropped_image_count}")
    print(f"Dropped duplicates against 145 gold: {dropped_gold_dups}")
    print(f"Dropped intra-reserve duplicates: {dropped_intra_dups}")
    print(f"Clean Unique Survivors: {len(final_survivors)}")

    # 4. Determine Stratification L2
    survivor_texts = [f"{r['question_text']} {r['answer']}" for r in final_survivors]
    X_survivors = tfidf.transform(survivor_texts)
    sims = cosine_similarity(X_survivors, X_gold)

    l2_buckets = {}
    for i, r in enumerate(final_survivors):
        key = r["question_text"][:60]
        if key in tagged_map and tagged_map[key]:
            pred_l2 = tagged_map[key]
        else:
            # Nearest neighbor from 145 gold
            best_gold_idx = int(sims[i].argmax())
            pred_l2 = gold_rows[best_gold_idx]["gold_l2"]
        r["_strat_l2"] = pred_l2
        l2_buckets.setdefault(pred_l2, []).append(r)

    print(f"\nUnique L2 subtopics represented in survivors: {len(l2_buckets)} / 38")

    # 5. Stratified Sampling of exactly 150 questions
    rng = random.Random(42)
    selected = []
    
    # First pass: For every L2 with >= 3 predictions, take min(3, len(bucket))
    for l2, bucket in sorted(l2_buckets.items()):
        rng.shuffle(bucket)
        take = min(len(bucket), 3) if len(bucket) >= 3 else 1
        selected.extend(bucket[:take])

    # Second pass: Proportional allocation for remaining slots
    chosen_ids = {id(x) for x in selected}
    remaining_pool = [x for bucket in l2_buckets.values() for x in bucket if id(x) not in chosen_ids]
    rng.shuffle(remaining_pool)
    
    needed = 150 - len(selected)
    selected.extend(remaining_pool[:needed])

    # Final shuffle
    rng.shuffle(selected)
    print(f"Total Stratified Sample Selected: {len(selected)}")

    # 6. Format and Write test_blind_150.csv
    # Schema requested by Claude:
    # id, question_text, answer, human_l1, human_l2, human_alt_l2, ambiguous, note, labeller, labelled_at
    rows_out = []
    strat_counts = {}
    for idx, r in enumerate(selected, 1):
        strat_l2 = r["_strat_l2"]
        strat_counts[strat_l2] = strat_counts.get(strat_l2, 0) + 1
        rows_out.append({
            "id": f"zvq-blind-{idx:03d}",
            "question_text": r["question_text"],
            "answer": r["answer"],
            "human_l1": "",
            "human_l2": "",
            "human_alt_l2": "",
            "ambiguous": "",
            "note": "",
            "labeller": "",
            "labelled_at": "",
        })

    fieldnames = ["id", "question_text", "answer", "human_l1", "human_l2", "human_alt_l2", "ambiguous", "note", "labeller", "labelled_at"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    print(f"Successfully wrote {len(rows_out)} rows to {OUT_CSV}")

    # Print stratification table
    print("\n--- Stratification Table (Predictions used ONLY to stratify, NOT written to CSV) ---")
    print(f"{'L2 Subtopic':<35} | {'Count in 150 Sample'}")
    print("-" * 55)
    for l2, count in sorted(strat_counts.items(), key=lambda x: -x[1]):
        print(f"{l2:<35} | {count}")

if __name__ == "__main__":
    build_stratified_150()
