"""Make an LLM-produced brief safe for retrieval: snap topics to real taxonomy names, drop invented ones,
and remove repeated words from the search query. Pure functions; no DB, no LLM."""
import difflib
import re
from typing import Dict, List, Sequence, Tuple


def _snap(value: str, known: Dict[str, str], cutoff: float) -> str:
    k = (value or "").strip().lower()
    if not k:
        return ""
    if k in known:
        return known[k]
    close = difflib.get_close_matches(k, list(known), n=1, cutoff=cutoff)
    return known[close[0]] if close else ""


def normalize_topics(l1s: Sequence[str], l2s: Sequence[str], *, l1_names: Sequence[str], l2_names: Sequence[str],
                     l2_to_l1: Dict[str, str], cutoff: float = 0.82) -> Tuple[List[str], List[str], List[str]]:
    """Returns (valid_l1s, valid_l2s, dropped). Names are snapped to the exact taxonomy spelling. A valid L2 also
    contributes its own L1, so 'Cricket' alone still yields 'Sports'. Anything unmatched goes to `dropped`."""
    k1 = {n.lower(): n for n in l1_names}
    k2 = {n.lower(): n for n in l2_names}
    out1: List[str] = []
    out2: List[str] = []
    dropped: List[str] = []
    for x in l2s or []:
        s = _snap(x, k2, cutoff)
        if not s:
            dropped.append(x)
        elif s not in out2:
            out2.append(s)
    for x in l1s or []:
        s = _snap(x, k1, cutoff)
        if not s:
            dropped.append(x)
        elif s not in out1:
            out1.append(s)
    for l2 in out2:
        parent = l2_to_l1.get(l2)
        if parent and parent not in out1:
            out1.append(parent)
    return out1, out2, dropped


def dedupe_query(query: str) -> str:
    """Drop repeated words (case-insensitive), keeping the first occurrence and its spelling.
    'engineering technology Technology Science engineering' -> 'engineering technology Science'."""
    seen = set()
    words = []
    for w in re.findall(r"\S+", query or ""):
        key = w.lower().strip(".,;:!?")
        if key and key not in seen:
            seen.add(key)
            words.append(w)
    return " ".join(words)
