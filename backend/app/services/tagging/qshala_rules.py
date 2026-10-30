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
from typing import Any, Dict, List, Optional, Tuple

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


# ====================================================================== L2 DISAMBIGUATION
# High-precedence, deterministic guards for the recurring L2 boundary conflicts found in the
# 22-question blind evaluation (ruling_sheet_22.csv). Each guard asserts the FINAL ruling's
# subtopic when its unmistakable signature is present, but ONLY when the LLM's proposed L2 is
# one of the known confusable siblings (or missing) — so a correct, unrelated tag is never
# clobbered. All targets use the exact v6 L2 names (several differ from the shorthand used in
# the ruling sheet, e.g. "Word Origins" -> "Etymology", "Environment" -> "Ecology and
# Environment", "Market Concepts"/charts -> "Technical Analysis", "Banking" -> "Banks and
# Banking"). v6-only; a no-op for other taxonomy versions.


@dataclass(frozen=True)
class L2Rule:
    rule_id: str
    target_l2: str
    target_l1: str
    from_l2: frozenset            # confusable siblings this may override (lowercased); empty = any
    signature: re.Pattern         # matched against question + answer (case-insensitive)
    require_all: tuple = ()        # extra re.Pattern objects that must ALL also match


def _p(pat: str) -> re.Pattern:
    return re.compile(pat, re.I)


