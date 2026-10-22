"""Score the QShala tagger against the 145-question gold set.

Reads   backend/eval_data/gold_labels_145.csv
Writes  backend/eval_data/results/eval_<timestamp>/report.md + per_question.csv + raw.jsonl

Runs the *real backend tagger* (QshalaTagger) directly, no mocks. The eval exercises
exactly the code that will run in production: rules → Gemini → routing → DB row.
It uses a temporary SQLite file so your dev/prod DB is never touched.

Usage from the repo root:
    python backend/eval_qshala_tagger.py --limit 10        # smoke test (~free on free tier)
    python backend/eval_qshala_tagger.py                   # full 145
    python backend/eval_qshala_tagger.py --throttle 1.0    # 1 req/s if you hit free-tier limits

Reads GEMINI_API_KEY from env. The 20 verified Bangalore-prelim questions and the
125 silver questions are reported separately so you can see where the real signal is.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import logging
import os
import pathlib
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

# Keep the backend package resolvable from any CWD.
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models.question import Question
from backend.app.models.document import Document, Slide  # noqa: F401  (resolve FKs)
from backend.app.models.qshala_tag import QshalaQuestionMetadata, QshalaTag, QshalaTagChange  # noqa: F401
from backend.app.services.tagging.qshala_tagger import QshalaTagger, _load_taxonomy, set_taxonomy_version

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("eval")

GOLD = HERE / "eval_data" / "gold_labels_145.csv"
VERIFIED_PREFIX = "zvq-blr-"   # 20 Bangalore-prelim questions reviewed by a human; the rest are silver.


# ---------------------------------------------------------------------- data loading

def load_gold() -> List[Dict[str, Any]]:
    with open(GOLD, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def is_verified(row: Dict[str, Any]) -> bool:
    return row["id"].startswith(VERIFIED_PREFIX)


# ---------------------------------------------------------------------- scoring

STOP_WORDS = {"they", "thus", "however", "the", "this", "that", "these", "those",
              "there", "their", "while", "unlike", "larger", "towns"}


def _norm(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


import math
from collections import Counter

def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """Wilson 95% confidence interval lower bound for k successes in n trials."""
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + (z**2) / n
    center = p + (z**2) / (2 * n)
    spread = z * math.sqrt((p * (1 - p) / n) + (z**2) / (4 * (n**2)))
    return max(0.0, (center - spread) / denom) * 100


def score(pred: QshalaTag, gold: Dict[str, Any]) -> Dict[str, Any]:
    tax = _load_taxonomy()
    accepted = {gold["gold_l2"]} | {a for a in gold["alt_l2"].split("|") if a}
    l2 = pred.subtopic_l2 or ""
    valid = l2 in tax["l2_to_l1"]
    l2_strict = valid and l2 == gold["gold_l2"]
    l2_lenient = valid and l2 in accepted
    l1_strict = valid and tax["l2_to_l1"][l2] == gold["gold_l1"]
    kws = pred.keywords_l3 or []
    kw_ok_format = isinstance(kws, list) and 4 <= len(kws) <= 7 and not any(_norm(k) in STOP_WORDS for k in kws)
    import re
    ans_first = re.split(r"/|\bor\b", gold["answer"])[0]
    ans_tokens = [t for t in _norm(ans_first).split() if len(t) >= 3]
    joined = _norm(" ".join(kws))
    kw_covers_answer = bool(ans_tokens) and all(t in joined for t in ans_tokens[:3])
    return {
        "id": gold["id"], "verified": is_verified(gold),
        "image_hint": gold.get("image_hint") == "Y",
        "ambiguous": gold.get("ambiguous") == "Y",
        "pred_l2": l2, "gold_l2": gold["gold_l2"],
        "l1_strict": l1_strict, "l2_strict": l2_strict, "l2_lenient": l2_lenient,
        "entity": pred.entity_type == gold["entity_type"],
        "geo": pred.india_international == gold["geography"],
        "shelf": pred.shelf_life == gold["shelf_life"],
        "sens": pred.sensitivity == gold["sensitivity"],
        "kw_format": kw_ok_format, "kw_answer": kw_covers_answer,
        "secondary_l2": "|".join(pred.secondary_l2 or []),
        "fit": pred.fit, "status": pred.status, "confidence": pred.confidence or 0.0,
        "tokens_in": pred.tokens_in or 0, "tokens_out": pred.tokens_out or 0,
        "thinking": pred.thinking_tokens or 0, "latency_ms": pred.latency_ms or 0,
    }


def summarise(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    if not rows:
        return {"label": label, "n": 0}
    pct = lambda k: 100 * sum(1 for r in rows if r.get(k)) / len(rows)
    lats = sorted(r["latency_ms"] for r in rows if r["latency_ms"]) or [0]
    
    n_conf = sum(1 for r in rows if r["status"] == "confirmed")
    k_strict = sum(1 for r in rows if r["status"] == "confirmed" and r["l2_strict"])
    k_lenient = sum(1 for r in rows if r["status"] == "confirmed" and r["l2_lenient"])
    
    acc_conf_strict = (100 * k_strict / n_conf) if n_conf else 0.0
    acc_conf_lenient = (100 * k_lenient / n_conf) if n_conf else 0.0
    wilson_conf_strict = wilson_lower(k_strict, n_conf)
    wilson_conf_lenient = wilson_lower(k_lenient, n_conf)

    return {
        "label": label, "n": len(rows),
        "l1_strict": pct("l1_strict"), "l2_strict": pct("l2_strict"), "l2_lenient": pct("l2_lenient"),
        "entity": pct("entity"), "geo": pct("geo"), "shelf": pct("shelf"), "sens": pct("sens"),
        "kw_format": pct("kw_format"), "kw_answer": pct("kw_answer"),
        "auto_confirmed_pct": 100 * n_conf / len(rows),
        "n_confirmed": n_conf,
        "acc_when_confirmed": acc_conf_strict,
        "acc_when_confirmed_lenient": acc_conf_lenient,
        "wilson_conf_strict": wilson_conf_strict,
        "wilson_conf_lenient": wilson_conf_lenient,
        "tokens_in_avg": statistics.mean(r["tokens_in"] for r in rows),
        "tokens_out_avg": statistics.mean(r["tokens_out"] for r in rows),
        "thinking_avg": statistics.mean(r["thinking"] for r in rows),
        "latency_p50_ms": statistics.median(lats),
        "latency_p95_ms": lats[int(0.95 * (len(lats) - 1))],
    }


# ---------------------------------------------------------------------- runner

async def run(limit: int, throttle: float, model: Optional[str], thinking: Optional[str] = None) -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set GEMINI_API_KEY in your environment first.")

    gold = load_gold()
    if limit:
        gold = gold[:limit]

    # Isolated SQLite file so this never touches the real DB.
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Seed a dummy document and one Question row per gold item.
    doc = Document(filename="eval.pptx", title="Eval Set", file_type="pptx",
                   storage_path=db_file, slide_count=len(gold), question_count=len(gold))
    db.add(doc)
    db.flush()
    for g in gold:
        db.add(Question(
            id=g["id"], document_id=doc.id, question_text=g["question_text"],
            answer=g["answer"], topic=g["gold_l1"], subtopic=g["gold_l2"],
        ))
    db.commit()

    tagger = QshalaTagger(model=model, thinking_level=thinking)
    print(f"Tagging {len(gold)} questions through {tagger.model}  thinking={tagger.thinking_level}  (sqlite: {db_file})")
    scores: List[Dict[str, Any]] = []
    raw_lines: List[str] = []

    for i, g in enumerate(gold, 1):
        for retry in range(4):
            try:
                t0 = time.perf_counter()
                row = await tagger.tag(db, question_id=g["id"], question_text=g["question_text"],
                                       answer=g["answer"], actor="eval", commit=True)
                s = score(row, g)
                scores.append(s)
                raw_lines.append(json.dumps({"gold": g, "pred": {
                    "l2": row.subtopic_l2, "l1": row.topic_l1, "keywords": row.keywords_l3,
                    "secondary_l2": row.secondary_l2 or [],
                    "entity": row.entity_type, "geo": row.india_international, "shelf": row.shelf_life,
                    "sens": row.sensitivity, "fit": row.fit, "summary": row.search_summary,
                    "status": row.status, "confidence": row.confidence, "notes": row.verification_notes,
                }}, ensure_ascii=False))
                status_sym = "[OK]" if s['l2_strict'] else "[X]"
                print(f"  [{i:3}/{len(gold)}] {g['id']:<16}  gold={g['gold_l2']:<35}  pred={row.subtopic_l2:<35}  "
                      f"{status_sym} ({row.status}, {time.perf_counter() - t0:.1f}s)", flush=True)
                break
            except Exception as e:
                err_str = str(e)
                if any(k in err_str for k in ("429", "503", "Resource", "quota", "rate")) and retry < 3:
                    wait_s = 4.0 * (retry + 1)
                    print(f"  [{i:3}/{len(gold)}] {g['id']}  RATE LIMITED (429/503), retrying in {wait_s}s...", flush=True)
                    await asyncio.sleep(wait_s)
                    continue
                print(f"  [{i:3}/{len(gold)}] {g['id']}  FAILED: {e}", flush=True)
                raw_lines.append(json.dumps({"gold": g, "error": str(e)}, ensure_ascii=False))
                break

        if throttle:
            await asyncio.sleep(throttle)

    # ---- write results.
    outdir = HERE / "eval_data" / "results" / f"eval_{dt.datetime.now():%Y%m%d_%H%M%S}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "raw.jsonl").write_text("\n".join(raw_lines), encoding="utf-8")

    with open(outdir / "per_question.csv", "w", newline="", encoding="utf-8-sig") as f:
        if scores:
            w = csv.DictWriter(f, fieldnames=list(scores[0].keys()))
            w.writeheader()
            w.writerows(scores)

    verified = [s for s in scores if s["verified"]]
    silver = [s for s in scores if not s["verified"]]
    text_only = [s for s in scores if not s["image_hint"]]
    image_dep = [s for s in scores if s["image_hint"]]
    unambig_text = [s for s in scores if not s["image_hint"] and not s["ambiguous"]]

    summaries = [
        summarise(scores, "ALL (145)"),
        summarise(verified, "VERIFIED (20 BLR)"),
        summarise(silver, "SILVER (125)"),
        summarise(text_only, "TEXT-TAGGABLE (Non-Image)"),
        summarise(image_dep, "IMAGE-DEPENDENT"),
        summarise(unambig_text, "UNAMBIGUOUS NON-IMAGE (95% Target)")
    ]

    # ---- report.md.
    def fmt(x: Any) -> str:
        return f"{x:.1f}" if isinstance(x, (int, float)) else str(x)

    lines: List[str] = []
    lines.append(f"# QShala tagger evaluation — {tagger.model}")
    lines.append("")
    lines.append(f"Run: {dt.datetime.now():%Y-%m-%d %H:%M}  |  N: {len(scores)}  |  throttle: {throttle}s/req")
    lines.append("")
    lines.append("The **VERIFIED** row (20 Bangalore prelims reviewed by a quizmaster) is the real signal. "
                 "The **SILVER** row (125 vault questions with my own first-pass labels) is directional only.")
    lines.append("")
    lines.append("## Accuracy")
    lines.append("| Slice | N | L1 strict | L2 strict | L2 lenient | Entity | Geo | Shelf | Sens | KW format | Answer in KW |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in summaries:
        if s["n"]:
            lines.append(f"| {s['label']} | {s['n']} | {fmt(s['l1_strict'])} | {fmt(s['l2_strict'])} | "
                         f"{fmt(s['l2_lenient'])} | {fmt(s['entity'])} | {fmt(s['geo'])} | "
                         f"{fmt(s['shelf'])} | {fmt(s['sens'])} | {fmt(s['kw_format'])} | {fmt(s['kw_answer'])} |")
    lines.append("")
    lines.append("## Routing & Confirmed Precision (Target: >=95% on Unambiguous Non-Image)")
    lines.append("| Slice | Coverage (Confirmed %) | Confirmed Count | L2 Strict on Confirmed | Wilson 95% LB (Strict) | L2 Lenient on Confirmed | Wilson 95% LB (Lenient) |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in summaries:
        if s["n"]:
            lines.append(f"| {s['label']} | {fmt(s['auto_confirmed_pct'])}% | {s['n_confirmed']}/{s['n']} | "
                         f"{fmt(s['acc_when_confirmed'])}% | **{fmt(s['wilson_conf_strict'])}%** | "
                         f"{fmt(s['acc_when_confirmed_lenient'])}% | **{fmt(s['wilson_conf_lenient'])}%** |")
    lines.append("")
    lines.append("Auto-confirmed is what the system will treat as settled without review. "
                 "Wilson 95% LB is the conservative statistical lower bound on precision.")
    lines.append("")
    lines.append("## Accuracy by Model Fit")
    lines.append("| Fit | N | L1 strict | L2 strict | L2 lenient | Auto-confirmed % |")
    lines.append("|---|---|---|---|---|---|")
    for f_val in ["good", "weak", "none"]:
        subset = [s for s in scores if s.get("fit") == f_val]
        if subset:
            s_sum = summarise(subset, f_val)
            lines.append(f"| {f_val} | {len(subset)} | {fmt(s_sum['l1_strict'])}% | {fmt(s_sum['l2_strict'])}% | {fmt(s_sum['l2_lenient'])}% | {fmt(s_sum['auto_confirmed_pct'])}% |")
    lines.append("")
    lines.append("## Accuracy by Pipeline Status")
    lines.append("| Status | N | L1 strict | L2 strict | L2 lenient | Avg Confidence |")
    lines.append("|---|---|---|---|---|---|")
    for st_val in ["confirmed", "draft"]:
        subset = [s for s in scores if s.get("status") == st_val]
        if subset:
            s_sum = summarise(subset, st_val)
            avg_conf = statistics.mean(s["confidence"] for s in subset)
            lines.append(f"| {st_val} | {len(subset)} | {fmt(s_sum['l1_strict'])}% | {fmt(s_sum['l2_strict'])}% | {fmt(s_sum['l2_lenient'])}% | {avg_conf:.2f} |")
    lines.append("")
    lines.append("## Cost & Latency (USD & INR @ 87.0 INR/USD)")
    lines.append("| Slice | Avg in tok | Avg out tok | p50 latency (ms) | p95 latency (ms) | Cost / 1k (USD) | Cost / 1k (INR) |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in summaries:
        if s["n"]:
            # Rates: $0.075 / 1M in, $0.300 / 1M out for 3.5-flash-lite
            in_cost = (s['tokens_in_avg'] * 1000 / 1e6) * 0.075
            out_cost = (s['tokens_out_avg'] * 1000 / 1e6) * 0.300
            cost_1k_usd = in_cost + out_cost
            cost_1k_inr = cost_1k_usd * 87.0
            lines.append(f"| {s['label']} | {s['tokens_in_avg']:.0f} | {s['tokens_out_avg']:.0f} | "
                         f"{s['latency_p50_ms']:.0f} | {s['latency_p95_ms']:.0f} | ${cost_1k_usd:.4f} | ₹{cost_1k_inr:.2f} |")
    lines.append("")
    lines.append("## Top 15 Confusion Pairs (Gold L2 × Predicted L2)")
    conf_pairs = Counter((s["gold_l2"], s["pred_l2"]) for s in scores if s["gold_l2"] != s["pred_l2"])
    if not conf_pairs:
        lines.append("Zero confusion pairs.")
    else:
        lines.append("| Count | Gold L2 | Predicted L2 | Lenient Accepted? |")
        lines.append("|---|---|---|---|")
        for (g_l2, p_l2), cnt in conf_pairs.most_common(15):
            # Check if this prediction was accepted as lenient
            sample = next((s for s in scores if s["gold_l2"] == g_l2 and s["pred_l2"] == p_l2), None)
            lenient_str = "Yes (Alt)" if (sample and sample["l2_lenient"]) else "No (Mismatch)"
            lines.append(f"| {cnt} | {g_l2} | {p_l2} | {lenient_str} |")
    lines.append("")
    lines.append("## Every mistake, for human review")
    bad = [s for s in scores if not s["l2_lenient"]]
    if not bad:
        lines.append("None.")
    else:
        lines.append("| id | gold L2 | pred L2 | status | confidence |")
        lines.append("|---|---|---|---|---|")
        for s in bad[:60]:
            lines.append(f"| {s['id']} | {s['gold_l2']} | {s['pred_l2']} | {s['status']} | {s['confidence']:.2f} |")

    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {outdir / 'report.md'}")

    db.close()
    engine.dispose()
    try:
        os.unlink(db_file)
    except OSError:
        print(f"(Could not delete temp DB {db_file} — harmless on Windows, delete manually if you like.)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="Only tag the first N gold questions.")
    ap.add_argument("--throttle", type=float, default=0.0, help="Seconds to sleep between calls (1.0 is safe on free tier).")
    ap.add_argument("--model", default=None, help="Override QSHALA_TAGGER_MODEL for this run (e.g. gemini-2.5-flash).")
    ap.add_argument("--thinking", default=None, help="Thinking level: minimal, low, medium, high. Default: low (tagger default).")
    ap.add_argument("--taxonomy", choices=["v4", "v5"], default="v4", help="Taxonomy version: v4 or v5 (default: v4)")
    args = ap.parse_args()
    if args.taxonomy:
        set_taxonomy_version(args.taxonomy)
    asyncio.run(run(limit=args.limit, throttle=args.throttle, model=args.model, thinking=args.thinking))


if __name__ == "__main__":
    main()
