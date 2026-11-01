import pytest
from backend.app.services.prompt_quiz.engine import (
    Brief,
    _brief_from_gemini,
    librarian,
)


def _cand(qid: str, text: str, **kw):
    base = {
        "id": qid,
        "question_text": text,
        "answer": "Answer",
        "topic_l1": "Sports",
        "subtopic_l2": "Cricket",
        "secondary_l2": [],
        "keywords": [],
        "india_international": "IN",
        "shelf_life": "EVERGREEN",
        "sensitivity": "NONE",
        "image_dependent": False,
        "question_images": [],
        "answer_images": [],
        "image_refs": [],
        "search_summary": "",
        "difficulty": "Medium",
        "difficulty_score": 0.5,
        "document_id": "doc1",
        "tagged": True,
        "question_format": "STANDARD_QA",
    }
    base.update(kw)
    return base


def test_broadened_retrieval():
    # Question 1 contains "cricket", Question 2 only contains "championship" and "board"
    bank = [
        _cand("q1", "A standard cricket trivia question about bowling styles.", subtopic_l2="Cricket"),
        _cand("q2", "Which team won the inaugural championship organized by the board?", subtopic_l2="Tournaments"),
    ]

    brief_narrow = Brief(
        prompt="cricket",
        query="cricket",
        count=1,
        search_terms=[],
    )
    hits_narrow = librarian(bank, brief_narrow, pool=10)
    hit_ids_narrow = {h["id"] for h in hits_narrow}
    assert "q1" in hit_ids_narrow
    assert "q2" not in hit_ids_narrow

    brief_expanded = Brief(
        prompt="cricket",
        query="cricket",
        count=2,
        search_terms=["board", "championship"],
    )
    hits_expanded = librarian(bank, brief_expanded, pool=10)
    hit_ids_expanded = {h["id"] for h in hits_expanded}
    assert "q1" in hit_ids_expanded
    assert "q2" in hit_ids_expanded


def test_public_brief_unchanged():
    brief = Brief(
        prompt="cricket IPL",
        query="cricket",
        count=10,
        search_terms=["Indian Premier League", "T20", "BCCI"],
    )
    pub = brief.public()
    assert pub["query"] == "cricket"
    assert pub["search_terms"] == ["Indian Premier League", "T20", "BCCI"]


def test_empty_terms_no_error():
    bank = [_cand("q1", "Some science technology innovation question")]
    brief = Brief(
        prompt="science",
        query="science",
        count=5,
        search_terms=[],
    )
    hits = librarian(bank, brief, pool=10)
    assert len(hits) == 1
    assert hits[0]["id"] == "q1"


def test_extraction_from_gemini_dict():
    gem = {
        "query": "cricket",
        "count": 10,
        "search_terms": ["Indian Premier League", "T20", "BCCI", "CSK"],
    }
    brief = _brief_from_gemini("cricket", gem, count=None, previous_brief=None)
    assert brief.search_terms == ["Indian Premier League", "T20", "BCCI", "CSK"]


def test_sanitization_of_bad_inputs():
    gem = {
        "query": "cricket",
        "count": 10,
        "search_terms": [
            "  valid term  ",
            "",
            "   ",
            None,
            123,
            "x" * 70,  # too long (>=60)
            "another valid",
            "term 3",
            "term 4",
            "term 5",
            "term 6",
            "term 7",
            "term 8",
            "term 9",  # exceeds cap of 8
        ],
    }
    brief = _brief_from_gemini("cricket", gem, count=None, previous_brief=None)
    assert brief.search_terms == [
        "valid term",
        "another valid",
        "term 3",
        "term 4",
        "term 5",
        "term 6",
        "term 7",
        "term 8",
    ]
