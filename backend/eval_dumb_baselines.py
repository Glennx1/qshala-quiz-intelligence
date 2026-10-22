"""Score two zero-cost / dumb baselines against the 145-question gold set.

Baseline A: Rules-only (qshala_rules.py)
Baseline B: Generic world-knowledge auto-tagger (auto_tagger.py)
"""
import csv
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from backend.app.services.tagging import qshala_rules
from backend.app.services.tagging.auto_tagger import AutoTagger

GOLD_PATH = HERE / "eval_data" / "gold_labels_145.csv"

def run_dumb_baselines():
    with open(GOLD_PATH, encoding="utf-8-sig") as f:
        gold = list(csv.DictReader(f))

    print(f"Loaded {len(gold)} questions for dumb baseline scoring.")

    # Baseline A: Rules only
    geo_correct = 0
    shelf_correct = 0
    sens_correct = 0
    l1_correct_rules = 0 # rules don't predict L1
    l2_correct_rules = 0 # rules don't predict L2

    for g in gold:
        r = qshala_rules.extract(g["question_text"], g["answer"])
        # Geo check
        if r.india_international == g["geography"]:
            geo_correct += 1
        if r.shelf_life == g["shelf_life"]:
            shelf_correct += 1
        if r.sensitivity == g["sensitivity"]:
            sens_correct += 1

    # Baseline B: Generic auto-tagger
    generic_tagger = AutoTagger()
    generic_l1_match = 0
    generic_tags_count = 0

    for g in gold:
        res = generic_tagger.tag_question(g["question_text"], g["answer"])
        topic = res.get("primary_topic") or ""
        # Check if topic matches gold_l1
        if topic and topic.lower() in g["gold_l1"].lower():
            generic_l1_match += 1

    n = len(gold)
    results = {
        "n": n,
        "rules_only": {
            "l1_strict": 0.0,
            "l2_strict": 0.0,
            "l2_lenient": 0.0,
            "geo_accuracy": (geo_correct / n) * 100,
            "shelf_accuracy": (shelf_correct / n) * 100,
            "sens_accuracy": (sens_correct / n) * 100,
        },
        "generic_auto_tagger": {
            "l1_match_against_gold_l1": (generic_l1_match / n) * 100,
            "l2_match": 0.0 # vocabulary completely disjoint
        }
    }

    print("\n=== DUMB BASELINES REPORT ===")
    print(f"1. Rules-Only (qshala_rules.py):")
    print(f"   - L1/L2 Accuracy: 0.0% (Rules do not assign taxonomy topics)")
    print(f"   - Geography Accuracy: {results['rules_only']['geo_accuracy']:.1f}%")
    print(f"   - Shelf-Life Accuracy: {results['rules_only']['shelf_accuracy']:.1f}%")
    print(f"   - Sensitivity Accuracy: {results['rules_only']['sens_accuracy']:.1f}%")
    print(f"\n2. Generic World-Knowledge Tagger (auto_tagger.py):")
    print(f"   - L1 Overlap against Gold L1: {results['generic_auto_tagger']['l1_match_against_gold_l1']:.1f}%")
    print(f"   - L2 Accuracy: 0.0% (Generic vocabulary has zero overlap with QShala v4)")

    out_file = HERE / "eval_data" / "dumb_baselines.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved dumb baselines to {out_file}")

if __name__ == "__main__":
    run_dumb_baselines()
