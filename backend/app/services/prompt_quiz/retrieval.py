"""QShala retrieval core — drop into backend/app/services/tagging/.

Framework-free. Build an index from a list of question dicts, then search with a
free-text query plus optional filters. Ranking is BM25 over (question text + answer +
keywords + subtopics + summary), with domain query-expansion so "fintech" also matches
"UPI", "wallet", etc. No external dependencies.

To use in FastAPI: build the index once at startup from your qshala_tags rows
(latest row per question, any status), then call index.search(query, filters) per request.
Swap this BM25 stage for pgvector later without changing the call site — see search().

Question dict shape (use your qshala_tags field names):
    {id, question_text, answer, topic_l1, subtopic_l2, secondary_l2[list],
     keywords (or keywords_l3)[list], india_international, shelf_life, sensitivity,
     image_dependent(bool)}
"""
from __future__ import annotations
import math, re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

STOP = set("the a an of to in on for and or is are was were be been being by with as at "
           "from this that it its their his her they them he she we you i which what who whom "
           "whose when where why how name named called known used also only not no than into over "
           "under after before during about more most new first world which these those there here "
           "had has have does did do your my our".split())

# Domain query-expansion: a query term on the left pulls in the terms on the right.
# These are one-directional (query -> extra query terms), tuned for QShala's decks.
SYNONYMS: Dict[str, List[str]] = {
    "fintech": ["upi", "wallet", "payments", "neobank", "paytm", "phonepe", "razorpay", "cred", "fintech"],
    "payments": ["upi", "wallet", "fastag", "rupay", "nfc", "card", "payment"],
    "crypto": ["cryptocurrency", "bitcoin", "dogecoin", "blockchain", "nft", "wazirx"],
    "startup": ["startup", "unicorn", "funding", "venture", "seed", "ipo", "founder"],
    "startups": ["startup", "unicorn", "funding", "venture", "founder"],
    "bank": ["bank", "banking", "rbi", "deposit", "loan", "nbfc", "atm"],
    "banking": ["bank", "rbi", "deposit", "npa", "loan", "nbfc"],
    "tax": ["tax", "gst", "income tax", "levy", "duty", "cess"],
    "ipo": ["ipo", "listing", "public offering", "prospectus"],
    "stock": ["stock", "share", "nse", "bse", "sensex", "nifty", "exchange", "equity"],
    "market": ["market", "stock", "sensex", "nifty", "index"],
    "cricket": ["cricket", "ipl", "bcci", "wicket", "test match", "world cup"],
    "sports": ["sports", "league", "football", "olympics", "tournament", "player"],
    "logo": ["logo", "brand", "identity", "mascot", "typeface", "symbol"],
    "brand": ["brand", "logo", "fmcg", "consumer", "marketing"],
    "ad": ["ad", "advertisement", "campaign", "advertising", "jingle", "tagline"],
    "advertising": ["ad", "advertisement", "campaign", "slogan", "tagline"],
    "insurance": ["insurance", "lic", "policy", "premium", "irdai"],
    "currency": ["currency", "note", "coin", "banknote", "rupee", "money", "mint"],
    "money": ["money", "currency", "cash", "fiat", "note", "coin"],
    "etymology": ["word", "origin", "latin", "derived", "phrase", "term"],
    "word": ["word", "origin", "etymology", "phrase", "derived"],
    "food": ["food", "cuisine", "dish", "sweet", "snack", "restaurant"],
    "ai": ["ai", "artificial intelligence", "chatbot", "openai", "gpt", "llm"],
    "ev": ["ev", "electric", "vehicle", "battery", "ola", "ather"],
    "auto": ["car", "automobile", "vehicle", "maruti", "tata motors", "ev"],
    "car": ["car", "automobile", "vehicle", "ev"],
    "acquisition": ["acquisition", "merger", "acquire", "stake", "buyout", "takeover"],
    "merger": ["merger", "acquisition", "acquire", "stake"],
    "scam": ["scam", "fraud", "scandal", "ponzi", "collapse", "phishing"],
    "scandal": ["scandal", "fraud", "collapse", "corporate crime"],
    "energy": ["energy", "solar", "power", "renewable", "hydrogen", "coal", "nuclear"],
    "festival": ["festival", "diwali", "mela", "celebration", "event"],
    "leader": ["ceo", "founder", "chairman", "billionaire", "entrepreneur"],
    "ceo": ["ceo", "chief executive", "founder", "chairman"],
}

