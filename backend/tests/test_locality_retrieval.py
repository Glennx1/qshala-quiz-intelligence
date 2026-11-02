"""Tests for geographic / locality retrieval across topics in prompt quiz engine."""
import pytest
from backend.app.services.prompt_quiz.engine import Brief, editor, guardian, _brief_from_regex
from backend.app.services.prompt_quiz.fulfillment import split_pools
from backend.app.services.prompt_quiz.audience import audience_score


def test_regex_detects_karnataka_locality():
    b = _brief_from_regex("5 questions on Karnataka", count=5, previous_brief=None)
    assert b.locality == "Karnataka"
    assert b.filters.get("india_focused") is True
    assert b.count == 5


def test_regex_detects_bengaluru_locality():
    b = _brief_from_regex("10 questions about Bangalore", count=10, previous_brief=None)
    assert b.locality == "Bengaluru"
    assert b.filters.get("india_focused") is True
    assert b.count == 10


def test_audience_score_alias_awareness():
    # Bengaluru query should boost Bangalore text/city match
    q1 = {"id": "1", "question_text": "Post office constructed in Bangalore", "city_name": None}
    assert audience_score(q1, locality="Bengaluru") > 0

    # Karnataka query should boost Bengaluru city
    q2 = {"id": "2", "question_text": "A general question", "city_name": "Bengaluru"}
    assert audience_score(q2, locality="Karnataka") > 0


def test_editor_does_not_filter_out_when_subtopics_l2_empty():
    brief = Brief(prompt="5 questions on Karnataka", query="Karnataka", count=5, locality="Karnataka")
    cands = [
        {"id": "1", "subtopic_l2": "Countries and Capitals", "score": 2.5, "topic_l1": "Geography"},
        {"id": "2", "subtopic_l2": "Banks and Banking", "score": 2.1, "topic_l1": "Finance"},
        {"id": "3", "subtopic_l2": "General Trivia", "score": 1.9, "topic_l1": "General Knowledge"},
    ]
    picked = editor(cands, brief)
    assert len(picked) == 3
    assert {p["id"] for p in picked} == {"1", "2", "3"}


def test_split_pools_drops_unmatched_l2s_and_allows_bm25_fallback():
    pool = [
        {"id": "1", "topic_l1": "Finance", "subtopic_l2": "Banks and Banking", "score": 1.5},
        {"id": "2", "topic_l1": "General Knowledge", "subtopic_l2": "General Trivia", "score": 1.2},
    ]
    # LLM suggested invented subtopics not in pool
    on_ok, adj, on_all, effective_l2s = split_pools(
        pool,
        l1s=[],  # cleared by locality logic
        l2s=["States of India", "Landmarks and Monuments"],
        filters={},
        format_filter=None,
    )
    assert effective_l2s == []
    # Both items have score >= 0.3 so both are on-topic when L1/L2 are empty
    assert len(on_ok) == 2
