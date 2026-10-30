"""Prompt-quiz engine: one sentence in, a curated draft quiz out.

Five personas, each a small deterministic step:
  Interpreter - turns the prompt into a Brief (topic words, count, filters, difficulty mix).
                Uses Gemini when GEMINI_API_KEY is set (natural-language understanding),
                and falls back to the regex parse_prompt() otherwise. Gemini ONLY reads the
                prompt and emits the structured Brief; it never selects or writes questions.
  Librarian   - retrieves candidates (BM25 over the bank; uses qshala_tags when present,
                falls back to the older Question.topic/subtopic/tags)
  Guardian    - drops duplicates, image-only, sensitive or time-sensitive items per brief
  Editor      - picks N with topic variety and an easy->hard ramp
  Host        - writes the one-line framing shown to the user

Retrieval, ranking and selection stay 100% deterministic Python — the LLM's role is
strictly prompt -> Brief, so there is zero hallucination risk in the questions served.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.question import Question
try:  # tag table may be absent or renamed on some branches; engine degrades to Question fields
    from backend.app.models.qshala_tag import QshalaTag
except Exception:  # pragma: no cover
    QshalaTag = None
from backend.app.services.prompt_quiz.retrieval import Index, parse_prompt, tokenize, WORD_NUMS

DIFF_RANK = {"easy": 0, "medium": 1, "hard": 2}


@dataclass
class Brief:
    prompt: str
    query: str
    count: int
    filters: Dict[str, Any] = field(default_factory=dict)
    ramp: bool = True
    hard_bias: Optional[str] = None  # "easy" | "hard" | None
    framing: Optional[str] = None    # LLM host framing, if the Interpreter produced one
    source: str = "regex"            # "gemini" | "regex" — which interpreter produced this brief
    format_filter: Optional[str] = None # CONNECT_4 | STEPPED_CLUE | ARRANGE_ORDER

    def public(self) -> Dict[str, Any]:
        return asdict(self)


# ---------- Interpreter ----------
def _bias_from_text(p: str) -> Optional[str]:
    return "hard" if re.search(r"\b(hard(?:er)?|tough(?:er)?|difficult|finals?)\b", p) else \
           "easy" if re.search(r"\b(easy|easier|warm-?up|beginner|gentle)\b", p) else None


def _brief_from_gemini(prompt: str, gem: Dict[str, Any], count: Optional[int],
                       previous_brief: Optional[Dict[str, Any]]) -> Brief:
    """Map the Gemini Interpreter JSON onto a Brief. Topic themes/subtopics are folded into the
    free-text query (not a hard filter) so the deterministic retriever's relax-if-narrow safety
    still applies and we never return an empty set because a theme name didn't match the bank."""
    # count: explicit UI count arg wins; else model's count; else inherit previous; else 10.
    n = count or gem.get("count") or (previous_brief or {}).get("count") or 10
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 50))

    query_bits = [str(gem.get("query") or "").strip()]
    query_bits += [str(t) for t in (gem.get("topics_l1") or []) if t]
    query_bits += [str(t) for t in (gem.get("subtopics_l2") or []) if t]
    query = re.sub(r"\s+", " ", " ".join(b for b in query_bits if b)).strip()

    filters: Dict[str, Any] = {}
    if gem.get("india_focused") is True:
        filters["india_international"] = "IN"
    if gem.get("evergreen") is True:
        filters["evergreen_only"] = True
    if gem.get("no_images") is True:
        filters["exclude_image"] = True
    if gem.get("audience") == "school":
        filters["school_safe"] = True

    raw_bias = (gem.get("hard_bias") or "").lower()
    bias = "hard" if raw_bias in ("hard", "spicy") else "easy" if raw_bias == "easy" else None

    framing = (gem.get("framing") or "").strip() or None
    fmt = gem.get("format_filter") or (previous_brief or {}).get("format_filter")
    return Brief(prompt=prompt, query=query, count=n, filters=filters,
                 hard_bias=bias, framing=framing, source="gemini", format_filter=fmt)


def _brief_from_regex(prompt: str, count: Optional[int],
                      previous_brief: Optional[Dict[str, Any]]) -> Brief:
    query, filters, n = parse_prompt(prompt or "")
    p = (prompt or "").lower()
    has_number = bool(re.search(r"\b\d{1,3}\b", p)) or any(
        re.search(r"\b" + re.escape(w) + r"\b", p) for w in WORD_NUMS)
    # refine fallback: a follow-up with no explicit number inherits the previous count.
    inherited = (previous_brief or {}).get("count") if previous_brief else None
    final_n = count or (n if has_number else (inherited or 10))
    final_n = max(1, min(int(final_n), 50))
    bias = _bias_from_text(p)
    fmt = filters.get("format_filter") or (previous_brief or {}).get("format_filter")
    return Brief(prompt=prompt, query=query, count=final_n, filters=filters,
                 hard_bias=bias, source="regex", format_filter=fmt)