_word = re.compile(r"[a-z0-9]+")

def tokenize(s: str) -> List[str]:
    return [w for w in _word.findall((s or "").lower()) if w not in STOP and len(w) > 1]

def _kw(q: Dict[str, Any]) -> List[str]:
    return q.get("keywords") or q.get("keywords_l3") or []


# --- deterministic question style (from text; no model, no stored column needed) ---
_STYLE_PATTERNS = [
    ("FILL_BLANK", re.compile(r"_{3,}|\bblanked?\b|fill in the blank", re.I)),
    ("ODD_ONE_OUT", re.compile(r"odd one out|does ?n.?t belong|which does not", re.I)),
    ("CONNECT", re.compile(r"\bconnect\b|what links|have in common|common (?:link|thread|factor)|identify the connect", re.I)),
    ("MCQ", re.compile(r"(?:^|\n)\s*[a-dA-D][\.\)]\s|\bwhich of the following\b|\boption[s]?\b", re.I)),
]
_NUMERIC_Q = re.compile(r"\bhow (?:many|much)\b|\bwhat (?:percentage|number|value|year|price)\b|\bestimate\b", re.I)
_NUMERIC_A = re.compile(r"^[\s\d,.%₹$+\-]+$")

def question_style(text: str, answer: str = "", image_dependent: bool = False) -> str:
    t = text or ""
    if image_dependent and re.search(r"identify|whose logo|which (?:brand|company).{0,20}(?:logo|ad)|which logo|name the", t, re.I):
        return "VISUAL_ID"
    for name, pat in _STYLE_PATTERNS:
        if pat.search(t):
            return name
    if _NUMERIC_Q.search(t) or _NUMERIC_A.match(str(answer).strip()):
        return "NUMERIC"
    return "STANDARD"

def expand(tokens: List[str]) -> Counter:
    """Return a weighted bag of query terms: originals weight 1.0, expansions 0.4."""
    bag: Counter = Counter()
    for t in tokens:
        bag[t] += 1.0
    text = " ".join(tokens)
    for key, extra in SYNONYMS.items():
        if key in tokens or (" " in key and key in text):
            for e in extra:
                for et in tokenize(e):
                    bag[et] = max(bag[et], 0.4)
    return bag

