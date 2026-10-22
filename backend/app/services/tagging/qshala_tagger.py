"""QShala-domain tagger: Zerodha Varsity Quiz business/finance/culture questions.

Flow for a single question:
  1. extract(rules)                → RuleSignals (free, no tokens)
  2. duplicate_check(question_text)→ existing confirmed tag inherited, if any (free)
  3. llm_tag(question + rules)     → full QShala tag payload (one Gemini call, enum-constrained JSON)
  4. route(rules, llm_output)      → status: 'confirmed' | 'draft' + a short reason

Every output is a QshalaTag row with provenance:
  source='LLM' (or 'HUMAN' / 'RULE'), model_version, taxonomy_version.
A confirmed row never overwrites a human-confirmed row: `promote` checks and refuses.

The tagger uses whichever Gemini model is in settings.QSHALA_TAGGER_MODEL (default:
'gemini-3.5-flash-lite'); the heavier generator model stays on settings.GEMINI_MODEL.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.qshala_tag import QshalaTag, QshalaTagChange
from backend.app.services.ai.gemini_provider import GeminiLLMProvider
from backend.app.services.tagging import qshala_rules

logger = logging.getLogger(__name__)

TAXONOMY_PATH = Path(__file__).resolve().parent / "qshala_taxonomy_v5_1.json"
TAXONOMY_VERSION = "v5.1"

ENTITY_TYPES = ["COMPANY", "PERSON", "TERM", "PRODUCT_OR_OBJECT", "BOOK",
                "ORGANISATION", "POLICY", "NUMBER", "PLACE", "EVENT"]
GEOGRAPHY = ["IN", "INTL", "MIXED"]
SHELF_LIFE = ["EVERGREEN", "REVIEW_YEARLY", "TIME_SENSITIVE"]
SENSITIVITY = ["NONE", "POLITICAL", "MATURE_REFERENCE"]
FIT = ["good", "weak", "none"]


# ---------------------------------------------------------------------- taxonomy

_TAX_CACHE: Dict[str, Any] = {}


def set_taxonomy_version(version: str) -> None:
    """Dynamically switch taxonomy version (v3, v4, v5, v5.1)."""
    global TAXONOMY_PATH, TAXONOMY_VERSION
    v_clean = version.strip().lower()
    if v_clean in ("v5.1", "5.1", "v5_1"):
        TAXONOMY_PATH = Path(__file__).resolve().parent / "qshala_taxonomy_v5_1.json"
        TAXONOMY_VERSION = "v5.1"
    elif v_clean in ("v5", "5"):
        TAXONOMY_PATH = Path(__file__).resolve().parent / "qshala_taxonomy_v5.json"
        TAXONOMY_VERSION = "v5"
    elif v_clean in ("v4", "4"):
        TAXONOMY_PATH = Path(__file__).resolve().parent / "qshala_taxonomy_v4.json"
        TAXONOMY_VERSION = "v4"
    elif v_clean in ("v3", "3"):
        TAXONOMY_PATH = Path(__file__).resolve().parent / "qshala_taxonomy_v3.json"
        TAXONOMY_VERSION = "v3"
    else:
        raise ValueError(f"Unknown taxonomy version: {version}")
    _TAX_CACHE.clear()


def _load_taxonomy() -> Dict[str, Any]:
    """Loaded once per process. The JSON file has: {level1: [{name, level2: [{name, description}]}]}."""
    if _TAX_CACHE:
        return _TAX_CACHE
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    l2_names: List[str] = []
    l1_names: List[str] = []
    l2_to_l1: Dict[str, str] = {}
    for grp in data["level1"]:
        l1 = grp["name"]
        l1_names.append(l1)
        for item in grp["level2"]:
            l2_names.append(item["name"])
            l2_to_l1[item["name"]] = l1
    _TAX_CACHE["raw"] = data
    _TAX_CACHE["l1"] = l1_names
    _TAX_CACHE["l2"] = l2_names
    _TAX_CACHE["l2_to_l1"] = l2_to_l1
    return _TAX_CACHE


def _taxonomy_prompt_block() -> str:
    tax = _load_taxonomy()["raw"]
    lines: List[str] = []
    for grp in tax["level1"]:
        lines.append(f"{grp['name']}:")
        for item in grp["level2"]:
            lines.append(f"  - {item['name']}: {item.get('description', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- prompt + schema

SYSTEM_PROMPT_TEMPLATE = """You tag quiz questions for QShala, a quiz company in Bangalore. The questions come from live quiz decks (Zerodha Varsity Quiz): business, finance, brands, companies, current affairs and culture, mostly India-focused. Return the fields below for each question.

