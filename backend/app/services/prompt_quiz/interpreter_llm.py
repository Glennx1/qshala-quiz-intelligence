"""Gemini-powered Interpreter for the prompt-quiz engine.

Strict separation of concerns: this module ONLY turns a natural-language prompt
(optionally plus the previous Brief, when refining) into a structured JSON object.
It NEVER selects, ranks, or writes questions — retrieval stays 100% deterministic
in engine.py (Index.search / librarian / guardian / editor).

It is intentionally synchronous (the prompt-quiz route is a sync FastAPI endpoint
that runs in a worker thread) and dependency-light: one blocking httpx call with a
hard timeout. Any failure — missing key, timeout, HTTP error, malformed JSON —
returns None, and engine.py falls back to the regex parse_prompt() path. Nothing
here can fail the request.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Keep the timeout tight: the Interpreter is on the request's critical path and we
# fall back to regex instantly if Gemini is slow.
INTERPRETER_TIMEOUT_S = 5.0

# v6 L1 themes, surfaced to the model so topics_l1 comes back in our vocabulary.
V6_THEMES = [
    "Finance", "Business", "Economy", "Technology", "Science",
    "History", "Geography", "Politics", "Sports", "Entertainment", "Culture",
]

# OpenAPI-style schema (upper-case types) matching GeminiLLMProvider.generate_json_schema.
BRIEF_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "count": {"type": "INTEGER"},
        "query": {"type": "STRING"},
        "topics_l1": {"type": "ARRAY", "items": {"type": "STRING"}},
        "subtopics_l2": {"type": "ARRAY", "items": {"type": "STRING"}},
        "hard_bias": {"type": "STRING",
                      "enum": ["easy", "medium", "hard", "balanced", "spicy"], "nullable": True},
        "audience": {"type": "STRING",
                     "enum": ["school", "college", "corporate", "general"], "nullable": True},
        "india_focused": {"type": "BOOLEAN", "nullable": True},
        "evergreen": {"type": "BOOLEAN", "nullable": True},
        "no_images": {"type": "BOOLEAN", "nullable": True},
        "framing": {"type": "STRING"},
    },
    "required": ["count", "query", "topics_l1", "framing"],
}

_SYSTEM = (
    "You are the Interpreter for a quiz-building tool. You translate a quiz master's "
    "natural-language request into a structured brief. You do NOT write, choose, or "
    "rank questions — a separate deterministic engine does that from a curated bank. "
    "Only output the brief.\n"
    "Rules:\n"
    "- count: how many questions they want (default 10 if unstated).\n"
    "- query: a short, clean semantic topic phrase for keyword search — strip filler "
    "like 'give me', 'questions', 'round', counts, and difficulty/audience words.\n"
    f"- topics_l1: zero or more themes drawn ONLY from this list: {', '.join(V6_THEMES)}.\n"
    "- subtopics_l2: candidate finer subtopics in plain words (free text is fine).\n"
    "- hard_bias / audience: null unless the prompt clearly implies one.\n"
    "- india_focused / evergreen / no_images: true/false only if clearly implied, else null.\n"
    "- framing: one witty, high-taste sentence describing the round to the host.\n"
    "When a PREVIOUS BRIEF is given, apply the follow-up as an edit to it (e.g. 'make it "
    "harder' changes only hard_bias; 'give me 5 more' raises count; 'swap cricket for tech' "
    "changes query/topics) and return the full updated brief."
)


def _build_prompt(prompt: str, previous_brief: Optional[Dict[str, Any]]) -> str:
    parts = []
    if previous_brief:
        slim = {k: previous_brief.get(k) for k in
                ("count", "query", "topics_l1", "subtopics_l2", "hard_bias",
                 "audience", "india_focused", "evergreen", "no_images")
                if previous_brief.get(k) not in (None, [], "")}
        parts.append("PREVIOUS BRIEF:\n" + json.dumps(slim, ensure_ascii=False))
        parts.append("FOLLOW-UP REQUEST:\n" + (prompt or ""))
    else:
        parts.append("REQUEST:\n" + (prompt or ""))
    return "\n\n".join(parts)


def interpret_with_gemini(
    prompt: str,
    previous_brief: Optional[Dict[str, Any]] = None,
    *,
    timeout_s: float = INTERPRETER_TIMEOUT_S,
) -> Optional[Dict[str, Any]]:
    """Return the Interpreter JSON dict, or None on any failure (caller falls back).

    Synchronous and self-contained: builds the same request shape as
    GeminiLLMProvider.generate_json_schema but with a blocking httpx client and a
    short timeout, so it is safe to call from a sync route without an event loop.
    """
    try:
        from backend.app.config import settings
    except Exception:
        return None

    key = (getattr(settings, "GEMINI_API_KEY", None) or "").strip()
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()
    if not key:
        return None

    model = getattr(settings, "GEMINI_MODEL", None) or "gemini-2.5-flash"
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    payload = {
        "contents": [{"parts": [{"text": _build_prompt(prompt, previous_brief)}]}],
        "system_instruction": {"parts": [{"text": _SYSTEM}]},
        "generationConfig": {
            "response_mime_type": "application/json",
            "response_schema": BRIEF_SCHEMA,
            "temperature": 0.0,
        },
    }

    try:
        import httpx
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        cands = data.get("candidates") or []
        if not cands:
            return None
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = ""
        for part in reversed(parts):                 # final (non-thought) text part
            if "text" in part and not part.get("thought", False):
                text = part["text"]
                break
        if not text:
            for part in reversed(parts):
                if "text" in part:
                    text = part["text"]
                    break
        clean = (text or "").strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        parsed = json.loads(clean.strip())
        return parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.info("Gemini interpreter unavailable, falling back to regex parse_prompt: %s", e)
        return None