class Index:
    def __init__(self, questions: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.q = questions
        self.k1, self.b = k1, b
        self.docs: List[Counter] = []
        self.len: List[int] = []
        self.style: List[str] = []
        df: Counter = Counter()
        for item in questions:
            parts = [item.get("question_text", ""), item.get("answer", ""),
                     " ".join(_kw(item)), item.get("subtopic_l2") or "",
                     " ".join(item.get("secondary_l2") or []), item.get("search_summary") or ""]
            # keywords/answer/subtopic repeated so they weigh more than body prose
            toks = tokenize(" ".join(parts)) + tokenize(" ".join(_kw(item))) \
                   + tokenize(item.get("answer", "")) + tokenize(item.get("subtopic_l2") or "")
            c = Counter(toks)
            self.docs.append(c)
            self.len.append(sum(c.values()))
            self.style.append(item.get('question_style') or question_style(item.get('question_text',''), item.get('answer',''), bool(item.get('image_dependent'))))
            for term in c:
                df[term] += 1
        self.N = len(questions)
        self.avgdl = (sum(self.len) / self.N) if self.N else 0.0
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def _bm25(self, i: int, qbag: Counter) -> float:
        c, dl = self.docs[i], self.len[i]
        s = 0.0
        for term, qw in qbag.items():
            tf = c.get(term, 0)
            if not tf:
                continue
            idf = self.idf.get(term, 0.0)
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            s += qw * idf * (tf * (self.k1 + 1)) / denom
        return s

    def search(self, query: str, filters: Optional[Dict[str, Any]] = None,
               top_k: int = 20) -> List[Dict[str, Any]]:
        filters = filters or {}
        qbag = expand(tokenize(query))
        # --- structured filters: hard gates that a keyword match can't override ---
        def passes(idx: int, item: Dict[str, Any]) -> bool:
            if filters.get("exclude_image") and item.get("image_dependent"):
                return False
            geo = filters.get("india_international")
            if geo and item.get("india_international") not in (geo, "MIXED"):
                return False
            if filters.get("evergreen_only") and item.get("shelf_life") == "TIME_SENSITIVE":
                return False
            if filters.get("school_safe") and item.get("sensitivity") in ("POLITICAL", "MATURE_REFERENCE"):
                return False
            topic = filters.get("topic_l1")
            if topic and item.get("topic_l1") != topic:
                return False
            styles = filters.get("question_style")
            if styles and self.style[idx] not in styles:
                return False
            # reuse history: item["used_in"] is a list of {quiz, audience, year} (or plain strings).
            # exclude a question that was already used at a given venue/quiz, optionally since a year.
            ex_venues = filters.get("exclude_used_in")   # list of quiz/venue/audience names
            since = filters.get("exclude_since_year")    # int or None
            if ex_venues:
                for u in (item.get("used_in") or []):
                    quiz = u.get("quiz") if isinstance(u, dict) else u
                    aud = u.get("audience") if isinstance(u, dict) else None
                    yr = u.get("year") if isinstance(u, dict) else None
                    if (quiz in ex_venues or aud in ex_venues) and (since is None or (yr or 0) >= since):
                        return False
            return True
        scored = []
        for i, item in enumerate(self.q):
            if not passes(i, item):
                continue
            s = self._bm25(i, qbag)
            # small boost if the query words appear in the chosen topic/subtopic
            tl = ((item.get("topic_l1") or "") + " " + (item.get("subtopic_l2") or "")).lower()
            if any(t in tl for t in qbag):
                s += 0.5
            if s > 0:
                scored.append((s, i, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for s, i, it in scored[:top_k]:
            row = dict(it)
            row["score"] = round(s, 3)
            row["question_style"] = it.get("question_style") or self.style[i]
            out.append(row)
        return out


# ---- very light prompt -> (clean query, filters) parser, for a chat-style box ----
def parse_prompt(prompt: str):
    p = prompt.lower()
    filters: Dict[str, Any] = {}
    if re.search(r"\bevergreen|timeless|any year\b", p):
        filters["evergreen_only"] = True
    if re.search(r"\bschool|kids|children|family|safe\b", p):
        filters["school_safe"] = True
    if re.search(r"\bno image|text only|without image|non-?image\b", p):
        filters["exclude_image"] = True
    if re.search(r"\bindia|indian\b", p):
        filters["india_international"] = "IN"
    elif re.search(r"\binternational|global|world\b", p):
        filters["india_international"] = "INTL"
    m = re.search(r"\b(\d{1,3})\b", p)
    count = int(m.group(1)) if m else 20
    # strip filter words so they don't dominate the text match
    q = re.sub(r"\b(\d{1,3}|questions?|quiz|round|evergreen|india|indian|international|global|"
               r"school|safe|family|kids|children|no image|text only|on|about|a|the|of|give me|pull|me)\b",
               " ", p)
    q = re.sub(r"[^a-z0-9 ]", " ", q)
    return re.sub(r"\s+", " ", q).strip(), filters, count