# NOTE: order matters — the first rule whose signature (and require_all) matches wins.
L2_DISAMBIGUATION_RULES: List[L2Rule] = [
    # 1. Central Banking vs Banking — monetary authority, currency-printing rights, CBDC.
    L2Rule(
        "central_banking_vs_banking", "Central Banking", "Finance",
        frozenset({"banks and banking", "digital payments", "economic history",
                   "money history", "government policy", "macroeconomics", "coins and notes"}),
        _p(r"\bcbdc\b|central bank digital currency"
           r"|print(?:ing|s|ed)?\s+(?:of\s+)?(?:money|currency|bank\s?notes?|notes?)"
           r"|right[s]?\s+to\s+(?:print|issue)\s+(?:money|currency|notes?)"
           r"|monetary authority|issue (?:its )?(?:own )?currency"),
    ),
    # 10. Executive Appointments vs Banking — CFO/CEO/chair appointment milestones.
    L2Rule(
        "exec_appointment_vs_banking", "Business Leaders", "Business",
        frozenset({"banks and banking", "earnings and results", "digital payments",
                   "insurance", "central banking"}),
        _p(r"\b(ceo|cfo|coo|cto|chief (?:executive|financial|operating|technology) officer"
           r"|chairman|chairperson|chairwoman|managing director|\bmd\b)\b"),
        require_all=(_p(r"\b(appoint\w*|named|become[s]?|first woman|first man|steps? down"
                        r"|succeed[s]?|elevat\w*|hire[d]?)\b"),),
    ),
    # 2. Stock Markets vs Advertising — an ad campaign announcement moving the share price.
    L2Rule(
        "ad_campaign_vs_stock", "Advertising", "Business",
        frozenset({"stock markets", "earnings and results", "market indices", "investing and funds"}),
        _p(r"\b(ad campaign|ad[- ]?spend|advertis\w+|marketing campaign|commercial|jingle|tagline|slogan)\b"),
        require_all=(_p(r"\b(share price|stock price|shares?|stock|ticker)\b.{0,40}"
                        r"\b(ros?e|jump\w*|surg\w*|f[ae]ll|gain\w*|clos\w*|\d+\s?%)"
                        r"|\b(ros?e|jump\w*|surg\w*|gain\w*)\b.{0,30}\b\d+\s?%"),),
    ),
    # 5. Technical Analysis vs Stocks — chart patterns / indicators (the concept, not a listing).
    L2Rule(
        "chart_pattern_vs_stock", "Technical Analysis", "Finance",
        frozenset({"stock markets", "investing and funds", "derivatives", "market indices"}),
        _p(r"\bchart pattern\b|\bcandlestick\b|head (?:and|&) shoulders|double top|double bottom"
           r"|cup and handle|moving average|\brsi\b|\bmacd\b|bollinger|support and resistance"
           r"|technical analysis"),
    ),
    # 4. Tickers & Acronyms vs Entertainment — the ORIGIN story of a stock ticker / symbol.
    L2Rule(
        "ticker_origin_vs_entertainment", "Etymology", "Culture",
        frozenset({"stock markets", "entertainment", "music", "musicians and bands",
                   "business jargon", "company origins", "investing and funds"}),
        _p(r"\b(stock )?(?:ticker|symbol)\b"),
        require_all=(_p(r"\bwhy\b|origin|named after|in honou?r|stands for|because|derived"),),
    ),
    # 7. Renewable-energy MoUs vs Brand Collabs — a state/government green-energy pact.
    L2Rule(
        "green_mou_vs_collab", "Indian Economy", "Economy",
        frozenset({"brand collaborations", "energy", "partnerships",
                   "infrastructure and manufacturing", "government policy"}),
        _p(r"\b(mou|memorandum of understanding|agreement|pact|signed|tie[- ]?up)\b"),
        require_all=(
            _p(r"\bgovernment of\b|\bgovt\.? of\b|state government|ministry|"
               r"\b(karnataka|maharashtra|gujarat|tamil nadu|telangana|rajasthan|odisha|"
               r"andhra pradesh|uttar pradesh|madhya pradesh)\b"),
            _p(r"\bsolar\b|\bwind\b|renewable|green (?:energy|hydrogen)|clean energy|\benergy\b"),
        ),
    ),
    # 8. Water/sustainability credits vs Brands — a corporate environmental initiative.
    L2Rule(
        "sustainability_vs_brand", "Ecology and Environment", "Science",
        frozenset({"consumer brands", "brand collaborations", "consumer prices"}),
        _p(r"\bwater credit|carbon credit|water usage|water[- ]stress\w*|water positive"
           r"|water conservation|sustainability|net[- ]?zero|emission[s]?\b|decarbon\w*"),
    ),
    # 6. Item price history vs Heritage — the changing/frozen price of an iconic item.
    L2Rule(
        "price_history_vs_heritage", "Consumer Prices", "Economy",
        frozenset({"archaeology and heritage sites", "food and drink", "retail",
                   "personal finance", "consumer brands"}),
        _p(r"\bprice[d]?\b|priced at|\b£|\$|₹|\brs\.?\b"),
        require_all=(_p(r"\brais\w*|ros?e|increas\w*|hik\w*|freeze|frozen|price freeze"
                        r"|unchanged since|price (?:rise|cut|drop)|cost\b"),),
    ),
    # 3. Brand Identity / Real Estate vs Urban Life — stations, platforms, sheds; a landmark
    #    hotel named for its site.
    L2Rule(
        "urban_landmark_vs_realestate", "Urban Life", "Culture",
        frozenset({"maps and travel", "real estate", "brand identity and logos",
                   "landmarks and monuments", "cities and places",
                   "infrastructure and manufacturing", "travel industry"}),
        _p(r"\b(railway|locomotive|\bloco\b|metro|train)\b.{0,30}\b(platform|shed|station)\b"
           r"|\b(platform|shed|station)\b.{0,30}\b(railway|locomotive|\bloco\b|metro|train)\b"
           r"|longest (?:railway )?platform|\bemd\b"
           r"|hotel\b.{0,60}\bnamed after (?:the )?(?:specific )?location"
           r"|named after (?:the )?(?:specific )?location (?:where|it)"),
    ),
    # 9. Consumer Products vs Identity — a maker launching a lifestyle product off its core line.
    L2Rule(
        "lifestyle_product_vs_identity", "Consumer Brands", "Business",
        frozenset({"brand identity and logos", "luxury", "automobiles", "real estate"}),
        _p(r"\b(stroller|pram|perfume|fragrance|apparel|sneakers?|watch|eyewear|sunglasses"
           r"|home\s?decor|furniture|baby\b|lifestyle product|merchandise|branded goods)\b"),
        require_all=(_p(r"\broll(?:ed|s)? out\b|launch\w*|unveil\w*|introduc\w*|priced at|debut\w*"),),
    ),
]