subtopic_l2: choose exactly ONE subtopic from the list, by what the question is ABOUT (its subject), not by where it is set or how it is asked. A bank's logo story is Brand Heritage & Identity; a bank's founding story is Financial History or Founder Stories. When two fit, choose the one a quizmaster would search for first.
secondary_l2: up to 3 other subtopics that also apply, or an empty list.
keywords_l3: 4 to 7 search keywords in Title Case, most specific first — named people, companies, products, places, key terms, and the answer; then one or two broader concept words. No filler words. Do not include facts the question does not support.
entity_type: what kind of thing the ANSWER is.
india_international: IN if the subject is India-centred, INTL if it is outside India, MIXED if both.
shelf_life: EVERGREEN = true in any year; REVIEW_YEARLY = facts or figures that can drift (fees, statistics, ongoing products); TIME_SENSITIVE = tied to a recent event or date.
sensitivity: POLITICAL if it touches contested politics or geopolitics; MATURE_REFERENCE if it mentions crime, drugs, violence or similar; otherwise NONE.
fit: good = a subtopic fits well; weak = the best available fit is imperfect; none = nothing fits.
search_summary: one sentence of at most 25 words saying what the question is about, naming the key entities and the answer.
If the question refers to an image or video you cannot see, tag from the text you have and set fit to weak.

