"""Audience + safety logic for the prompt engine, built on fields that ALREADY exist on bank candidates
(india_international, sensitivity, shelf_life, difficulty_score, tagged, ...). Pure functions: no DB, no LLM.

HARD rules (passes_hard) are never relaxed silently: format, no_images, school_safe, evergreen.
SOFT rules (audience_score, difficulty_penalty) only reorder; they never remove a question.
"""
from typing import Any, Dict, Iterable, List, Optional, Set

Candidate = Dict[str, Any]

HARD_FLAGS = ("format", "no_images", "school_safe", "evergreen", "india_international")
_BANDS = {"easy": (0.0, 0.35), "medium": (0.35, 0.65), "hard": (0.65, 1.01)}
_IN_MARKERS = (
    "india", "indian", "karnataka", "bangalore", "bengaluru",
    "mumbai", "bombay", "delhi", "chennai", "madras",
    "kolkata", "calcutta", "pune", "hyderabad", "mysore", "mysuru", "hassan"
)


def _lc(v: Any) -> str:
    return (v or "").strip().lower() if isinstance(v, str) else ""


# ------------------------------------------------------------------ hard filters
def passes_hard(c: Candidate, filters: Dict[str, Any], format_filter: Optional[str] = None,
                skip: Optional[str] = None) -> bool:
    """True if the candidate satisfies every hard rule. `skip` ignores one rule (used to count what a rule blocks)."""
    f = filters or {}
    if skip != "format" and format_filter and (c.get("question_format") or "STANDARD_QA") != format_filter:
        return False
    if skip != "no_images" and f.get("no_images"):
        # Real image lists only. `image_dependent` is a loose "short question" heuristic, so it is NOT used here.
        if c.get("question_images") or c.get("answer_images") or c.get("image_refs"):
            return False
    if skip != "school_safe" and f.get("school_safe"):
        if not c.get("tagged"):
            return False                      # unknown sensitivity: stay conservative for school audiences
        # NULL sensitivity means "never assessed" (rule-seeded rows, parked/failed rows), NOT "safe".
        sens = c.get("sensitivity")
        if not isinstance(sens, str) or sens.strip().upper() != "NONE":
            return False
    if skip != "evergreen" and f.get("evergreen"):
        if (c.get("shelf_life") or "").upper() == "TIME_SENSITIVE":
            return False
    if skip != "india_international" and f.get("india_international"):
        target_geo = str(f.get("india_international")).upper()
        c_geo = (c.get("india_international") or "").upper()
        if c_geo and c_geo in (target_geo, "MIXED"):
            pass
        else:
            txt = (
                (c.get("question_text") or "") + " " +
                (c.get("answer") or "") + " " +
                (c.get("topic_l1") or "") + " " +
                (c.get("city_name") or "") + " " +
                (c.get("geo_region") or "")
            ).lower()
            has_in = any(m in txt for m in _IN_MARKERS)
            if target_geo == "IN" and not has_in:
                return False
            if target_geo == "INTL" and has_in:
                return False
    return True


# ------------------------------------------------------------------ difficulty (soft)
def difficulty_value(c: Candidate) -> Optional[float]:
    """0..1 or None when unrated. Multimodal questions are 'Unrated' by policy, so they stay neutral."""
    label = _lc(c.get("difficulty"))
    if label in ("", "unrated", "unknown"):
        return None
    s = c.get("difficulty_score")
    if isinstance(s, (int, float)):
        return float(s)
    return {"easy": 0.2, "medium": 0.5, "hard": 0.8}.get(label)


def _target_band(hard_bias: Optional[str]):
    t = _lc(hard_bias)
    if t == "spicy":
        t = "hard"
    return _BANDS.get(t)             # None for balanced / unset


def difficulty_penalty(c: Candidate, hard_bias: Optional[str]) -> float:
    """0 = fits the requested band. Up to 1.0 = far outside it. Unrated gets a small fixed nudge."""
    band = _target_band(hard_bias)
    if band is None:
        return 0.0
    v = difficulty_value(c)
    if v is None:
        return 0.1
    lo, hi = band
    gap = lo - v if v < lo else (v - hi if v >= hi else 0.0)
    return min(1.0, max(0.0, gap) / 0.35)


# ------------------------------------------------------------------ audience (soft)
def audience_score(c: Candidate, *, locality: Optional[str] = None, india_focused: Optional[bool] = None,
                   audience: Optional[str] = None, tone: Optional[Iterable[str]] = None) -> float:
    """Additive nudge on top of the BM25 score. Roughly -0.4 .. +1.8."""
    d = 0.0
    geo = (c.get("india_international") or "NA").upper()
    if geo in ("NA", ""):
        txt = ((c.get("question_text") or "") + " " + (c.get("answer") or "")).lower()
        geo = "IN" if any(m in txt for m in _IN_MARKERS) else "INTL"
    if india_focused is True:
        d += 0.5 if geo in ("IN", "MIXED") else (-0.4 if geo == "INTL" else 0.0)
    elif india_focused is False:
        d += 0.4 if geo == "INTL" else (-0.3 if geo == "IN" else 0.0)

    loc = _lc(locality)
    if loc and loc not in ("global", "international", "world"):
        city, region = _lc(c.get("city_name")), _lc(c.get("geo_region"))
        loc_aliases = {loc}
        if loc in ("bengaluru", "bangalore"):
            loc_aliases = {"bengaluru", "bangalore"}
        elif loc in ("mumbai", "bombay"):
            loc_aliases = {"mumbai", "bombay"}
        elif loc in ("chennai", "madras"):
            loc_aliases = {"chennai", "madras"}
        elif loc in ("kolkata", "calcutta"):
            loc_aliases = {"kolkata", "calcutta"}
        elif loc in ("delhi", "new delhi"):
            loc_aliases = {"delhi", "new delhi"}
        elif loc == "karnataka":
            loc_aliases = {"karnataka", "bengaluru", "bangalore", "mysore", "mysuru"}

        q_blob = (_lc(c.get("question_text")) + " " + _lc(c.get("answer")) + " " +
                  " ".join(str(kw).lower() for kw in c.get("keywords") or []) + " " + _lc(c.get("search_summary")))

        if city and any(a == city for a in loc_aliases):
            d += 0.9
        elif (region and any(a == region or a in region for a in loc_aliases)) or (city and any(a in city for a in loc_aliases)):
            d += 0.6
        elif any(a in q_blob for a in loc_aliases):
            d += 0.5

    aud = _lc(audience)
    if aud and aud != "general" and _lc(c.get("primary_audience")) == aud:
        d += 0.3

    words = [_lc(t).replace("-", " ") for t in (tone or []) if _lc(t)]
    if words:
        blob = " ".join([" ".join(c.get("keywords") or []), c.get("search_summary") or ""]).lower()
        d += min(0.6, 0.2 * sum(1 for w in words if w in blob))
    return d


def defaults_for_audience(audience: Optional[str], filters: Dict[str, Any], hard_bias: Optional[str]):
    """Fill only what the quizmaster left unset. Returns (filters, hard_bias)."""
    f = dict(filters or {})
    aud = _lc(audience)
    if aud == "school":
        f.setdefault("school_safe", True)
        f.setdefault("evergreen", True)
        hard_bias = hard_bias or "easy"
    elif aud in ("college", "corporate"):
        hard_bias = hard_bias or "medium"
    return f, hard_bias
