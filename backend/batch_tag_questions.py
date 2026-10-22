"""Batch tag all questions in the QShala database using QshalaTagger v5.1.

Usage:
    python backend/batch_tag_questions.py --help
    python backend/batch_tag_questions.py --dry-run
    python backend/batch_tag_questions.py --api-key <PAID_GEMINI_KEY> --model gemini-3.5-flash-lite
    python backend/batch_tag_questions.py --import-real-set --sync-tags
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import pathlib
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.question import Question
from backend.app.models.qshala_tag import QshalaTag, QshalaQuestionMetadata
from backend.app.models.document import Document
from backend.app.services.tagging.qshala_tagger import QshalaTagger, set_taxonomy_version, _load_taxonomy
from backend.app.services.tagging import qshala_rules

logger = logging.getLogger("batch_tagger")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Flash-Lite pricing: $0.075 / 1M input, $0.30 / 1M output
COST_PER_M_IN = 0.075
COST_PER_M_OUT = 0.30
USD_TO_INR = 84.0


def import_322_real_set_into_db(session) -> int:
    """Import the 322 real ZVQ questions from combined_322_dataset.csv if not already present."""
    csv_path = HERE / "eval_data" / "combined_322_dataset.csv"
    if not csv_path.exists():
        logger.warning(f"File not found: {csv_path}")
        return 0

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    existing_ids = set(r[0] for r in session.query(Question.id).all())
    added = 0

    # Ensure placeholder document records exist for provenance
    decks = set(r["source_deck"] for r in rows)
    for deck in decks:
        doc = session.query(Document).filter(Document.id == deck).first()
        if not doc:
            doc = Document(
                id=deck,
                filename=f"{deck}.pptx",
                title=deck,
                file_type="pptx",
                storage_path=f"storage/uploads/{deck}.pptx",
                file_size_bytes=1000,
                processing_status="COMPLETED",
                question_count=0
            )
            session.add(doc)
    session.flush()

    for r in rows:
        qid = r["id"]
        if qid in existing_ids:
            continue

        q_obj = Question(
            id=qid,
            document_id=r.get("source_deck"),
            question_text=r.get("question_text", "").strip(),
            answer=r.get("answer", "").strip(),
            topic=r.get("l1_topic"),
            subtopic=r.get("l2_subtopic"),
            topics=[r.get("l1_topic")] if r.get("l1_topic") else [],
            difficulty="Medium",
            difficulty_score=0.5,
            duplicate_status="UNIQUE"
        )
        session.add(q_obj)
        added += 1

    session.commit()
    logger.info(f"Imported {added} new questions from combined_322_dataset.csv into questions table.")
    return added


def sync_existing_dataset_tags(session) -> int:
    """Seed or update QshalaTag rows from combined_322_dataset.csv and existing database labels."""
    csv_path = HERE / "eval_data" / "combined_322_dataset.csv"
    if not csv_path.exists():
        return 0

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        csv_rows = {r["id"]: r for r in reader}

    all_questions = session.query(Question).all()
    created = 0

    for q in all_questions:
        # Check if already has a tag
        existing_tag = session.query(QshalaTag).filter(QshalaTag.question_id == q.id).first()
        if existing_tag:
            continue

        r = csv_rows.get(q.id)
        if r:
            l1 = r.get("l1_topic")
            l2 = r.get("l2_subtopic")
            alt_l2 = [x.strip() for x in r.get("alt_l2", "").split("|") if x.strip()]
            entity_type = r.get("entity_type") or "TERM"
            india_intl = r.get("india_international") or "IN"
            shelf_life = r.get("shelf_life") or "EVERGREEN"
            sensitivity = r.get("sensitivity") or "NONE"
            notes = r.get("notes") or "pre-labelled real question"
        else:
            # Fall back to question fields + rules
            rules = qshala_rules.extract(q.question_text, q.answer)
            l1 = q.topic or (rules.brand_hints_l1[0] if rules.brand_hints_l1 else "Culture & Society")
            l2 = q.subtopic or "Heritage"
            alt_l2 = []
            entity_type = "TERM"
            india_intl = "IN"
            shelf_life = rules.shelf_life or "EVERGREEN"
            sensitivity = rules.sensitivity or "NONE"
            notes = "seeded from presentation extraction"

        # Generate rule keywords
        words = [w for w in q.question_text.split() if len(w) > 4 and w.isalnum()]
        keywords = ([q.answer] if q.answer else []) + words[:5]
        summary = f"{q.question_text[:80]}... Answer: {q.answer}" if len(q.question_text) > 80 else f"{q.question_text} Answer: {q.answer}"

        tag = QshalaTag(
            question_id=q.id,
            taxonomy_version="v5.1",
            model_version="dataset_seed_v5_1",
            source="HUMAN" if r else "RULE",
            topic_l1=l1,
            subtopic_l2=l2,
            keywords_l3=keywords[:7],
            secondary_l2=alt_l2[:3],
            entity_type=entity_type,
            india_international=india_intl,
            shelf_life=shelf_life,
            sensitivity=sensitivity,
            fit="good",
            search_summary=summary[:180],
            confidence=1.0 if r else 0.85,
            status="confirmed",
            verification_notes=notes,
            tokens_in=0,
            tokens_out=0,
            thinking_tokens=0,
            latency_ms=0,
        )
        session.add(tag)
        created += 1

    session.commit()
    logger.info(f"Seeded {created} QshalaTag rows in database.")
    return created


async def run_batch_tagging(
    api_key: Optional[str] = None,
    model: str = "gemini-3.5-flash-lite",
    limit: int = 0,
    throttle: float = 0.5,
    import_real_set: bool = True,
    dry_run: bool = False
):
    from backend.app.database import SessionLocal

    set_taxonomy_version("v5.1")
    tax_info = _load_taxonomy()
    logger.info(f"Loaded Taxonomy v5.1: {len(tax_info['l1'])} L1 domains, {len(tax_info['l2'])} L2 subtopics.")

    session = SessionLocal()

    if import_real_set:
        import_322_real_set_into_db(session)

    all_questions = session.query(Question).order_by(Question.created_at.asc()).all()
    if limit > 0:
        all_questions = all_questions[:limit]

    logger.info(f"Total questions to process: {len(all_questions)}")

    if dry_run or not api_key:
        if not api_key and not os.getenv("GEMINI_API_KEY"):
            logger.warning("No GEMINI_API_KEY provided. Seeding tags from dataset/rules and compiling distribution report.")
            sync_existing_dataset_tags(session)

    # If live tagging requested with API key
    effective_key = api_key or os.getenv("GEMINI_API_KEY")
    tagged_count = 0
    failed_count = 0
    total_in_tokens = 0
    total_out_tokens = 0
    total_think_tokens = 0

    if effective_key and not dry_run:
        os.environ["GEMINI_API_KEY"] = effective_key
        from backend.app.services.ai.gemini_provider import GeminiLLMProvider
        provider = GeminiLLMProvider(api_key=effective_key)
        tagger = QshalaTagger(provider=provider, model=model)

        for idx, q in enumerate(all_questions, 1):
            logger.info(f"[{idx}/{len(all_questions)}] Tagging {q.id}...")
            try:
                tag_row = await tagger.tag(
                    db=session,
                    question_id=q.id,
                    question_text=q.question_text,
                    answer=q.answer,
                    actor="batch_tagger",
                    commit=True
                )
                tagged_count += 1
                total_in_tokens += (tag_row.tokens_in or 0)
                total_out_tokens += (tag_row.tokens_out or 0)
                total_think_tokens += (tag_row.thinking_tokens or 0)
                if throttle > 0:
                    await asyncio.sleep(throttle)
            except Exception as e:
                logger.error(f"Failed to tag {q.id}: {e}")
                failed_count += 1
                if "429" in str(e) or "quota" in str(e).lower():
                    logger.error("Rate limit / quota hit! Stopping live calls.")
                    break

    # Compile distribution report from latest tags in DB
    from sqlalchemy import func
    latest_subq = (
        session.query(
            QshalaTag.question_id,
            func.max(QshalaTag.created_at).label("max_created_at")
        )
        .group_by(QshalaTag.question_id)
        .subquery()
    )

    latest_tags = (
        session.query(QshalaTag)
        .join(latest_subq, (QshalaTag.question_id == latest_subq.c.question_id) & (QshalaTag.created_at == latest_subq.c.max_created_at))
        .all()
    )

    total_tagged = len(latest_tags)
    cost_usd = (total_in_tokens / 1_000_000 * COST_PER_M_IN) + (total_out_tokens / 1_000_000 * COST_PER_M_OUT)
    cost_inr = cost_usd * USD_TO_INR

    # Distributions
    l2_dist = Counter(t.subtopic_l2 for t in latest_tags if t.subtopic_l2)
    l1_dist = Counter(t.topic_l1 for t in latest_tags if t.topic_l1)
    geo_dist = Counter(t.india_international for t in latest_tags if t.india_international)
    shelf_dist = Counter(t.shelf_life for t in latest_tags if t.shelf_life)
    sens_dist = Counter(t.sensitivity for t in latest_tags if t.sensitivity)

    print("\n" + "=" * 70)
    print("                QSHALA BATCH TAGGING REPORT (v5.1)")
    print("=" * 70)
    print(f"Total Questions in Vault:   {len(all_questions)}")
    print(f"Total Questions Tagged:     {total_tagged}")
    print(f"Tokens Used (Live Tagging): {total_in_tokens:,} in / {total_out_tokens:,} out")
    print(f"Estimated Cost:             ${cost_usd:.4f} USD (Rs. {cost_inr:.2f} INR)")
    print("-" * 70)
    print("DISTRIBUTION ACROSS 8 L1 DOMAINS:")
    for l1, cnt in l1_dist.most_common():
        pct = (cnt / total_tagged) * 100 if total_tagged else 0
        print(f"  {l1:<30} : {cnt:>4} ({pct:5.1f}%)")
    print("-" * 70)
    print("GEOGRAPHY DISTRIBUTION:")
    for geo, cnt in geo_dist.most_common():
        pct = (cnt / total_tagged) * 100 if total_tagged else 0
        print(f"  {geo:<30} : {cnt:>4} ({pct:5.1f}%)")
    print("-" * 70)
    print("SHELF LIFE DISTRIBUTION:")
    for sl, cnt in shelf_dist.most_common():
        pct = (cnt / total_tagged) * 100 if total_tagged else 0
        print(f"  {sl:<30} : {cnt:>4} ({pct:5.1f}%)")
    print("-" * 70)
    print("SENSITIVITY DISTRIBUTION:")
    for sens, cnt in sens_dist.most_common():
        pct = (cnt / total_tagged) * 100 if total_tagged else 0
        print(f"  {sens:<30} : {cnt:>4} ({pct:5.1f}%)")
    print("-" * 70)
    print(f"DISTRIBUTION ACROSS TOP L2 SUBTOPICS ({len(l2_dist)} of 78 represented):")
    for l2, cnt in l2_dist.most_common(20):
        pct = (cnt / total_tagged) * 100 if total_tagged else 0
        print(f"  {l2:<32} : {cnt:>4} ({pct:5.1f}%)")
    print("=" * 70 + "\n")

    session.close()


def main():
    parser = argparse.ArgumentParser(description="Batch tag real question set")
    parser.add_argument("--api-key", help="Gemini API Key (paid key)")
    parser.add_argument("--model", default="gemini-3.5-flash-lite", help="Gemini model")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of questions to process")
    parser.add_argument("--throttle", type=float, default=0.5, help="Sleep between API calls (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Sync tags without calling live LLM")
    parser.add_argument("--no-import", action="store_true", help="Do not import 322 real set")
    args = parser.parse_args()

    asyncio.run(
        run_batch_tagging(
            api_key=args.api_key,
            model=args.model,
            limit=args.limit,
            throttle=args.throttle,
            import_real_set=not args.no_import,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