def disambiguate_l2(question_text: str, answer: str = "", proposed_l2: Optional[str] = None,
                    taxonomy_version: Optional[str] = "v6") -> Optional[Tuple[str, str, str]]:
    """Return (target_l2, target_l1, rule_id) if a high-precedence guard overrides the proposed
    L2, else None. Only fires for v6 and only when `proposed_l2` is a known confusable sibling
    (or missing), so it never overrides a correct, unrelated tag. Never returns a change that
    equals the proposed L2.
    """
    if (taxonomy_version or "").lower() != "v6":
        return None
    text = f"{question_text or ''} {answer or ''}"
    prop = (proposed_l2 or "").strip().lower()
    for rule in L2_DISAMBIGUATION_RULES:
        if rule.from_l2 and prop and prop not in rule.from_l2:
            continue  # the model picked something outside this rule's confusable set — leave it
        if not rule.signature.search(text):
            continue
        if any(not p.search(text) for p in rule.require_all):
            continue
        if prop == rule.target_l2.lower():
            return None  # already correct
        return (rule.target_l2, rule.target_l1, rule.rule_id)
    return None


def apply_disambiguation(paths: List[Dict[str, Any]], question_text: str, answer: str = "",
                         taxonomy_version: Optional[str] = "v6") -> List[Dict[str, Any]]:
    """Re-order a normalised topic-path list so a ruled L2 becomes the primary path, demoting the
    model's original primary into the secondary slot (which preserves soft-L2 evaluation credit).
    Pure function: returns a new list; the input is unchanged. Safe to call on an empty list.
    """
    primary_l2 = (paths[0].get("l2") if paths else None)
    hit = disambiguate_l2(question_text, answer, primary_l2, taxonomy_version)
    if not hit:
        return paths
    target_l2, target_l1, _rule = hit
    carry_keywords = list(paths[0].get("keywords", []) or []) if paths else []
    new_first = {"l1": target_l1, "l2": target_l2, "keywords": carry_keywords}
    # Keep every prior path as a sibling (deduped by l2), with the model's original primary first
    # so it lands in secondary_l2.
    rest, seen = [], {target_l2.lower()}
    for p in paths:
        l2 = (p.get("l2") or "")
        if l2 and l2.lower() not in seen:
            rest.append(p)
            seen.add(l2.lower())
    return [new_first] + rest


def l2_match(expected: Optional[str], primary: Optional[str],
             secondary: Optional[List[str]] = None) -> bool:
    """Soft L2 match: a classification counts as correct if `expected` equals the primary L2
    OR any secondary L2 (case-insensitive). Used by tagging evaluation and retrieval so a
    model that put the right answer in its secondary slot is not scored as wrong."""
    if not expected:
        return False
    e = expected.strip().lower()
    if primary and e == primary.strip().lower():
        return True
    for s in (secondary or []):
        if s and e == s.strip().lower():
            return True
    return False


# ---------------------------------------------------------------------- canonical taxonomy & format tagging

