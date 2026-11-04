"""
A/B check for the Gemini cost controls: does the capped image description tag the same as the old one?

For a random sample of real questions that have images, this script:
  1. describes each question's first image TWICE: the OLD way (open-ended prompt, no output cap, default
     reasoning) and the NEW way (GeminiLLMProvider.describe_image: ~70 words, capped, minimal reasoning);
  2. prints the token usage of both (input / output / thinking) so the saving is measured, not guessed;
  3. tags the same questions three times through the real batch-tagger prompt: with the old descriptions,
     again with the old descriptions (this is the model's own run-to-run noise), and with the new ones;
  4. reports how often the new run agrees with the old one (theme, subtopic, confirmed/draft) next to the
     noise floor. If new-vs-old agreement is about as high as old-vs-old, quality is unchanged.

It only READS the database and writes nothing. It makes real Gemini calls with your configured key, about
2 vision calls per sample question plus 3 tagging chunks; with the default sample of 20 that is a few rupees.

Run from the repo root with a valid GEMINI_API_KEY in your environment or .env:
    python -m scripts.ab_vision_cost --sample 20
"""
import argparse
import asyncio
import base64
import random
import statistics

import httpx
from sqlalchemy import text

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.services.ai.gemini_provider import GeminiLLMProvider, usage_snapshot
from backend.app.services.ingestion.vision_resize import shrink_for_vision
from backend.app.services.tagging import qshala_batch, qshala_rules
from backend.app.services.tagging.qshala_tagger import TAXONOMY_VERSION, _route, _system_prompt, _v6_paths

OLD_PROMPT = (
    "Analyze this quiz presentation image. "
    "1. Transcribe any text visible on the image accurately (OCR). "
    "2. Describe the key visual content (person, monument, diagram, flag, animal, historical event, etc.) "
    "and any visual clues relevant to a quiz question."
)


def load_sample(n: int, seed: int):
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "select id, question_text, answer, (question_images::json->>0) as url from questions "
            "where json_array_length(question_images::json) > 0 and question_text is not null and answer is not null"
        )).fetchall()
    finally:
        db.rollback()
        db.close()
    rows = [r for r in rows if r[3] and str(r[3]).startswith("http")]
    random.Random(seed).shuffle(rows)
    return rows[:n]


async def fetch_image(client: httpx.AsyncClient, url: str):
    r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; QShalaIngestion/1.0)"})
    r.raise_for_status()
    ext = url.rsplit(".", 1)[-1].lower()
    mime = "image/png" if ext == "png" else ("image/jpeg" if ext in ("jpg", "jpeg") else "image/webp")
    return shrink_for_vision(r.content, mime)


async def tag_all(provider, items, clues_key):
    """Tag every item through the real batch prompt (no DB writes). Returns {n: (theme, l2, status)}."""
    chunks = [items[i:i + qshala_batch.CHUNK_SIZE] for i in range(0, len(items), qshala_batch.CHUNK_SIZE)]
    schema, system = qshala_batch._batch_schema(), _system_prompt()
    out = {}
    for chunk in chunks:
        view = [{**it, "visual_clues": it[clues_key]} for it in chunk]
        prompt = qshala_batch._batch_user_prompt(view, [])
        data, _ = await provider.generate_json_schema(
            prompt=prompt, schema=schema, system_instruction=system,
            model=settings.QSHALA_TAGGER_MODEL, thinking_level="low", temperature=0.0)
        for r in data.get("results", []):
            n = int(r["n"])
            paths = _v6_paths(r)
            first = paths[0] if paths else {}
            it = next(x for x in chunk if x["n"] == n)
            status, _, _ = _route(it["rules"], {"fit": r.get("fit", "weak"),
                                                "india_international": r.get("india_international"),
                                                "subtopic_l2": first.get("l2")})
            out[n] = (first.get("l1"), first.get("l2"), status)
    return out


