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
from typing import Any, Dict, List, Optional, Sequence, Set

from sqlalchemy.orm import Session

from backend.app.models.question import Question
try:  # tag tables may be absent or renamed on some branches; engine degrades gracefully
    from backend.app.models.qshala_tag import QshalaTag, QshalaQuestionMetadata
except Exception:  # pragma: no cover
    QshalaTag = None
    QshalaQuestionMetadata = None

from backend.app.services.prompt_quiz.retrieval import Index, parse_prompt, tokenize, WORD_NUMS
from backend.app.services.prompt_quiz.interpreter_llm import V6_THEMES
from backend.app.services.prompt_quiz.audience import (
    audience_score, defaults_for_audience, difficulty_penalty, passes_hard
)
from backend.app.services.prompt_quiz.fulfillment import (
    blocked_counts, build_fulfillment, split_pools
)

DIFF_RANK = {"easy": 0, "medium": 1, "hard": 2}


@dataclass
class Brief:
    prompt: str
    query: str
    count: int
    filters: Dict[str, Any] = field(default_factory=dict)
    ramp: bool = True
    hard_bias: Optional[str] = None  # "easy" | "hard" | "medium" | None
    framing: Optional[str] = None    # LLM host framing, if the Interpreter produced one
    source: str = "regex"            # "gemini" | "regex" — which interpreter produced this brief
    format_filter: Optional[str] = None # CONNECT_4 | STEPPED_CLUE | ARRANGE_ORDER | STANDARD_QA
    locality: Optional[str] = None
    venue_type: Optional[str] = None
    tone: List[str] = field(default_factory=list)
    cross_topic_padding: bool = False
    topics_l1: List[str] = field(default_factory=list)
    subtopics_l2: List[str] = field(default_factory=list)

    def public(self) -> Dict[str, Any]:
        return asdict(self)


# ---------- Interpreter ----------
def _bias_from_text(p: str) -> Optional[str]:
    return "hard" if re.search(r"\b(hard(?:er)?|tough(?:er)?|difficult|finals?)\b", p) else \
           "easy" if re.search(r"\b(easy|easier|warm-?up|beginner|gentle)\b", p) else None


def _brief_from_gemini(prompt: str, gem: Dict[str, Any], count: Optional[int],
                       previous_brief: Optional[Dict[str, Any]]) -> Brief:
    prev_filters = dict((previous_brief or {}).get("filters") or {})

    # count: explicit UI count arg wins; else model's count; else inherit previous; else 10.
    n = count or gem.get("count") or (previous_brief or {}).get("count") or 10
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, 50))

    topics_l1 = list(gem.get("topics_l1") or (previous_brief or {}).get("topics_l1") or [])
    subtopics_l2 = list(gem.get("subtopics_l2") or (previous_brief or {}).get("subtopics_l2") or [])

    query_bits = [str(gem.get("query") or "").strip()]
    query_bits += [str(t) for t in topics_l1 if t]
    query_bits += [str(t) for t in subtopics_l2 if t]
    query = re.sub(r"\s+", " ", " ".join(b for b in query_bits if b)).strip()

    filters: Dict[str, Any] = dict(prev_filters)
    if gem.get("india_focused") is not None:
        filters["india_focused"] = gem.get("india_focused")
        filters["india_international"] = "IN" if gem.get("india_focused") is True else "INTL"
    if gem.get("evergreen") is not None:
        val = bool(gem.get("evergreen"))
        filters["evergreen"] = val
        if val:
            filters["evergreen_only"] = True
        else:
            filters.pop("evergreen_only", None)
    if gem.get("no_images") is not None:
        val = bool(gem.get("no_images"))
        filters["no_images"] = val
        if val:
            filters["exclude_image"] = True
        else:
            filters.pop("exclude_image", None)
    if gem.get("school_safe") is not None:
        filters["school_safe"] = bool(gem.get("school_safe"))
    if gem.get("audience"):
        filters["audience"] = gem.get("audience")

    raw_bias = gem.get("hard_bias")
    if raw_bias is None and previous_brief:
        raw_bias = previous_brief.get("hard_bias")
    raw_bias = (raw_bias or "").lower()
    bias = "hard" if raw_bias in ("hard", "spicy") else "easy" if raw_bias == "easy" else ("medium" if raw_bias == "medium" else None)

    framing = (gem.get("framing") or "").strip() or (previous_brief or {}).get("framing") or None
    fmt = gem.get("format_filter") or (previous_brief or {}).get("format_filter")

    locality = gem.get("locality") or (previous_brief or {}).get("locality")
    venue_type = gem.get("venue_type") or (previous_brief or {}).get("venue_type")
    tone = list(gem.get("tone") or (previous_brief or {}).get("tone") or [])
    cross_topic_padding = bool(gem.get("cross_topic_padding") if gem.get("cross_topic_padding") is not None else (previous_brief or {}).get("cross_topic_padding", False))

    return Brief(
        prompt=prompt,
        query=query,
        count=n,
        filters=filters,
        hard_bias=bias,
        framing=framing,
        source="gemini",
        format_filter=fmt,
        locality=locality,
        venue_type=venue_type,
        tone=tone,
        cross_topic_padding=cross_topic_padding,
        topics_l1=topics_l1,
        subtopics_l2=subtopics_l2,
    )