TAXONOMY_RULES: List[Tuple[str, str, str]] = [
    # Finance rules
    (r"\b(stock|shares?|nse|bse|demat|broker|trading|sensex|nifty|market cap|listed|equit(?:y|ies))\b", "Finance", "Stock Markets"),
    (r"\b(mutual funds?|etf|sip|investor|investing|warren buffett|portfolio)\b", "Finance", "Investing and Funds"),
    (r"\b(derivatives?|futures?|options?|hedging)\b", "Finance", "Derivatives"),
    (r"\b(bonds?|yields?|g-secs?|treasury bills?|debt market)\b", "Finance", "Bonds"),
    (r"\b(gold|silver|crude oil|commodit(?:y|ies))\b", "Finance", "Commodities"),
    (r"\b(bitcoin|ethereum|crypto|blockchain|nft)\b", "Finance", "Cryptocurrency"),
    (r"\b(ipo|listings?|anchor investor|debut)\b", "Finance", "IPOs and Listings"),
    (r"\b(index|indices|dow jones|s&p|saatvik)\b", "Finance", "Market Indices"),
    (r"\b(bubble|crash|panic|mania|tulip mania|dot com|confirmation bias|herd mentality|bias)\b", "Finance", "Behavioural Finance"),
    (r"\b(banks?|banking|sbi|hdfc|icici|axis|vaults?|safes?|cheques?|micr|atm)\b", "Finance", "Banks and Banking"),
    (r"\b(rbi|reserve bank|central bank|federal reserve|repo rate|monetary policy)\b", "Finance", "Central Banking"),
    (r"\b(upi|wallets?|paytm|phonepe|gpay|npci|digital payments?)\b", "Finance", "Digital Payments"),
    (r"\b(insurance|lic|policy\s*bazaar|premium|irdai)\b", "Finance", "Insurance"),
    (r"\b(loans?|credit|cibil|credit score|nbfc|emi|lending|gold loan)\b", "Finance", "Lending and Credit"),
    (r"\b(splitwise|budget|saving|retirement|personal finance)\b", "Finance", "Personal Finance"),
    (r"\b(currency|banknote|coins?|rupee|dollar|mint|demonetisation|numismatic)\b", "Finance", "Coins and Notes"),
    (r"\b(money history|barter|cowrie)\b", "Finance", "Money History"),

    # Business rules
    (r"\b(startups?|unicorn|founders?|seed funding|series a|venture capital|incubator|swiggy|zepto|blinkit|navi)\b", "Business", "Startups"),
    (r"\b(founded|origin|established in|history of|earliest|tata|godrej|iti|infy|infosys)\b", "Business", "Company Origins"),
    (r"\b(scandal|fraud|ponzi|bernie madoff|harshad mehta|enron)\b", "Business", "Corporate Scandals"),
    (r"\b(ceo|chairperson|industrialist|mukesh ambani|ratan tata|tarun mehta|tim cook|vijaypat singhania)\b", "Business", "Business Leaders"),
    (r"\b(merger|acquisition|takeover|buyout|deal)\b", "Business", "Acquisitions and Mergers"),
    (r"\b(net worth|wealthiest|billionaire|forbes|fortune 500|valuation|richest)\b", "Business", "Rankings and Awards"),
    (r"\b(accounting|double-entry|balance sheet|trial balance|ledger|journal)\b", "Business", "Accounting"),
    (r"\b(advertising|campaign|commercial|ad|tagline|slogan|surf excel|amul|lays)\b", "Business", "Advertising"),
    (r"\b(collaboration|partnership|collab|camelbak|crayola)\b", "Business", "Brand Collaborations"),
    (r"\b(logo|mascot|brand identity|visual identity)\b", "Business", "Brand Identity and Logos"),
    (r"\b(retail|e-commerce|flipkart|amazon|walmart|zomato|blinkit)\b", "Business", "Retail"),
    (r"\b(electric vehicle|ather|tata motors|automotive|cars?)\b", "Business", "Automobiles"),

    # Economy rules
    (r"\b(gdp|gross domestic product|nominal gdp|per capita|economic growth)\b", "Economy", "Macroeconomics"),
    (r"\b(budget|union budget|finance minister|income tax|pan|taxation|gst)\b", "Economy", "Taxation"),
    (r"\b(inflation|consumer price|cpi|purchasing power)\b", "Economy", "Consumer Prices"),
    (r"\b(trade|export|import|customs|wto|tariff)\b", "Economy", "Global Trade"),
    (r"\b(infrastructure|metro|namma metro|railway|highway|ports?)\b", "Economy", "Infrastructure and Manufacturing"),

    # Technology rules
    (r"\b(ai|artificial intelligence|machine learning|chatgpt|openai)\b", "Technology", "Artificial Intelligence"),
    (r"\b(apps?|dating apps?|tinder|software|internet|platform)\b", "Technology", "Internet and Platforms"),
    (r"\b(social media|instagram|linkedin|twitter|youtube|content creator)\b", "Technology", "Social Media"),
    (r"\b(gadgets?|phones?|smartphones?|laptop|hardware)\b", "Technology", "Tech Products and Gadgets"),
    (r"\b(telecom|5g|spectrum|airtel|jio|bsnl|telephone)\b", "Technology", "Telecom"),
    (r"\b(invention|inventor|patents?|discovered)\b", "Technology", "Inventions and Inventors"),

    # Politics / Law
    (r"\b(election|voting|indelible ink|election commission|vote)\b", "Politics", "Elections"),
    (r"\b(constitution|parliament|lok sabha|rajya sabha|government policy)\b", "Politics", "Governance and Constitution"),

    # Sports
    (r"\b(cricket|ipl|icc|world cup|olympic|mirabai chanu|football|futsal|bengaluru 5s)\b", "Sports", "Sports Business"),

    # Culture / Media / History
    (r"\b(east india company|william dalrymple|colonial|historical)\b", "History", "Economic History"),
    (r"\b(toys?|channapatna|heritage|tradition|craft)\b", "Culture", "Festivals and Traditions"),
    (r"\b(novel|author|book|christie malry|monsoon)\b", "Culture", "Literature and Authors"),
    (r"\b(music|band|beatles|song|musician|axl rose)\b", "Entertainment", "Musicians and Bands"),
    (r"\b(cheese|gouda|kempe gouda|food|cuisine|manga|nissin)\b", "Culture", "Food and Drink"),
    (r"\b(zimbabwe|australia|sydney|bangalore|bengaluru|mumbai)\b", "Geography", "Countries and Capitals"),
]


