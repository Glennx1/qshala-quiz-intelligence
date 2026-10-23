"""Deterministic signals the tagger extracts before (and in parallel with) any LLM call.

Rules handle the things that are facts, not opinions: a city name is a city, a year is a
year, a Mumbai-police mention is Mumbai. Keeping these out of the LLM means fewer tokens
and more consistency; it also gives the tagger a cheap second signal to agree or disagree
with the LLM's output.

Everything here is pure Python. No API calls, no database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------- dictionaries

# City -> (geo_region, india_international) for India; cities outside IN get india_international='INTL'.
CITIES_IN: Dict[str, str] = {
    "bengaluru": "South India", "bangalore": "South India",
    "chennai": "South India", "hyderabad": "South India", "kochi": "South India",
    "thiruvananthapuram": "South India", "mysuru": "South India", "mysore": "South India",
    "coimbatore": "South India", "mangaluru": "South India", "mangalore": "South India",
    "mumbai": "West India", "pune": "West India", "ahmedabad": "West India",
    "surat": "West India", "nagpur": "West India", "nashik": "West India",
    "goa": "West India", "panaji": "West India",
    "delhi": "North India", "new delhi": "North India", "gurugram": "North India",
    "gurgaon": "North India", "noida": "North India", "jaipur": "North India",
    "chandigarh": "North India", "lucknow": "North India",
    "kolkata": "East India", "guwahati": "East India", "bhubaneswar": "East India",
    "patna": "East India", "ranchi": "East India",
    "indore": "Central India", "bhopal": "Central India", "raipur": "Central India",
}
CITIES_INTL: Dict[str, str] = {
    "new york": "North America", "san francisco": "North America", "silicon valley": "North America",
    "london": "Europe", "paris": "Europe", "berlin": "Europe", "zurich": "Europe",
    "tokyo": "Asia", "singapore": "Asia", "hong kong": "Asia", "shanghai": "Asia",
    "dubai": "Middle East", "sydney": "Oceania",
}

# Brand/entity mentions that strongly imply an L1 topic. The tagger uses these as a nudge,
# not a final answer — the LLM still picks the exact L2.
BRAND_TO_L1: Dict[str, str] = {
    # Banks / payments
    "zerodha": "Markets & Investing", "groww": "Markets & Investing", "upstox": "Markets & Investing",
    "nse": "Markets & Investing", "bse": "Markets & Investing", "sebi": "Markets & Investing",
    "hdfc bank": "Banking, Payments & Insurance", "sbi": "Banking, Payments & Insurance",
    "icici bank": "Banking, Payments & Insurance", "axis bank": "Banking, Payments & Insurance",
    "kotak": "Banking, Payments & Insurance", "karnataka bank": "Banking, Payments & Insurance",
    "upi": "Banking, Payments & Insurance", "npci": "Banking, Payments & Insurance",
    "paytm": "Banking, Payments & Insurance", "phonepe": "Banking, Payments & Insurance",
    "gpay": "Banking, Payments & Insurance", "google pay": "Banking, Payments & Insurance",
    "lic": "Banking, Payments & Insurance", "rbi": "Banking, Payments & Insurance",
    # Tech
    "openai": "Technology & Digital", "anthropic": "Technology & Digital",
    "nvidia": "Technology & Digital", "google": "Technology & Digital",
    "microsoft": "Technology & Digital", "apple": "Technology & Digital",
    "meta": "Technology & Digital", "facebook": "Technology & Digital",
    # Sports / entertainment
    "ipl": "Sports & Entertainment Business", "bcci": "Sports & Entertainment Business",
    "fifa": "Sports & Entertainment Business", "netflix": "Sports & Entertainment Business",
    "disney": "Sports & Entertainment Business", "jiocinema": "Sports & Entertainment Business",
    # Economy / policy
    "opec": "Economy & Policy", "rbi": "Economy & Policy", "wto": "Economy & Policy",
    "imf": "Economy & Policy", "world bank": "Economy & Policy",
}

# Same nudges for the v6 theme names (Finance, Business, Economy, Technology, Sports, Entertainment...).
BRAND_TO_L1_V6: Dict[str, str] = {
    "zerodha": "Finance", "groww": "Finance", "upstox": "Finance", "nse": "Finance", "bse": "Finance",
    "sebi": "Finance", "hdfc bank": "Finance", "sbi": "Finance", "icici bank": "Finance", "axis bank": "Finance",
    "kotak": "Finance", "karnataka bank": "Finance", "upi": "Finance", "npci": "Finance", "paytm": "Finance",
    "phonepe": "Finance", "gpay": "Finance", "google pay": "Finance", "lic": "Finance", "rbi": "Finance",
    "openai": "Technology", "anthropic": "Technology", "nvidia": "Technology", "google": "Technology",
    "microsoft": "Technology", "apple": "Technology", "meta": "Technology", "facebook": "Technology",
    "ipl": "Sports", "bcci": "Sports", "fifa": "Sports",
    "netflix": "Entertainment", "disney": "Entertainment", "jiocinema": "Entertainment",
    "opec": "Economy", "wto": "Economy", "imf": "Economy", "world bank": "Economy",
}

# Patterns that mark a question as TIME_SENSITIVE (dated reference).
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
CURRENT_YEAR_WINDOW = 3                                      # Any year within 3y of today → TIME_SENSITIVE.

# Patterns that mark MATURE_REFERENCE sensitivity.
MATURE_RE = re.compile(
    r"\b(fraud|scam|cybercrime|cyber(?:crime|-safety)|helpline\s*1930|dowry|rape|murder|drug|narcotic|violence|arrest|jail)\b",
    re.I,
)

# Image-dependent hint — question text relies on an image we're not sending the LLM.
IMAGE_HINT_RE = re.compile(
    r"\b(this|the|these)\s+(photo|image|picture|logo|ad|hoarding|meme|map|poster|collection|book\s+title|structure|building|page)\b"
    r"|in the image|shown (here|alongside)|pictured|seen in the (image|picture)|marked in these|blanked out|\bthis is an ad\b",
    re.I,
)


# ---------------------------------------------------------------------- output

@dataclass
class RuleSignals:
    """What the rule engine extracted from a question. Everything is optional — only confident hits are returned."""
    city_name: Optional[str] = None
    geo_region: Optional[str] = None
    india_international: Optional[str] = None
    brand_hints_l1: List[str] = field(default_factory=list)
    shelf_life: Optional[str] = None
    sensitivity: Optional[str] = None
    image_dependent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], False)}


# ---------------------------------------------------------------------- the extractor

def _find_city(haystack_lc: str) -> Optional[tuple[str, str, str]]:
    """Returns (display_city, geo_region, india_international) for the first match, or None."""
    for city, region in CITIES_IN.items():
        if re.search(rf"\b{re.escape(city)}\b", haystack_lc):
            return (city.title(), region, "IN")
    for city, region in CITIES_INTL.items():
        if re.search(rf"\b{re.escape(city)}\b", haystack_lc):
            return (city.title(), region, "INTL")
    return None


def extract(question_text: str, answer: str = "", explanation: str = "",
            taxonomy_version: Optional[str] = None) -> RuleSignals:
    """Pull every deterministic signal we can from the raw text.

    Nothing here will contradict the LLM later unless the two disagree on a rule hit —
    that disagreement is a routing signal, not a correction.
    """
    text = f"{question_text} {answer} {explanation}".strip()
    lc = text.lower()
    out = RuleSignals()

    # City / geography.
    hit = _find_city(lc)
    if hit:
        out.city_name, out.geo_region, out.india_international = hit

    # Brand-to-L1 nudges.
    seen_l1: List[str] = []
    brand_map = BRAND_TO_L1_V6 if (taxonomy_version or "").lower() == "v6" else BRAND_TO_L1
    for brand, l1 in brand_map.items():
        if re.search(rf"\b{re.escape(brand)}\b", lc) and l1 not in seen_l1:
            seen_l1.append(l1)
    out.brand_hints_l1 = seen_l1

    # Shelf-life.
    years = [int(y) for y in YEAR_RE.findall(text)]
    this_year = datetime.utcnow().year
    if years:
        if any(this_year - y <= CURRENT_YEAR_WINDOW for y in years):
            out.shelf_life = "TIME_SENSITIVE"
        else:
            out.shelf_life = "REVIEW_YEARLY"
    # (No positive EVERGREEN rule — absence of a year is not proof of evergreenness. The LLM decides.)

    # Sensitivity.
    if MATURE_RE.search(text):
        out.sensitivity = "MATURE_REFERENCE"

    # Image dependence.
    if IMAGE_HINT_RE.search(question_text) or len(question_text.split()) < 12:
        out.image_dependent = True

    return out