def agreement(a, b):
    keys = sorted(set(a) & set(b))
    if not keys:
        return (0, 0, 0, 0)
    return (len(keys),
            sum(a[k][0] == b[k][0] for k in keys),
            sum(a[k][1] == b[k][1] for k in keys),
            sum(a[k][2] == b[k][2] for k in keys))


async def main(sample: int, seed: int):
    provider = GeminiLLMProvider()
    if not provider.api_key:
        raise SystemExit("No GEMINI_API_KEY configured.")
    rows = load_sample(sample, seed)
    print(f"vision model: {provider.model} | tagger model: {settings.QSHALA_TAGGER_MODEL} | questions: {len(rows)}")

    items, old_u, new_u = [], {"in": 0, "out": 0, "think": 0}, {"in": 0, "out": 0, "think": 0}
    async with httpx.AsyncClient(timeout=60) as http:
        for idx, (qid, qtext, ans, url) in enumerate(rows):
            try:
                data, mime = await fetch_image(http, url)
                media = [{"mime_type": mime, "data": base64.b64encode(data).decode()}]
                old_txt, ou = await provider.generate_multimodal_ex(OLD_PROMPT, media, usage_label="vision_old")
                new_txt = await provider.describe_image(data, mime)
            except Exception as e:
                print(f"  skipped question {idx} ({type(e).__name__}: {str(e)[:120]})")
                continue
            for k in old_u:
                old_u[k] += ou.get(k, 0)
            items.append({"n": idx, "question_id": qid, "question_text": qtext.strip(), "answer": ans.strip(),
                          "old": old_txt.strip(), "new": new_txt.strip(),
                          "rules": qshala_rules.extract(qtext, ans, taxonomy_version=TAXONOMY_VERSION)})
    if not items:
        raise SystemExit("Nothing could be described (check the API key and network).")

    snap = usage_snapshot()
    nv = snap.get("vision", {})
    n = len(items)
    print(f"\n== image description, {n} images ==")
    print(f"OLD  avg tokens in/out/thinking: {old_u['in']/n:.0f} / {old_u['out']/n:.0f} / {old_u['think']/n:.0f}"
          f"   | avg chars {statistics.mean(len(i['old']) for i in items):.0f} (max {max(len(i['old']) for i in items)})")
    print(f"NEW  avg tokens in/out/thinking: {nv.get('in',0)/n:.0f} / {nv.get('out',0)/n:.0f} / {nv.get('think',0)/n:.0f}"
          f"   | avg chars {statistics.mean(len(i['new']) for i in items):.0f} (max {max(len(i['new']) for i in items)})")
    old_total = old_u["out"] + old_u["think"]
    new_total = nv.get("out", 0) + nv.get("think", 0)
    if old_total:
        print(f"output+thinking tokens: {old_total} -> {new_total}  ({100 * (1 - new_total / old_total):.0f}% fewer)")

    print("\n== tagging with old vs new descriptions ==")
    t_old = await tag_all(provider, items, "old")
    t_old2 = await tag_all(provider, items, "old")      # same input again: the model's own run-to-run noise
    t_new = await tag_all(provider, items, "new")
    for label, a, b in (("old vs old (noise floor)", t_old, t_old2), ("old vs NEW", t_old, t_new)):
        m, th, l2, st = agreement(a, b)
        print(f"{label:26s} n={m}: theme same {th}/{m}  subtopic same {l2}/{m}  confirmed/draft same {st}/{m}")

    print("\nQuestions where NEW differs from OLD:")
    shown = 0
    for it in items:
        k = it["n"]
        if k in t_old and k in t_new and t_old[k][:2] != t_new[k][:2]:
            shown += 1
            print(f"- {it['question_text'][:90]!r}\n    old: {t_old[k]}\n    new: {t_new[k]}")
    if not shown:
        print("- none")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    asyncio.run(main(args.sample, args.seed))