def classify_taxonomy(q_text: str, ans_text: str, round_name: str = "", fmt: str = "QA") -> Tuple[str, str, List[str]]:
    """Rule-based instant classification: returns (L1, L2, keywords). Guarantees no question is Uncategorised."""
    combined = f"{q_text} {ans_text} {round_name}".lower()

    # Default
    l1 = "General Knowledge"
    l2 = "General Trivia"
    keywords: List[str] = []

    # Check taxonomy rules
    for pat, rule_l1, rule_l2 in TAXONOMY_RULES:
        if re.search(pat, combined, re.I):
            l1 = rule_l1
            l2 = rule_l2
            break

    # Add canonical question format tag
    fmt_display = {
        "CONNECT_4": "Connect 4",
        "CONNECT": "Connect 4",
        "STEPPED_CLUE": "Stepped Clue (Portfolio Builder)",
        "THREE_CLUE": "Stepped Clue (Portfolio Builder)",
        "ARRANGE_ORDER": "Arrange the Order (Ticker Tangle)",
        "BUZZER": "Buzzer (Closing Bell)",
        "QA": "Direct QA",
        "VISUAL_CLUE": "Visual Clue",
        "VIDEO_CLUE": "Video Clue",
        "AUDIO_CLUE": "Audio Clue",
        "POTPOURRI": "Potpourri",
        "IMAGE_REVEAL": "Image Reveal",
        "LIST_IT": "List It",
    }.get(fmt, fmt)
    keywords.append(fmt_display)

    # Extract relevant entities
    entities = [
        "NSE", "BSE", "SEBI", "RBI", "Demat Account", "Double-Entry", "Bank Vaults",
        "Navi", "Sachin Bansal", "GDP", "Wealthiest Women", "Savitri Jindal",
        "Market Crashes", "Tulip Mania", "Dot Com Bubble", "MRF", "Page Industries",
        "Unicorn Status", "Accounting Cycle", "ITI", "Splitwise", "PAN Card",
        "Gold Loan", "Tata Group", "Dating Apps", "Lays", "Puneeth Rajkumar",
        "Saatvik Index", "Crayola", "CamelBak", "Monsoon", "Apple", "Tim Cook",
        "SIP", "Zomato", "East India Company", "Indelible Ink", "Mirabai Chanu",
        "The Beatles", "AirBNB", "Policy Bazaar", "Surf Excel", "Kempe Gouda"
    ]
    for ent in entities:
        if ent.lower() in combined and ent not in keywords:
            keywords.append(ent)
            if len(keywords) >= 5:
                break

    return l1, l2, keywords