def _brief_from_regex(prompt: str, count: Optional[int],
                      previous_brief: Optional[Dict[str, Any]]) -> Brief:
    query, raw_filters, n = parse_prompt(prompt or "")
    p = (prompt or "").lower()
    has_number = bool(re.search(r"\b\d{1,3}\b", p)) or any(
        re.search(r"\b" + re.escape(w) + r"\b", p) for w in WORD_NUMS)
    inherited = (previous_brief or {}).get("count") if previous_brief else None
    final_n = count or (n if has_number else (inherited or 10))
    final_n = max(1, min(int(final_n), 50))

    prev_bias = (previous_brief or {}).get("hard_bias")
    bias = _bias_from_text(p) or prev_bias
    fmt = raw_filters.get("format_filter") or (previous_brief or {}).get("format_filter")

    # Inherit and merge filters
    filters = dict((previous_brief or {}).get("filters") or {})
    # Map raw_filters from parse_prompt
    if "exclude_image" in raw_filters:
        filters["exclude_image"] = True
        filters["no_images"] = True
    if "evergreen_only" in raw_filters:
        filters["evergreen_only"] = True
        filters["evergreen"] = True
    if "school_safe" in raw_filters:
        filters["school_safe"] = True
    if raw_filters.get("india_international") == "IN":
        filters["india_focused"] = True
        filters["india_international"] = "IN"
    elif raw_filters.get("india_international") == "INTL":
        filters["india_focused"] = False
        filters["india_international"] = "INTL"

    # Regex audience hints
    if re.search(r"\b(school|kids?|class\s*\d+|assembly|children)\b", p):
        filters["audience"] = "school"
        filters["school_safe"] = True
    elif re.search(r"\b(college|fest|hostel|campus)\b", p):
        filters["audience"] = "college"
    elif re.search(r"\b(corporate|company|office|offsite)\b", p):
        filters["audience"] = "corporate"

    # Locality detection
    locality = (previous_brief or {}).get("locality")
    city_m = re.search(r"\b(bangalore|bengaluru|mumbai|bombay|delhi|new delhi|pune|chennai|madras|kolkata|calcutta|hyderabad)\b", p)
    if city_m:
        raw_city = city_m.group(1).lower()
        city_map = {
            "bangalore": "Bengaluru", "bengaluru": "Bengaluru",
            "mumbai": "Mumbai", "bombay": "Mumbai",
            "delhi": "Delhi", "new delhi": "Delhi",
            "chennai": "Chennai", "madras": "Chennai",
            "kolkata": "Kolkata", "calcutta": "Kolkata",
            "pune": "Pune",
            "hyderabad": "Hyderabad",
        }
        locality = city_map.get(raw_city, raw_city.title())
        filters["india_focused"] = True

    venue_type = (previous_brief or {}).get("venue_type")
    tone = list((previous_brief or {}).get("tone") or [])
    cross_topic_padding = bool((previous_brief or {}).get("cross_topic_padding", False))
    if re.search(r"\b(related|adjacent|whatever you have|fill the rest)\b", p):
        cross_topic_padding = True

    # Detect V6 theme in prompt if not inherited
    matched_l1s = [t for t in V6_THEMES if t.lower() in p]
    topics_l1 = matched_l1s or list((previous_brief or {}).get("topics_l1") or [])
    subtopics_l2 = list((previous_brief or {}).get("subtopics_l2") or [])

    framing = (previous_brief or {}).get("framing")

    return Brief(
        prompt=prompt,
        query=query,
        count=final_n,
        filters=filters,
        hard_bias=bias,
        framing=framing,
        source="regex",
        format_filter=fmt,
        locality=locality,
        venue_type=venue_type,
        tone=tone,
        cross_topic_padding=cross_topic_padding,
        topics_l1=topics_l1,
        subtopics_l2=subtopics_l2,
    )


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

    # Defaults for audience
    f, hb = defaults_for_audience(brief.filters.get("audience"), brief.filters, brief.hard_bias)
    brief.filters = f
    brief.hard_bias = hb

    # Explicit UI options override whatever either interpreter decided.
    for k, v in (options or {}).items():
        if k == "format_filter":
            brief.format_filter = v or None
        elif k == "cross_topic_padding":
            brief.cross_topic_padding = bool(v)
        elif k == "hard_bias":
            brief.hard_bias = v or None
        elif v in (None, False, ""):
            brief.filters.pop(k, None)
            if k == "exclude_image":
                brief.filters.pop("no_images", None)
            elif k == "no_images":
                brief.filters.pop("exclude_image", None)
            elif k == "evergreen_only":
                brief.filters.pop("evergreen", None)
            elif k == "evergreen":
                brief.filters.pop("evergreen_only", None)
        else:
            brief.filters[k] = v
            if k == "exclude_image":
                brief.filters["no_images"] = True
            elif k == "no_images":
                brief.filters["exclude_image"] = True
            elif k == "evergreen_only":
                brief.filters["evergreen"] = True
            elif k == "evergreen":
                brief.filters["evergreen_only"] = True
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

    meta: Dict[str, Any] = {}
    if QshalaQuestionMetadata is not None:
        try:
            mrows = db.query(QshalaQuestionMetadata).all()
            for m in mrows:
                meta[m.question_id] = m
        except Exception:
            meta = {}

    bank = []
    for q in qs:
        # Exclude questions with empty text unless they have valid visual clues
        q_text_clean = (q.question_text or "").strip()
        has_img = bool(getattr(q, 'question_images', None) or getattr(q, 'image_refs', None))
        if len(q_text_clean) < 8 and not has_img:
            continue
        t = tags.get(q.id)
        m = meta.get(q.id)
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
            "city_name": (getattr(t, 'city_name', None) if t else None) or (getattr(m, 'city_name', None) if m else None),
            "geo_region": (getattr(t, 'geo_region', None) if t else None) or (getattr(m, 'geo_region', None) if m else None),
            "primary_audience": getattr(m, 'primary_audience', None) if m else None,
        })
    return bank


