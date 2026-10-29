"""Chunked, review-gated batch tagging for deck ingestion.

Why this exists
---------------
The per-question tagger (`QshalaTagger.tag`) is correct but makes one Gemini call per question with
rate-limit spacing, which dominates ingestion time. A naive "one call for the whole deck" fixes the
speed but overflows Gemini's output-token ceiling on a large deck (the JSON array is truncated and
`json.loads` throws), which is the failure that stalled ingestion partway through.

This module sends one Gemini call per *chunk* of questions (default 12), so each response stays well
under the token ceiling. Every returned item is run through the SAME `_route()` confidence gate the
single-question path uses, so low-confidence / weak-fit results still land in `draft` (the review
queue) exactly as before. A chunk that fails, times out, or returns short does not abort the deck:
its questions are tagged `draft` with a reason and ingestion continues — the pipeline always reaches
a terminal state.

Quiz-master feedback loop
-------------------------
`recent_human_exemplars()` pulls the most recent human-confirmed tags and injects them into each
chunk prompt as worked examples. Every correction a quiz master makes in the review UI therefore
improves tagging on the next deck, with no training step. "Human-confirmed" covers BOTH review
actions: Correct (writes a new source="HUMAN" tag) and Accept (promotes the AI draft and stamps
verified_by) — see recent_human_exemplars.

This module reuses the tagger's taxonomy, prompt, schema, routing and path-normalisation helpers;
it does not duplicate that logic.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.models.qshala_tag import QshalaTag, QshalaTagChange
from backend.app.models.question import Question
from backend.app.services.tagging import qshala_rules, topic_paths
from backend.app.services.tagging.qshala_tagger import (
    TAXONOMY_VERSION, GEOGRAPHY_V6, _system_prompt, _tag_schema_v6,
    _v6_paths, _route, _clean_year, safe_error, is_rate_limit, retry_after_seconds,
)

logger = logging.getLogger(__name__)

CHUNK_SIZE = 12          # questions per Gemini call; keeps the response JSON well under the token ceiling
CHUNK_CONCURRENCY = 2    # chunks in flight at once; stays inside free-tier RPM with backoff
CHUNK_TIMEOUT_S = 75.0   # a chunk slower than this is abandoned and its questions go to review
MAX_CHUNK_RETRIES = 3


def _batch_schema() -> Dict[str, Any]:
    """The per-question v6 schema wrapped in a `results` array carrying each item's `n`."""
    item = _tag_schema_v6()
    item_props = dict(item.get("properties", {}))
    item_props["n"] = {"type": "INTEGER"}
    wrapped_item = {"type": "OBJECT", "properties": item_props,
                    "required": list({*item.get("required", []), "n"})}
    return {"type": "OBJECT",
            "properties": {"results": {"type": "ARRAY", "items": wrapped_item}},
            "required": ["results"]}


# --------------------------------------------------------------------- feedback loop

def recent_human_exemplars(db: Session, limit: int = 8) -> List[Dict[str, str]]:
    """Most recent human-confirmed tags as compact worked examples. These are what quiz masters
    produced in the review UI; reusing them teaches the model this vault's judgement. One indexed
    query; the caller reads it once per deck.

    A tag counts as human-confirmed when it is `confirmed` AND either the quiz master wrote it
    (source='HUMAN', via the Correct/tag-editor path) OR a quiz master promoted it (verified_by
    set, via the one-click Accept path). Earlier this filtered on source='HUMAN' alone, so Accept
    actions — which keep source='LLM' and only stamp verified_by — never reached the loop."""
    try:
        rows = (db.query(QshalaTag, Question.question_text)
                .join(Question, Question.id == QshalaTag.question_id)
                .filter(QshalaTag.status == "confirmed",
                        QshalaTag.topic_l1.isnot(None),
                        or_(QshalaTag.source == "HUMAN", QshalaTag.verified_by.isnot(None)))
                .order_by(QshalaTag.created_at.desc())
                .limit(limit).all())
    except Exception as e:                       # never let the feedback query break ingestion
        logger.warning("exemplar query failed (continuing without): %s", safe_error(e))
        return []
    out: List[Dict[str, str]] = []
    for tag, qtext in rows:
        q = (qtext or "").strip().replace("\n", " ")
        if q:
            out.append({"q": q[:200], "theme": tag.topic_l1 or "", "subtopic": tag.subtopic_l2 or ""})
    return out


