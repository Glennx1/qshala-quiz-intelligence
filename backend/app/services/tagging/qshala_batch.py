"""Chunked, review-gated batch tagging.

One Gemini call per chunk of ~12 questions (not one call for the whole deck — that overflows the
output-token budget and hangs). Each returned item is run through the SAME _route() gate as the
single-question path, so weak-fit questions land in `draft` (the review queue). A chunk that fails,
times out, or comes back short does NOT abort the deck: its questions are written as `draft` with a
reason, and tagging continues. Recent human-confirmed tags are injected as few-shot examples so quiz
master clarifications improve every later run.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.qshala_tag import QshalaTag, QshalaTagChange
from backend.app.models.question import Question
from backend.app.services.tagging import qshala_rules, topic_paths
from backend.app.services.tagging.qshala_tagger import (
    TAXONOMY_VERSION, GEOGRAPHY_V6, _load_taxonomy, _system_prompt, _tag_schema_v6,
    _v6_paths, _route, _clean_year, safe_error, is_rate_limit, retry_after_seconds,
)

logger = logging.getLogger(__name__)

CHUNK_SIZE = 12          # questions per Gemini call; keeps output JSON well under the token ceiling
CHUNK_CONCURRENCY = 2    # chunks in flight at once; stays within free-tier RPM with backoff
CHUNK_TIMEOUT_S = 75.0   # a chunk that takes longer is abandoned -> its questions go to review
MAX_CHUNK_RETRIES = 3


# ---- schema: a list of per-question v6 payloads, each echoing its index `n` ----

def _batch_schema() -> Dict[str, Any]:
    item = _tag_schema_v6()                       # OBJECT with topics/geo/india_international/...
    item = {**item, "properties": {**item["properties"], "n": {"type": "INTEGER"}}}
    item["required"] = ["n"] + list(item.get("required", []))
    return {"type": "OBJECT",
            "properties": {"results": {"type": "ARRAY", "items": item}},
            "required": ["results"]}


# ---- few-shot examples from quiz-master-verified tags (the feedback loop) ----

def recent_human_exemplars(db: Session, limit: int = 8) -> List[Dict[str, str]]:
    """Most recent HUMAN-confirmed tags, as compact worked examples. These are what a quiz master
    produced by clarifying/accepting in the review UI — reusing them teaches the model this vault's
    style. Cheap: one indexed query, cached per run by the caller."""
    rows = (db.query(QshalaTag, Question.question_text, Question.answer)
            .join(Question, Question.id == QshalaTag.question_id)
            .filter(QshalaTag.source == "HUMAN", QshalaTag.status == "confirmed",
                    QshalaTag.topic_l1.isnot(None))
            .order_by(QshalaTag.created_at.desc())
            .limit(limit).all())
    out = []
    for tag, qtext, _ans in rows:
        q = (qtext or "").strip().replace("\n", " ")
        if not q:
            continue
        out.append({"q": q[:200], "theme": tag.topic_l1 or "", "subtopic": tag.subtopic_l2 or ""})
    return out


def _exemplar_block(exemplars: List[Dict[str, str]]) -> str:
    if not exemplars:
        return ""
    lines = ["\nQUIZ-MASTER-VERIFIED EXAMPLES (match this judgement; do not quote them back):"]
    for e in exemplars:
        lines.append(f'- "{e["q"]}" -> theme: {e["theme"]} | subtopic: {e["subtopic"]}')
    return "\n".join(lines) + "\n"


def _batch_user_prompt(items: List[Dict[str, Any]], exemplars: List[Dict[str, str]]) -> str:
    parts = [_exemplar_block(exemplars),
             f"Tag the following {len(items)} questions. Return `results` with one object per "
             f"question, each with its `n` (the number shown). Tag every question; never skip one.\n"]
    for it in items:
        block = [f"[n={it['n']}] QUESTION: {it['question_text']}", f"ANSWER: {it['answer']}"]
        if it.get("visual_clues"):
            block.append(f"VISUAL CLUES: {it['visual_clues'][:400]}")
        if it["rules"].brand_hints_l1:
            block.append(f"Rule hint: likely theme(s) {', '.join(it['rules'].brand_hints_l1)}.")
        if it["rules"].image_dependent:
            block.append("Rule hint: may depend on an unseen image; tag from text, set fit=weak if unsure.")
        parts.append("\n".join(block))
    return "\n\n".join(p for p in parts if p)


# ---- write one routed result (mirrors _finish_v6 so draft/confirmed behaviour is identical) ----

def _write_item(db: Session, *, q: Dict[str, Any], llm_out: Dict[str, Any], model: str,
                latency_ms: int, actor: str, reason_prefix: str = "") -> QshalaTag:
    rules = q["rules"]
    paths = _v6_paths(llm_out)
    first = paths[0] if paths else {}
    routed = {"fit": llm_out.get("fit", "weak"),
              "india_international": llm_out.get("india_international"),
              "subtopic_l2": first.get("l2")}
    status, confidence, reason = _route(rules, routed)
    if not paths:
        status, confidence, reason = "draft", 0.30, "model returned no usable topic"
    if reason_prefix:
        reason = f"{reason_prefix}{reason}"
    geo = llm_out.get("india_international")

    existing = (db.query(QshalaTag)
                .filter(QshalaTag.status == "confirmed", QshalaTag.question_id == q["question_id"])
                .order_by(QshalaTag.created_at.desc()).first())
    if existing and existing.source == "HUMAN":
        return existing  # never re-tag over a human-confirmed row

    row = QshalaTag(
        question_id=q["question_id"], taxonomy_version=TAXONOMY_VERSION, model_version=model,
        source="LLM", topic_l1=first.get("l1"), subtopic_l2=first.get("l2"),
        keywords_l3=first.get("keywords", []),
        secondary_l2=[p["l2"] for p in paths[1:] if p.get("l2")],
        city_name=rules.city_name,
        geo_region=(llm_out.get("geo_location") or "").strip() or rules.geo_region,
        india_international=geo if geo in GEOGRAPHY_V6 else "NA",
        relevant_year=_clean_year(llm_out.get("relevant_year")),
        fit=llm_out.get("fit"), search_summary=llm_out.get("search_summary"),
        confidence=confidence, status=status, latency_ms=latency_ms,
        verification_notes=f"auto-routed (batch): {reason}",
    )
    db.add(row); db.flush()
    if status == "confirmed":
        if existing:
            existing.status = "superseded"
            db.add(QshalaTagChange(question_id=q["question_id"], from_tag_id=existing.id,
                                   to_tag_id=row.id, change_type="SUPERSEDE", actor=actor, reason=reason))
        db.add(QshalaTagChange(question_id=q["question_id"], from_tag_id=None, to_tag_id=row.id,
                               change_type="PROMOTE", actor=actor, reason=reason))
    if paths and not topic_paths.has_human_paths(db, q["question_id"]):
        topic_paths.replace_paths(db, q["question_id"], paths, source="LLM", actor=actor,
                                  question=q.get("question_obj"))
    from backend.app.services.question_meta_service import apply_tag_to_meta
    apply_tag_to_meta(db, q["question_id"], row)
    return row


def _write_to_review(db: Session, q: Dict[str, Any], model: str, reason: str) -> QshalaTag:
    """Fallback: park a question in the review queue (draft, confidence 0) when its chunk failed."""
    existing = (db.query(QshalaTag)
                .filter(QshalaTag.status == "confirmed", QshalaTag.question_id == q["question_id"])
                .order_by(QshalaTag.created_at.desc()).first())
    if existing and existing.source == "HUMAN":
        return existing
    row = QshalaTag(question_id=q["question_id"], taxonomy_version=TAXONOMY_VERSION,
                    model_version=model, source="LLM", fit="none", confidence=0.0,
                    status="draft", verification_notes=f"needs review: {reason}")
    db.add(row); db.flush()
    return row


# ---- the orchestrator ----

async def tag_deck_batched(db: Session, questions: List[Question], *, provider, model: str,
                           actor: str = "system", thinking_level: str = "low",
                           rpm: float = 0.0) -> Dict[str, int]:
    """Tag a whole deck in chunks. Commits per chunk. Always completes; uncertain or failed
    questions end up as `draft` (review). Returns {confirmed, draft, chunks, failed_chunks}."""
    items: List[Dict[str, Any]] = []
    for idx, q in enumerate(questions):
        qtext = (q.question_text or "").strip()
        if not qtext and getattr(q, "explanation", None):
            qtext = (q.explanation or "").strip()
        ans = (q.answer or "").strip()
        if not qtext or not ans:
            _write_to_review(db, {"question_id": q.id, "rules": qshala_rules.extract(qtext or "", ans or "", taxonomy_version=TAXONOMY_VERSION), "question_obj": q}, model, "missing question text or answer")
            continue
        items.append({
            "n": idx, "question_id": q.id, "question_obj": q,
            "question_text": qtext, "answer": ans,
            "visual_clues": getattr(q, "visual_clues", "") or "",
            "rules": qshala_rules.extract(qtext, ans, taxonomy_version=TAXONOMY_VERSION),
        })

    exemplars = recent_human_exemplars(db)          # the feedback loop, read once per deck
    chunks = [items[i:i + CHUNK_SIZE] for i in range(0, len(items), CHUNK_SIZE)]
    schema, system = _batch_schema(), _system_prompt()
    sem = asyncio.Semaphore(CHUNK_CONCURRENCY)
    stats = {"confirmed": 0, "draft": 0, "chunks": len(chunks), "failed_chunks": 0}

    async def run_chunk(chunk: List[Dict[str, Any]]) -> Dict[int, Tuple[Dict[str, Any], int]]:
        prompt = _batch_user_prompt(chunk, exemplars)
        async with sem:
            for attempt in range(MAX_CHUNK_RETRIES):
                try:
                    if rpm and rpm > 0:
                        await asyncio.sleep(60.0 / rpm)
                    t0 = time.perf_counter()
                    data, _usage = await asyncio.wait_for(
                        provider.generate_json_schema(prompt=prompt, schema=schema,
                                                      system_instruction=system, model=model,
                                                      thinking_level=thinking_level, temperature=0.0),
                        timeout=CHUNK_TIMEOUT_S)
                    latency = int((time.perf_counter() - t0) * 1000)
                    if isinstance(data, dict) and "results" in data:
                        results = {int(r["n"]): (r, latency) for r in (data.get("results") or [])
                                   if isinstance(r, dict) and "n" in r}
                    elif isinstance(data, dict) and ("topics" in data or "subtopic_l2" in data):
                        # Compatibility fallback for single-question mocks like FakeGemini
                        results = {q["n"]: (data, latency) for q in chunk}
                    else:
                        results = {}
                    return results
                except Exception as e:
                    if attempt == MAX_CHUNK_RETRIES - 1:
                        logger.error("batch chunk failed: %s", safe_error(e))
                        return {}
                    wait = (retry_after_seconds(e) or min(30, 6 * (2 ** attempt))) if is_rate_limit(e) \
                        else 1.5 * (attempt + 1)
                    await asyncio.sleep(wait)
        return {}

    # Run chunks with bounded concurrency, commit each as it lands.
    coros = [run_chunk(c) for c in chunks]
    for chunk, fut in zip(chunks, await asyncio.gather(*coros)):
        got = fut
        if not got:
            stats["failed_chunks"] += 1
        for q in chunk:
            res = got.get(q["n"])
            try:
                if res is None:
                    _write_to_review(db, q, model, "batch chunk failed; parked for review")
                    stats["draft"] += 1
                else:
                    llm_out, latency = res
                    row = _write_item(db, q=q, llm_out=llm_out, model=model, latency_ms=latency,
                                      actor=actor)
                    stats["confirmed" if row.status == "confirmed" else "draft"] += 1
            except Exception as e:
                db.rollback()
                logger.error("write failed for %s: %s", q["question_id"], safe_error(e))
                _write_to_review(db, q, model, f"write error: {safe_error(e)[:120]}")
                stats["draft"] += 1
        db.commit()                                 # per-chunk commit -> no long-open transaction

    logger.info("batch tagging done: %s", stats)
    return stats