Subtopics, grouped by topic:
"""


def _system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE + _taxonomy_prompt_block()


def _tag_schema() -> Dict[str, Any]:
    """OpenAPI-style schema for Gemini's response_schema. Upper-case types; strict enums.

    We constrain the subtopic to the 41 L2 names so the model can't invent one.
    """
    tax = _load_taxonomy()
    return {
        "type": "OBJECT",
        "properties": {
            "subtopic_l2": {"type": "STRING", "enum": tax["l2"]},
            "secondary_l2": {"type": "ARRAY", "items": {"type": "STRING", "enum": tax["l2"]}, "maxItems": 3},
            "keywords_l3": {"type": "ARRAY", "items": {"type": "STRING"}, "minItems": 4, "maxItems": 7},
            "entity_type": {"type": "STRING", "enum": ENTITY_TYPES},
            "india_international": {"type": "STRING", "enum": GEOGRAPHY},
            "shelf_life": {"type": "STRING", "enum": SHELF_LIFE},
            "sensitivity": {"type": "STRING", "enum": SENSITIVITY},
            "fit": {"type": "STRING", "enum": FIT},
            "search_summary": {"type": "STRING"},
        },
        "required": ["subtopic_l2", "keywords_l3", "entity_type", "india_international",
                     "shelf_life", "sensitivity", "fit", "search_summary"],
    }


def _user_prompt(question_text: str, answer: str, rules: qshala_rules.RuleSignals) -> str:
    hints: List[str] = []
    if rules.brand_hints_l1:
        hints.append(f"Rule hints — likely topic(s): {', '.join(rules.brand_hints_l1)}. Confirm or override from the question itself.")
    if rules.image_dependent:
        hints.append("Rule hint — this question appears to depend on an image that is NOT shown. Tag from text and set fit=weak.")
    hint_block = ("\n" + "\n".join(hints)) if hints else ""
    return f"QUESTION: {question_text}\nANSWER: {answer}{hint_block}"


# ---------------------------------------------------------------------- the core call

def _canonical_hash(question_text: str, answer: str) -> str:
    norm = re.sub(r"\s+", " ", f"{question_text}||{answer}".lower()).strip()
    return hashlib.sha256(norm.encode()).hexdigest()[:32]


async def _call_llm(provider: GeminiLLMProvider, model: str, question_text: str,
                    answer: str, rules: qshala_rules.RuleSignals,
                    thinking_level: str = "low") -> Tuple[Dict[str, Any], Dict[str, int], int]:
    """One Gemini call. Returns (parsed_json, usage_dict, latency_ms)."""
    system = _system_prompt()
    user = _user_prompt(question_text, answer, rules)
    schema = _tag_schema()
    t0 = time.perf_counter()
    data, usage = await provider.generate_json_schema(
        prompt=user,
        schema=schema,
        system_instruction=system,
        model=model,
        thinking_level=thinking_level,
        temperature=0.0,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return data, usage, latency_ms


# ---------------------------------------------------------------------- routing

def _route(rules: qshala_rules.RuleSignals, llm: Dict[str, Any]) -> Tuple[str, float, str]:
    """Decide status (confirmed / draft) and a confidence estimate.

    - LLM fit='good' AND no rule conflict → confirmed, 0.90.
    - LLM fit='weak' or fit='none'       → draft, 0.50.
    - Rule geography disagrees with LLM  → draft, 0.60. (route to review.)
    - LLM-only, no rule hits at all      → draft, 0.70.  (reviewer should look.)
    """
    fit = llm.get("fit", "weak")
    reasons: List[str] = []

    if fit in ("weak", "none"):
        return ("draft", 0.50, f"model marked fit={fit}")

    # Geography disagreement is the strongest cheap signal we have.
    if rules.india_international and llm.get("india_international") and rules.india_international != llm["india_international"]:
        reasons.append(f"geography mismatch (rule {rules.india_international} vs LLM {llm['india_international']})")
        return ("draft", 0.60, "; ".join(reasons))

    # Brand-hint agreement is a soft confirmation but not a hard rule — the LLM can override.
    rule_l1s = set(rules.brand_hints_l1 or [])
    llm_l1 = _load_taxonomy()["l2_to_l1"].get(llm.get("subtopic_l2", ""))
    rule_signals_fired = bool(rules.city_name or rules.brand_hints_l1 or rules.shelf_life or rules.sensitivity)

    if rule_signals_fired and (not rule_l1s or llm_l1 in rule_l1s):
        return ("confirmed", 0.90, "LLM fit=good, no rule conflict")
    if not rule_signals_fired:
        return ("draft", 0.70, "no rule signals fired; recommend quick review")

    # Rules fired but L1 doesn't match any brand-hint L1 — not fatal, but worth a look.
    return ("draft", 0.75, f"brand hints suggested {sorted(rule_l1s)}; LLM chose {llm_l1}")


# ---------------------------------------------------------------------- public API

class QshalaTagger:
    """Thin, DB-aware tagger. Instantiate once per request / job; it holds the Gemini client."""

    def __init__(self, provider: Optional[GeminiLLMProvider] = None, model: Optional[str] = None,
                 thinking_level: Optional[str] = None):
        self.provider = provider or GeminiLLMProvider()
        self.model = model or getattr(settings, "QSHALA_TAGGER_MODEL", None) or "gemini-3.5-flash-lite"
        self.thinking_level = thinking_level or "low"

    # ---- Tag one question. Does NOT commit the row by default; caller decides.

    async def tag(
        self,
        db: Session,
        *,
        question_id: str,
        question_text: str,
        answer: str,
        actor: str = "system",
        commit: bool = True,
    ) -> QshalaTag:
        """Full pipeline for one question. Returns the inserted QshalaTag row (uncommitted if commit=False)."""
        # Step 1: rules.
        rules = qshala_rules.extract(question_text, answer)

        # Step 2: duplicate check against previously confirmed tags.
        canon = _canonical_hash(question_text, answer)
        existing = (
            db.query(QshalaTag)
            .filter(QshalaTag.status == "confirmed")
            .filter(QshalaTag.question_id == question_id)
            .order_by(QshalaTag.created_at.desc())
            .first()
        )
        if existing and existing.source == "HUMAN":
            # Never re-tag over a human-confirmed row. Return the existing row unchanged.
            logger.info("qshala_tagger: skipping re-tag; HUMAN-confirmed row exists for %s", question_id)
            return existing

        # Step 3: LLM call.
        try:
            llm_out, usage, latency_ms = await _call_llm(self.provider, self.model, question_text, answer, rules,
                                                           thinking_level=self.thinking_level)
        except Exception as e:
            logger.exception("LLM call failed for %s: %s", question_id, e)
            raise

        # Step 4: route.
        status, confidence, reason = _route(rules, llm_out)
        l2 = llm_out.get("subtopic_l2")
        l1 = _load_taxonomy()["l2_to_l1"].get(l2) if l2 else None

        row = QshalaTag(
            question_id=question_id,
            taxonomy_version=TAXONOMY_VERSION,
            model_version=self.model,
            source="LLM",
            topic_l1=l1,
            subtopic_l2=l2,
            keywords_l3=llm_out.get("keywords_l3", []),
            secondary_l2=llm_out.get("secondary_l2", []),
            entity_type=llm_out.get("entity_type"),
            city_name=rules.city_name,
            geo_region=rules.geo_region,
            india_international=llm_out.get("india_international"),
            shelf_life=(rules.shelf_life if rules.shelf_life == "TIME_SENSITIVE" else None)
                       or llm_out.get("shelf_life")
                       or rules.shelf_life,
            sensitivity=llm_out.get("sensitivity") or rules.sensitivity or "NONE",
            fit=llm_out.get("fit"),
            search_summary=llm_out.get("search_summary"),
            confidence=confidence,
            status=status,
            tokens_in=usage.get("in"),
            tokens_out=usage.get("out"),
            thinking_tokens=usage.get("think"),
            latency_ms=latency_ms,
            verification_notes=f"auto-routed: {reason}",
        )
        db.add(row)
        db.flush()

        # If we're confirming, supersede the previous confirmed row (if any) and log the change.
        if status == "confirmed" and existing:
            existing.status = "superseded"
            db.add(QshalaTagChange(
                question_id=question_id, from_tag_id=existing.id, to_tag_id=row.id,
                change_type="SUPERSEDE", actor=actor, reason=reason,
            ))
        if status == "confirmed":
            db.add(QshalaTagChange(
                question_id=question_id, from_tag_id=None, to_tag_id=row.id,
                change_type="PROMOTE", actor=actor, reason=reason,
            ))

        if commit:
            db.commit()
            db.refresh(row)
        return row

    # ---- Human review API.

    def human_override(
        self,
        db: Session,
        *,
        question_id: str,
        new_tags: Dict[str, Any],
        actor: str,
        notes: Optional[str] = None,
        commit: bool = True,
    ) -> QshalaTag:
        """Store a human-authored tag row. Supersedes any current confirmed row.

        `new_tags` is a dict with the same keys the LLM returns, plus optional fact_check_url.
        """
        existing = (
            db.query(QshalaTag)
            .filter(QshalaTag.status == "confirmed")
            .filter(QshalaTag.question_id == question_id)
            .order_by(QshalaTag.created_at.desc())
            .first()
        )
        l2 = new_tags.get("subtopic_l2")
        l1 = _load_taxonomy()["l2_to_l1"].get(l2) if l2 else None
        row = QshalaTag(
            question_id=question_id, taxonomy_version=TAXONOMY_VERSION, model_version="human", source="HUMAN",
            topic_l1=l1, subtopic_l2=l2,
            keywords_l3=new_tags.get("keywords_l3", []),
            secondary_l2=new_tags.get("secondary_l2", []),
            entity_type=new_tags.get("entity_type"),
            city_name=new_tags.get("city_name"),
            geo_region=new_tags.get("geo_region"),
            india_international=new_tags.get("india_international"),
            shelf_life=new_tags.get("shelf_life"),
            sensitivity=new_tags.get("sensitivity", "NONE"),
            fit=new_tags.get("fit", "good"),
            search_summary=new_tags.get("search_summary"),
            confidence=1.0,
            status="confirmed",
            verified_by=actor,
            verified_at=datetime.now(timezone.utc),
            verification_notes=notes,
            fact_check_url=new_tags.get("fact_check_url"),
        )
        db.add(row)
        db.flush()
        if existing:
            existing.status = "superseded"
            db.add(QshalaTagChange(
                question_id=question_id, from_tag_id=existing.id, to_tag_id=row.id,
                change_type="HUMAN_OVERRIDE", actor=actor, reason=notes or "",
            ))
        db.add(QshalaTagChange(
            question_id=question_id, from_tag_id=None, to_tag_id=row.id,
            change_type="PROMOTE", actor=actor, reason="human-confirmed",
        ))
        if commit:
            db.commit()
            db.refresh(row)
        return row

    @staticmethod
    def current(db: Session, question_id: str) -> Optional[QshalaTag]:
        """The current confirmed tag row for a question, or None."""
        return (
            db.query(QshalaTag)
            .filter(QshalaTag.question_id == question_id, QshalaTag.status == "confirmed")
            .order_by(QshalaTag.created_at.desc())
            .first()
        )