def _exemplar_block(exemplars: List[Dict[str, str]]) -> str:
    if not exemplars:
        return ""
    lines = ["QUIZ-MASTER-VERIFIED EXAMPLES (match this judgement; do not quote them back):"]
    for e in exemplars:
        lines.append(f'- "{e["q"]}" -> theme: {e["theme"]} | subtopic: {e["subtopic"]}')
    return "\n".join(lines)


def _batch_user_prompt(items: List[Dict[str, Any]], exemplars: List[Dict[str, str]]) -> str:
    parts: List[str] = []
    ex = _exemplar_block(exemplars)
    if ex:
        parts.append(ex)
    parts.append(f"Tag the following {len(items)} questions. Return `results` with one object per "
                 f"question, each carrying its `n` (the number shown). Tag every question; never skip one.")
    for it in items:
        block = [f"[n={it['n']}] QUESTION: {it['question_text']}", f"ANSWER: {it['answer']}"]
        if it.get("visual_clues"):
            block.append(f"VISUAL CLUES: {it['visual_clues'][:400]}")
        rules = it["rules"]
        if rules.brand_hints_l1:
            block.append(f"Rule hint: likely theme(s) {', '.join(rules.brand_hints_l1)}.")
        if rules.image_dependent:
            block.append("Rule hint: may depend on an unseen image; tag from text, set fit=weak if unsure.")
        parts.append("\n".join(block))
    return "\n\n".join(parts)


# --------------------------------------------------------------------- writing results

def _write_item(db: Session, q: Dict[str, Any], llm_out: Dict[str, Any], model: str,
                latency_ms: int, actor: str) -> QshalaTag:
    """Persist one routed result. Mirrors QshalaTagger._finish_v6 so draft/confirmed behaviour and
    topic-path writing are identical to the single-question path."""
    rules = q["rules"]
    paths = _v6_paths(llm_out)
    # High-precedence deterministic L2 guards (ruling_sheet_22). Re-orders paths so a ruled subtopic
    # becomes primary and the model's original primary drops to secondary_l2.
    paths = qshala_rules.apply_disambiguation(paths, q.get("question_text", ""), q.get("answer", ""),
                                              taxonomy_version=TAXONOMY_VERSION)
    first = paths[0] if paths else {}
    routed = {"fit": llm_out.get("fit", "weak"),
              "india_international": llm_out.get("india_international"),
              "subtopic_l2": first.get("l2")}
    status, confidence, reason = _route(rules, routed)
    if not paths:
        status, confidence, reason = "draft", 0.30, "model returned no usable topic"
    geo = llm_out.get("india_international")

    existing = (db.query(QshalaTag)
                .filter(QshalaTag.status == "confirmed", QshalaTag.question_id == q["question_id"])
                .order_by(QshalaTag.created_at.desc()).first())
    if existing and existing.source == "HUMAN":
        return existing                           # never re-tag over a human-confirmed row

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
    db.add(row)
    db.flush()
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
    return row


def _write_to_review(db: Session, q: Dict[str, Any], model: str, reason: str) -> QshalaTag:
    """Park a question in the review queue (draft, confidence 0) when its chunk could not be tagged."""
    existing = (db.query(QshalaTag)
                .filter(QshalaTag.status == "confirmed", QshalaTag.question_id == q["question_id"])
                .order_by(QshalaTag.created_at.desc()).first())
    if existing and existing.source == "HUMAN":
        return existing
    row = QshalaTag(question_id=q["question_id"], taxonomy_version=TAXONOMY_VERSION,
                    model_version=model, source="LLM", fit="none", confidence=0.0,
                    status="draft", verification_notes=f"needs review: {reason}")
    db.add(row)
    db.flush()
    return row


