import csv
import json
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent
GOLD_CSV = ROOT / "backend" / "eval_data" / "gold_labels_145.csv"
TAXONOMY_JSON = ROOT / "backend" / "app" / "services" / "tagging" / "qshala_taxonomy_v4.json"
RUN2_CSV = ROOT / "docs" / "baselines" / "run2_flash_lite" / "per_question.csv"
OUT_MD = ROOT / "docs" / "dev_diagnostics.md"

def run_diagnostics():
    with open(TAXONOMY_JSON, encoding="utf-8") as f:
        tax_data = json.load(f)
    l2_to_l1 = {}
    for grp in tax_data["level1"]:
        for sub in grp["level2"]:
            l2_to_l1[sub["name"]] = grp["name"]

    with open(GOLD_CSV, encoding="utf-8-sig") as f:
        gold_rows = {r["id"]: r for r in csv.DictReader(f)}

    with open(RUN2_CSV, encoding="utf-8-sig") as f:
        run2_rows = list(csv.DictReader(f))

    # Evaluate each row
    confusions = Counter()
    domain_stats = defaultdict(lambda: {"total": 0, "l1_correct": 0, "l2_strict": 0, "l2_lenient": 0})
    l2_stats = defaultdict(lambda: {"total": 0, "strict": 0, "lenient": 0})
    fit_stats = defaultdict(lambda: {"total": 0, "lenient": 0, "confirmed": 0})
    errors_list = []

    entity_correct = 0
    geo_correct = 0
    shelf_correct = 0
    sens_correct = 0

    for r in run2_rows:
        qid = r["id"]
        g = gold_rows[qid]
        pred_l2 = r["pred_l2"]
        pred_l1 = l2_to_l1.get(pred_l2, "")
        gold_l2 = g["gold_l2"]
        gold_l1 = g["gold_l1"]
        accepted_l2 = {gold_l2} | {a.strip() for a in (g.get("alt_l2") or "").split("|") if a.strip()}

        l1_ok = pred_l1 == gold_l1
        l2_strict_ok = pred_l2 == gold_l2
        l2_lenient_ok = pred_l2 in accepted_l2

        # Confusion
        if not l2_lenient_ok:
            confusions[(gold_l2, pred_l2)] += 1
            errors_list.append({
                "id": qid,
                "gold_l1": gold_l1,
                "gold_l2": gold_l2,
                "pred_l1": pred_l1,
                "pred_l2": pred_l2,
                "alt_l2": g.get("alt_l2", ""),
                "fit": r["fit"],
                "status": r["status"],
                "q": g["question_text"][:90],
                "a": g["answer"][:40]
            })

        # By domain
        domain_stats[gold_l1]["total"] += 1
        if l1_ok: domain_stats[gold_l1]["l1_correct"] += 1
        if l2_strict_ok: domain_stats[gold_l1]["l2_strict"] += 1
        if l2_lenient_ok: domain_stats[gold_l1]["l2_lenient"] += 1

        # By subtopic
        l2_stats[gold_l2]["total"] += 1
        if l2_strict_ok: l2_stats[gold_l2]["strict"] += 1
        if l2_lenient_ok: l2_stats[gold_l2]["lenient"] += 1

        # Fit
        fit_val = r["fit"] or "none"
        fit_stats[fit_val]["total"] += 1
        if l2_lenient_ok: fit_stats[fit_val]["lenient"] += 1
        if r["status"] == "confirmed": fit_stats[fit_val]["confirmed"] += 1

        # Non-L2 fields
        if r["entity"] == "True": entity_correct += 1
        if r["geo"] == "True": geo_correct += 1
        if r["shelf"] == "True": shelf_correct += 1
        if r["sens"] == "True": sens_correct += 1

    total_n = len(run2_rows)

    lines = []
    lines.append("# Item-5 Dev-Set Diagnostics (Read-Only Analysis on 145 Questions)\n")
    lines.append(f"Evaluated Run 2 Flash-Lite on updated ground truth (N = {total_n}).\n")

    lines.append("## 1. Top Remaining Confusion Pairs (Gold L2 vs. Predicted L2)")
    lines.append("| Gold Subtopic | Predicted Subtopic | Count | Notes |")
    lines.append("|---|---|---|---|")
    for (gold_c, pred_c), cnt in confusions.most_common(10):
        lines.append(f"| {gold_c} | {pred_c} | {cnt} | Boundary ambiguity between {gold_c} and {pred_c} |")
    lines.append("")

    lines.append("## 2. Performance by Macro Domain (Level 1)")
    lines.append("| Domain (L1) | N | L1 Strict | L2 Strict | L2 Lenient |")
    lines.append("|---|---|---|---|---|")
    for d, s in sorted(domain_stats.items(), key=lambda x: -x[1]["total"]):
        l1_pct = 100.0 * s["l1_correct"] / s["total"]
        l2_s_pct = 100.0 * s["l2_strict"] / s["total"]
        l2_l_pct = 100.0 * s["l2_lenient"] / s["total"]
        lines.append(f"| {d} | {s['total']} | {l1_pct:.1f}% | {l2_s_pct:.1f}% | {l2_l_pct:.1f}% |")
    lines.append("")

    lines.append("## 3. Performance by Self-Rated Fit")
    lines.append("| Fit | N | L2 Lenient Accuracy | Auto-Confirmed % |")
    lines.append("|---|---|---|---|")
    for f_val in ["good", "weak", "none"]:
        s = fit_stats[f_val]
        if s["total"]:
            acc = 100.0 * s["lenient"] / s["total"]
            conf_pct = 100.0 * s["confirmed"] / s["total"]
            lines.append(f"| {f_val} | {s['total']} | {acc:.1f}% | {conf_pct:.1f}% |")
    lines.append("")

    lines.append("## 4. Non-L2 Metadata Accuracy")
    lines.append(f"- **Entity Type**: {100.0 * entity_correct / total_n:.1f}% ({entity_correct}/{total_n})")
    lines.append(f"- **Geography (India vs. International)**: {100.0 * geo_correct / total_n:.1f}% ({geo_correct}/{total_n})")
    lines.append(f"- **Shelf Life (Evergreen vs. Time-Sensitive)**: {100.0 * shelf_correct / total_n:.1f}% ({shelf_correct}/{total_n})")
    lines.append(f"- **Sensitivity**: {100.0 * sens_correct / total_n:.1f}% ({sens_correct}/{total_n})\n")

    lines.append("## 5. Complete Roster of Remaining Disagreements (Lenient Misses)")
    lines.append("| ID | Gold L2 | Pred L2 | Status | Fit | Question Snippet |")
    lines.append("|---|---|---|---|---|---|")
    for err in errors_list:
        lines.append(f"| {err['id']} | {err['gold_l2']} | {err['pred_l2']} | {err['status']} | {err['fit']} | {err['q']}... |")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Diagnostics written to {OUT_MD}")
    print(f"Total remaining lenient misses: {len(errors_list)} / {total_n}")

if __name__ == "__main__":
    run_diagnostics()