def interpret(prompt: str, count: Optional[int] = None, options: Optional[Dict[str, Any]] = None,
              previous_brief: Optional[Dict[str, Any]] = None) -> Brief:
    """Prompt -> Brief. Tries the Gemini Interpreter first; on any failure (no key, timeout,
    error) falls back seamlessly to the regex parser. `options` are explicit UI toggles applied
    last and always win. `previous_brief` enables refinement ("make it harder", "5 more")."""
    gem: Optional[Dict[str, Any]] = None
    try:
        from backend.app.services.prompt_quiz.interpreter_llm import interpret_with_gemini
        gem = interpret_with_gemini(prompt or "", previous_brief)
    except Exception:
        gem = None

    brief = _brief_from_gemini(prompt, gem, count, previous_brief) if gem \
        else _brief_from_regex(prompt, count, previous_brief)

    # Explicit UI options override whatever either interpreter decided.
    for k, v in (options or {}).items():
        if v in (None, False, ""):
            brief.filters.pop(k, None)
        else:
            brief.filters[k] = v
    return brief


# ---------- Librarian ----------
def _load_bank(db: Session) -> List[Dict[str, Any]]:
    qs = db.query(Question).filter((Question.duplicate_status != "CONFIRMED_DUPLICATE") | (Question.duplicate_status.is_(None))).all()
    tags: Dict[str, Any] = {}
    try:
        if QshalaTag is None:
            raise RuntimeError("no tag table")
        rows = (db.query(QshalaTag).filter(QshalaTag.status.in_(["confirmed", "draft"]))
                .order_by(QshalaTag.created_at.asc()).all())
        for r in rows:  # newest wins; confirmed beats draft
            old = tags.get(r.question_id)
            if old is None or r.status == "confirmed" or old.status != "confirmed":
                tags[r.question_id] = r
    except Exception:
        tags = {}
    bank = []
    for q in qs:
        # Exclude questions with empty text unless they have valid visual clues
        q_text_clean = (q.question_text or "").strip()
        has_img = bool(getattr(q, 'question_images', None) or getattr(q, 'image_refs', None))
        if len(q_text_clean) < 8 and not has_img:
            continue
        t = tags.get(q.id)
        has_img = bool(getattr(q, 'question_images', None) or getattr(q, 'image_refs', None))
        bank.append({
            "id": q.id,
            "question_text": q.question_text,
            "answer": q.answer,
            "topic_l1": (getattr(t, 'topic_l1', None) if t else None) or q.topic,
            "subtopic_l2": (getattr(t, 'subtopic_l2', None) if t else None) or q.subtopic,
            "secondary_l2": (getattr(t, 'secondary_l2', None) if t else None) or [],
            "keywords": (getattr(t, 'keywords_l3', None) if t and getattr(t, 'keywords_l3', None) else None) or (q.tags or []),
            "india_international": getattr(t, 'india_international', None) if t else None,
            "shelf_life": (getattr(t, 'shelf_life', None) if t else None) or ("TIME_SENSITIVE" if getattr(q, "temporal_nature", None) == "TIME_SENSITIVE" else "EVERGREEN"),
            "sensitivity": getattr(t, 'sensitivity', None) if t else None,
            "image_dependent": has_img,
            "question_images": list(getattr(q, 'question_images', []) or []),
            "answer_images": list(getattr(q, 'answer_images', []) or []),
            "image_refs": list(getattr(q, 'image_refs', []) or []),
            "search_summary": getattr(t, 'search_summary', None) if t else None,
            "difficulty": (q.difficulty or "Medium"),
            "difficulty_score": q.difficulty_score if q.difficulty_score is not None else 0.5,
            "document_id": q.document_id,
            "tagged": bool(t),
            "question_format": getattr(q, 'question_format', None) or getattr(q, 'question_type', 'STANDARD_QA'),
        })
    return bank


def librarian(bank: List[Dict[str, Any]], brief: Brief, pool: int = 80) -> List[Dict[str, Any]]:
    if brief.format_filter:
        bank = [q for q in bank if q.get("question_format") == brief.format_filter]
    idx = Index(bank)
    hits = idx.search(brief.query, brief.filters, top_k=pool)
    if len(hits) < brief.count:  # query too narrow: relax hard filters other than safety
        relaxed = {k: v for k, v in brief.filters.items() if k in ("school_safe", "exclude_image")}
        seen = {h["id"] for h in hits}
        hits += [h for h in idx.search(brief.query, relaxed, top_k=pool) if h["id"] not in seen]
    if len(hits) < brief.count and brief.query:  # keyword not in bank: pull broad candidates matching safety
        relaxed = {k: v for k, v in brief.filters.items() if k in ("school_safe", "exclude_image")}
        seen = {h["id"] for h in hits}
        hits += [h for h in idx.search("", relaxed, top_k=pool) if h["id"] not in seen]
    return hits


