import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GOLD_CSV = ROOT / "backend" / "eval_data" / "gold_labels_145.csv"
TAXONOMY_JSON = ROOT / "backend" / "app" / "services" / "tagging" / "qshala_taxonomy_v4.json"

RUN1_CSV = ROOT / "docs" / "baselines" / "run1_flash_lite" / "per_question.csv"
RUN2_CSV = ROOT / "docs" / "baselines" / "run2_flash_lite" / "per_question.csv"

def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + (z**2) / n
    center = p + (z**2) / (2 * n)
    spread = z * math.sqrt((p * (1 - p) / n) + (z**2) / (4 * (n**2)))
    return max(0.0, (center - spread) / denom) * 100

def load_data():
    with open(TAXONOMY_JSON, encoding="utf-8") as f:
        tax_data = json.load(f)
    l2_to_l1 = {}
    for grp in tax_data["level1"]:
        for sub in grp["level2"]:
            l2_to_l1[sub["name"]] = grp["name"]

    with open(GOLD_CSV, encoding="utf-8-sig") as f:
        gold = {r["id"]: r for r in csv.DictReader(f)}

    return l2_to_l1, gold

def rescore_run(run_csv_path, l2_to_l1, gold_map):
    with open(run_csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    rescored = []
    for r in rows:
        qid = r["id"]
        g = gold_map[qid]
        accepted = {g["gold_l2"]} | {a.strip() for a in (g.get("alt_l2") or "").split("|") if a.strip()}
        pred_l2 = r["pred_l2"]
        valid = pred_l2 in l2_to_l1
        
        l2_strict = valid and (pred_l2 == g["gold_l2"])
        l2_lenient = valid and (pred_l2 in accepted)
        l1_strict = valid and (l2_to_l1.get(pred_l2) == g["gold_l1"])
        
        rescored.append({
            "id": qid,
            "verified": g["label_status"] == "VERIFIED",
            "image_hint": g.get("image_hint") == "Y",
            "ambiguous": g.get("ambiguous") == "Y",
            "status": r["status"],
            "pred_l2": pred_l2,
            "gold_l2": g["gold_l2"],
            "l1_strict": l1_strict,
            "l2_strict": l2_strict,
            "l2_lenient": l2_lenient,
        })
    return rescored

def calc_slice_metrics(rows):
    n = len(rows)
    if n == 0:
        return {}
    pct = lambda k: 100.0 * sum(1 for r in rows if r[k]) / n
    n_conf = sum(1 for r in rows if r["status"] == "confirmed")
    k_strict = sum(1 for r in rows if r["status"] == "confirmed" and r["l2_strict"])
    k_lenient = sum(1 for r in rows if r["status"] == "confirmed" and r["l2_lenient"])
    
    acc_conf_strict = (100.0 * k_strict / n_conf) if n_conf else 0.0
    acc_conf_lenient = (100.0 * k_lenient / n_conf) if n_conf else 0.0
    
    return {
        "n": n,
        "l1_strict": pct("l1_strict"),
        "l2_strict": pct("l2_strict"),
        "l2_lenient": pct("l2_lenient"),
        "n_confirmed": n_conf,
        "coverage": 100.0 * n_conf / n,
        "conf_strict": acc_conf_strict,
        "wilson_strict": wilson_lower(k_strict, n_conf),
        "conf_lenient": acc_conf_lenient,
        "wilson_lenient": wilson_lower(k_lenient, n_conf),
    }

def print_table(name, rows):
    all_m = calc_slice_metrics(rows)
    ver_m = calc_slice_metrics([r for r in rows if r["verified"]])
    text_m = calc_slice_metrics([r for r in rows if not r["image_hint"]])
    unamb_m = calc_slice_metrics([r for r in rows if not r["image_hint"] and not r["ambiguous"]])

    print(f"\n=== {name} ===")
    print(f"| Slice | N | L1 strict | L2 strict | L2 lenient | Confirmed Cov | Confirmed Strict (+Wilson) | Confirmed Lenient (+Wilson) |")
    print(f"|---|---|---|---|---|---|---|---|")
    for lbl, m in [("ALL (145)", all_m), ("VERIFIED (46)", ver_m), ("TEXT-TAGGABLE", text_m), ("UNAMBIGUOUS (Target)", unamb_m)]:
        if m:
            print(f"| {lbl} | {m['n']} | {m['l1_strict']:.1f}% | {m['l2_strict']:.1f}% | {m['l2_lenient']:.1f}% | {m['coverage']:.1f}% ({m['n_confirmed']}/{m['n']}) | {m['conf_strict']:.1f}% ({m['wilson_strict']:.1f}%) | {m['conf_lenient']:.1f}% ({m['wilson_lenient']:.1f}%) |")

if __name__ == "__main__":
    l2_to_l1, gold_map = load_data()
    r1 = rescore_run(RUN1_CSV, l2_to_l1, gold_map)
    r2 = rescore_run(RUN2_CSV, l2_to_l1, gold_map)
    print_table("RUN 1 (FLASH-LITE) - RESCORED ON CORRECTED GOLD", r1)
    print_table("RUN 2 (FLASH-LITE) - RESCORED ON CORRECTED GOLD", r2)