def librarian(bank: List[Dict[str, Any]], brief: Brief, pool: int = 80) -> List[Dict[str, Any]]:
    if brief.format_filter:
        bank = [q for q in bank if q.get("question_format") == brief.format_filter]
    idx = Index(bank)
    hits = idx.search(brief.query, brief.filters, top_k=pool)
    if len(hits) < brief.count:  # query too narrow: relax hard filters other than safety
        relaxed = {k: v for k, v in brief.filters.items() if k in ("school_safe", "no_images")}
        seen = {h["id"] for h in hits}
        hits += [h for h in idx.search(brief.query, relaxed, top_k=pool) if h["id"] not in seen]
    if len(hits) < brief.count and brief.query:  # keyword not in bank: pull broad candidates matching safety
        relaxed = {k: v for k, v in brief.filters.items() if k in ("school_safe", "no_images")}
        seen = {h["id"] for h in hits}
        hits += [h for h in idx.search("", relaxed, top_k=pool) if h["id"] not in seen]
    return hits


# ---------- Guardian ----------
def _fp(text: str) -> frozenset:
    return frozenset(tokenize(text)[:14])


def guardian(hits: List[Dict[str, Any]], brief: Brief, exclude_ids: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
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
                previous_brief: Optional[Dict[str, Any]] = None,
                exclude_ids: Optional[Set[str]] = None) -> Dict[str, Any]:
    brief = interpret(prompt, count, options, previous_brief)
    bank = _load_bank(db)

    # 3. Librarian: search broadly with filters=None, top_k=300
    idx = Index(bank)
    hits = idx.search(brief.query, filters=None, top_k=300)
    if len(hits) < 300:
        seen = {h["id"] for h in hits}
        broad = idx.search("", filters=None, top_k=300)
        hits += [h for h in broad if h["id"] not in seen]

    # Split into on-topic vs adjacent
    on_ok, adjacent, on_all, _ = split_pools(
        hits,
        l1s=brief.topics_l1,
        l2s=brief.subtopics_l2,
        filters=brief.filters,
        format_filter=brief.format_filter,
    )

    # 4. Score each pool item
    def _rank_cand(c: Dict[str, Any]) -> float:
        base = float(c.get("score") or 0.0)
        aud = audience_score(
            c,
            locality=brief.locality,
            india_focused=brief.filters.get("india_focused"),
            audience=brief.filters.get("audience"),
            tone=brief.tone,
        )
        diff_pen = difficulty_penalty(c, brief.hard_bias)
        return base + aud - 0.35 * diff_pen

    on_ok.sort(key=_rank_cand, reverse=True)
    adjacent.sort(key=_rank_cand, reverse=True)

    # 5. Guardian + Editor on ranked on-topic list
    effective_exclude = set(exclude_ids or set())
    cands = guardian(on_ok, brief, exclude_ids=effective_exclude)
    picked = editor(cands, brief)

    # 6. Padding if requested and short
    padded = 0
    if brief.cross_topic_padding and len(picked) < brief.count:
        needed = brief.count - len(picked)
        picked_ids = effective_exclude | {p["id"] for p in picked}
        adj_cands = guardian(adjacent, brief, exclude_ids=picked_ids)
        adj_brief = Brief(**{**asdict(brief), "count": needed})
        adj_picked = editor(adj_cands, adj_brief)
        picked.extend(adj_picked)
        padded = len(adj_picked)

    # 7. Fulfillment
    blocked = blocked_counts(on_all, brief.filters, brief.format_filter)
    fulfillment = build_fulfillment(
        requested=brief.count,
        picked=picked,
        padded=padded,
        adjacent_available=len(adjacent),
        blocked=blocked,
        hard_bias=brief.hard_bias,
        padding_allowed=brief.cross_topic_padding,
    )

    # 8. Host message
    msg = fulfillment["note"] if fulfillment.get("short") else host(brief, picked, len(bank))

    return {
        "brief": brief.public(),
        "questions": [_view(p) for p in picked],
        "message": msg,
        "bank_size": len(bank),
        "stages": ["Interpreter", "Librarian", "Guardian", "Editor", "Host"],
        "fulfillment": fulfillment,
    }