# ---------- Guardian ----------
def _fp(text: str) -> frozenset:
    return frozenset(tokenize(text)[:14])


def guardian(hits: List[Dict[str, Any]], brief: Brief, exclude_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    out, seen = [], []
    for h in hits:
        if exclude_ids and h["id"] in exclude_ids:
            continue
        fp = _fp(h["question_text"])
        if any(fp and len(fp & s) / max(len(fp | s), 1) > 0.7 for s in seen):
            continue
        seen.append(fp)
        out.append(h)
    return out


# ---------- Editor ----------
def editor(cands: List[Dict[str, Any]], brief: Brief) -> List[Dict[str, Any]]:
    n = brief.count
    ordered_cands = list(cands)
    if brief.hard_bias == "hard":
        ordered_cands.sort(key=lambda c: -(c.get("difficulty_score") or 0.5))
    elif brief.hard_bias == "easy":
        ordered_cands.sort(key=lambda c: (c.get("difficulty_score") or 0.5))

    chosen: List[Dict[str, Any]] = []
    per_sub: Dict[str, int] = {}
    cap = max(2, -(-n // 3))  # no subtopic takes more than ~a third
    leftovers = []
    for c in ordered_cands:
        sub = c.get("subtopic_l2") or c.get("topic_l1") or "?"
        if per_sub.get(sub, 0) >= cap:
            leftovers.append(c)
            continue
        per_sub[sub] = per_sub.get(sub, 0) + 1
        chosen.append(c)
        if len(chosen) == n:
            break
    for c in leftovers:
        if len(chosen) >= n:
            break
        chosen.append(c)
    if brief.ramp:
        chosen.sort(key=lambda c: c.get("difficulty_score") or 0.5)
        if brief.hard_bias == "hard":
            chosen.sort(key=lambda c: -(c.get("difficulty_score") or 0.5))
    return chosen


# ---------- Host ----------
def host(brief: Brief, picked: List[Dict[str, Any]], bank_size: int) -> str:
    if not picked:
        return "I couldn't find anything for that in the bank yet. Try a broader topic."
    # Prefer the Interpreter's witty framing when it produced one and the draft is complete.
    if brief.framing and len(picked) >= brief.count:
        return brief.framing
    subs = {}
    for p in picked:
        s = p.get("subtopic_l2") or p.get("topic_l1")
        if s:
            subs[s] = subs.get(s, 0) + 1
    top = ", ".join(s for s, _ in sorted(subs.items(), key=lambda x: -x[1])[:3])
    short = "" if len(picked) >= brief.count else f" (only {len(picked)} of {brief.count} matched)"
    ramp = "easy to hard" if brief.hard_bias != "hard" else "hardest first"
    return f"{len(picked)} questions{short}, ordered {ramp}. Mostly {top}."


def _view(c: Dict[str, Any]) -> Dict[str, Any]:
    return {k: c.get(k) for k in ("id", "question_text", "answer", "topic_l1", "subtopic_l2",
                                  "difficulty", "image_dependent", "shelf_life", "tagged", "score", "document_id",
                                  "question_images", "answer_images", "image_refs")}


def build_draft(db: Session, prompt: str, count: Optional[int] = None,
                options: Optional[Dict[str, Any]] = None,
                previous_brief: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    brief = interpret(prompt, count, options, previous_brief)
    bank = _load_bank(db)
    cands = guardian(librarian(bank, brief), brief)
    picked = editor(cands, brief)
    return {
        "brief": brief.public(),
        "questions": [_view(p) for p in picked],
        "message": host(brief, picked, len(bank)),
        "bank_size": len(bank),
        "stages": ["Interpreter", "Librarian", "Guardian", "Editor", "Host"],
    }


def swap_one(db: Session, prompt: str, question_id: str, keep_ids: List[str],
             options: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    brief = interpret(prompt, 1, options)
    bank = _load_bank(db)
    target = next((b for b in bank if b["id"] == question_id), None)
    if target and target.get("subtopic_l2"):  # prefer a neighbour of the swapped question
        brief.query = f"{brief.query} {target['subtopic_l2']}"
    cands = guardian(librarian(bank, brief), brief, exclude_ids=set(keep_ids) | {question_id})
    return _view(cands[0]) if cands else None