# --------------------------------------------------------------------- orchestrator

async def tag_questions_batched(db: Session, questions: List[Question], *, provider, model: str,
                                actor: str = "deck_upload", thinking_level: str = "low",
                                rpm: float = 0.0) -> Dict[str, int]:
    """Tag a list of Question rows in chunks. The caller owns the transaction; this flushes rows and
    does NOT commit (so it composes with the pipeline's own commit). Always returns; uncertain or
    failed questions are left as `draft`. Returns counts {confirmed, draft, chunks, failed_chunks}."""
    items: List[Dict[str, Any]] = []
    for idx, q in enumerate(questions):
        qtext, ans = (q.question_text or "").strip(), (q.answer or "").strip()
        if not qtext or not ans:
            continue
        items.append({
            "n": idx, "question_id": q.id, "question_obj": q,
            "question_text": qtext, "answer": ans,
            "visual_clues": getattr(q, "visual_clues", "") or "",
            "rules": qshala_rules.extract(qtext, ans, taxonomy_version=TAXONOMY_VERSION),
        })

    exemplars = recent_human_exemplars(db)
    chunks = [items[i:i + CHUNK_SIZE] for i in range(0, len(items), CHUNK_SIZE)]
    schema, system = _batch_schema(), _system_prompt()
    sem = asyncio.Semaphore(CHUNK_CONCURRENCY)
    stats = {"confirmed": 0, "draft": 0, "chunks": len(chunks), "failed_chunks": 0}

    async def run_chunk(chunk: List[Dict[str, Any]]) -> Dict[int, Any]:
        prompt = _batch_user_prompt(chunk, exemplars)
        async with sem:
            for attempt in range(MAX_CHUNK_RETRIES):
                try:
                    if rpm and rpm > 0:
                        await asyncio.sleep(60.0 / rpm)
                    t0 = time.perf_counter()
                    data, _usage = await asyncio.wait_for(
                        provider.generate_json_schema(
                            prompt=prompt, schema=schema, system_instruction=system,
                            model=model, thinking_level=thinking_level, temperature=0.0),
                        timeout=CHUNK_TIMEOUT_S)
                    latency = int((time.perf_counter() - t0) * 1000)
                    return {int(r["n"]): (r, latency) for r in (data.get("results") or [])
                            if isinstance(r, dict) and "n" in r}
                except Exception as e:
                    if attempt == MAX_CHUNK_RETRIES - 1:
                        logger.error("batch chunk failed after %d attempts: %s",
                                     MAX_CHUNK_RETRIES, safe_error(e))
                        return {}
                    # Match the per-question tagger's proven 429 backoff: 6s, 12s, 24s (honour
                    # Retry-After when Google sends it). Non-rate-limit errors retry faster.
                    wait = (retry_after_seconds(e) or min(60, 6 * (2 ** attempt))) if is_rate_limit(e) \
                        else 1.5 * (attempt + 1)
                    await asyncio.sleep(wait)
        return {}

    results = await asyncio.gather(*[run_chunk(c) for c in chunks])
    for chunk, got in zip(chunks, results):
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
                    row = _write_item(db, q, llm_out, model, latency, actor)
                    stats["confirmed" if row.status == "confirmed" else "draft"] += 1
            except Exception as e:
                logger.error("tag write failed for %s: %s", q["question_id"], safe_error(e))
                try:
                    _write_to_review(db, q, model, f"write error: {safe_error(e)[:120]}")
                    stats["draft"] += 1
                except Exception:
                    pass

    logger.info("batch tagging: %s", stats)
    return stats