def swap_one(db: Session, prompt: str, question_id: str, keep_ids: List[str],
             options: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    brief = interpret(prompt, 1, options)
    bank = _load_bank(db)
    target = next((b for b in bank if b["id"] == question_id), None)
    if target and target.get("subtopic_l2"):  # prefer a neighbour of the swapped question
        brief.query = f"{brief.query} {target['subtopic_l2']}"
    idx = Index(bank)
    hits = idx.search(brief.query, filters=None, top_k=300)
    seen = {h["id"] for h in hits}
    broad = idx.search("", filters=None, top_k=300)
    hits += [h for h in broad if h["id"] not in seen]

    exclude_ids = set(keep_ids) | {question_id}
    ok_hits = [c for c in hits if c["id"] not in exclude_ids and passes_hard(c, brief.filters, brief.format_filter)]
    if not ok_hits:
        return None

    def _rank(c: Dict[str, Any]) -> float:
        aud = audience_score(
            c,
            locality=brief.locality,
            india_focused=brief.filters.get("india_focused"),
            audience=brief.filters.get("audience"),
            tone=brief.tone,
        )
        diff_pen = difficulty_penalty(c, brief.hard_bias)
        return float(c.get("score") or 0.0) + aud - 0.35 * diff_pen

    ok_hits.sort(key=_rank, reverse=True)
    cands = guardian(ok_hits, brief, exclude_ids=exclude_ids)
    return _view(cands[0]) if cands else None
