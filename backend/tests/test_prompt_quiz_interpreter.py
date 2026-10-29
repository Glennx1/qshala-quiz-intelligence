"""Task 1: Gemini Interpreter wiring + bulletproof regex fallback + refinement.

These run with GEMINI_API_KEY forced empty, so they exercise the deterministic fallback path
end to end (no network). The separation-of-concerns guarantee is structural: the engine only ever
asks the Interpreter for a Brief, then retrieves questions with deterministic Python.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.services.prompt_quiz import engine
from backend.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_gemini(monkeypatch):
    # Force the fallback path: no key => interpret_with_gemini returns None instantly.
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "", raising=False)
    yield


def test_interpreter_falls_back_to_regex_and_parses_count():
    b = engine.interpret("8 questions on banking")
    assert b.source == "regex"
    assert b.count == 8
    assert "bank" in b.query


def test_explicit_count_arg_wins():
    b = engine.interpret("give me a quiz on cricket", count=12)
    assert b.count == 12


def test_count_is_clamped():
    assert engine.interpret("500 questions on tech").count == 50
    assert engine.interpret("banking", count=99).count == 50


def test_hard_bias_detected():
    assert engine.interpret("a tough finals round on markets").hard_bias == "hard"
    assert engine.interpret("easy warm-up on brands").hard_bias == "easy"


def test_filter_words_become_filters():
    b = engine.interpret("school safe evergreen quiz on cricket, no images")
    assert b.filters.get("school_safe") is True
    assert b.filters.get("evergreen_only") is True
    assert b.filters.get("exclude_image") is True


def test_refine_inherits_count_when_followup_has_no_number():
    # "make it harder" keeps the previous count and flips the bias.
    prev = engine.interpret("10 questions on markets").public()
    refined = engine.interpret("make it harder", previous_brief=prev)
    assert refined.count == 10
    assert refined.hard_bias == "hard"


def test_options_override_filters():
    b = engine.interpret("cricket quiz", options={"exclude_image": True})
    assert b.filters.get("exclude_image") is True
    b2 = engine.interpret("no images cricket quiz", options={"exclude_image": False})
    assert "exclude_image" not in b2.filters          # explicit False clears it


def test_draft_endpoint_accepts_previous_brief_and_count():
    r = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "7 questions on banking"})
    assert r.status_code == 200
    brief = r.json()["brief"]
    assert brief["count"] == 7 and "Interpreter" in r.json()["stages"]
    # refine round-trip: send the brief back with a follow-up
    r2 = client.post("/api/v1/prompt-quiz/draft",
                     json={"prompt": "make it harder", "previous_brief": brief})
    assert r2.status_code == 200
    assert r2.json()["brief"]["count"] == 7


def test_interpreter_never_selects_questions():
    # The Interpreter output carries no question ids/text — selection is the engine's job.
    b = engine.interpret("5 questions on fintech").public()
    assert "questions" not in b and "id" not in b
