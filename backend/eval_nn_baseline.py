"""Leave-one-out Nearest Neighbor (TF-IDF) baseline for QShala 145 gold questions.

Replaces the zero-intelligence dumb baselines with a classic IR / machine learning baseline:
For each question i in the 145 dataset:
  1. Fit TF-IDF on all questions except i (or fit across corpus and mask diagonal i==i).
  2. Find question j (j != i) with the highest cosine similarity.
  3. Predict j's gold_l1 and gold_l2 as the tags for question i.
  4. Score L1 strict, L2 strict, and L2 lenient.
"""
import csv
import json
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

HERE = Path(__file__).resolve().parent
GOLD = HERE / "eval_data" / "gold_labels_145.csv"
OUT_JSON = HERE / "eval_data" / "dumb_baselines.json"

def run_nn_baseline():
    with open(GOLD, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    texts = [f"{r['question_text']} {r['answer']}" for r in rows]
    
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    X = vec.fit_transform(texts)
    
    # Cosine similarity matrix (145 x 145)
    sims = cosine_similarity(X, X)
    np.fill_diagonal(sims, -1.0)  # Exclude self (leave-one-out)
    
    results = []
    for i, row in enumerate(rows):
        nn_idx = int(np.argmax(sims[i]))
        nn_row = rows[nn_idx]
        sim_score = float(sims[i, nn_idx])
        
        pred_l1 = nn_row["gold_l1"]
        pred_l2 = nn_row["gold_l2"]
        
        accepted_l2 = {row["gold_l2"]} | {a.strip() for a in row.get("alt_l2", "").split("|") if a.strip()}
        
        l1_match = pred_l1 == row["gold_l1"]
        l2_strict = pred_l2 == row["gold_l2"]
        l2_lenient = pred_l2 in accepted_l2
        
        results.append({
            "id": row["id"],
            "verified": row["id"].startswith("zvq-blr-"),
            "gold_l1": row["gold_l1"],
            "gold_l2": row["gold_l2"],
            "nn_id": nn_row["id"],
            "nn_sim": sim_score,
            "pred_l1": pred_l1,
            "pred_l2": pred_l2,
            "l1_strict": l1_match,
            "l2_strict": l2_strict,
            "l2_lenient": l2_lenient
        })
        
    def summarize(subset, name):
        n = len(subset)
        if n == 0: return {}
        l1 = sum(1 for r in subset if r["l1_strict"]) / n * 100
        l2_s = sum(1 for r in subset if r["l2_strict"]) / n * 100
        l2_l = sum(1 for r in subset if r["l2_lenient"]) / n * 100
        return {
            "name": name,
            "n": n,
            "l1_strict": round(l1, 2),
            "l2_strict": round(l2_s, 2),
            "l2_lenient": round(l2_l, 2),
            "l1_correct": sum(1 for r in subset if r["l1_strict"]),
            "l2_strict_correct": sum(1 for r in subset if r["l2_strict"]),
            "l2_lenient_correct": sum(1 for r in subset if r["l2_lenient"]),
        }
        
    all_summary = summarize(results, "ALL (145)")
    ver_summary = summarize([r for r in results if r["verified"]], "VERIFIED (20)")
    silver_summary = summarize([r for r in results if not r["verified"]], "SILVER (125)")
    
    print("=" * 60)
    print("LEAVE-ONE-OUT TF-IDF NEAREST-NEIGHBOR BASELINE")
    print("=" * 60)
    print(f"ALL (145):     L1 Strict: {all_summary['l1_strict']}%  |  L2 Strict: {all_summary['l2_strict']}%  |  L2 Lenient: {all_summary['l2_lenient']}%")
    print(f"VERIFIED (20): L1 Strict: {ver_summary['l1_strict']}%  |  L2 Strict: {ver_summary['l2_strict']}%  |  L2 Lenient: {ver_summary['l2_lenient']}%")
    print(f"SILVER (125):  L1 Strict: {silver_summary['l1_strict']}%  |  L2 Strict: {silver_summary['l2_strict']}%  |  L2 Lenient: {silver_summary['l2_lenient']}%")
    print("=" * 60)
    
    # Load existing dumb baselines and update with NN baseline
    data = {}
    if OUT_JSON.exists():
        try:
            data = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
            
    data["tfidf_nearest_neighbour_leave_one_out"] = {
        "description": "Leave-one-out TF-IDF (1,2-grams) cosine similarity on question_text + answer",
        "all_145": all_summary,
        "verified_20": ver_summary,
        "silver_125": silver_summary
    }
    
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Updated baseline numbers saved to {OUT_JSON}")

if __name__ == "__main__":
    run_nn_baseline()
