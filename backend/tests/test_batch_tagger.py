import asyncio
import pytest
from unittest.mock import AsyncMock
from backend.app.services.tagging.qshala_tagger import QshalaTagger
from backend.app.services.ingestion.pipeline import is_image_dependent_question


class MockBatchGemini:
    def __init__(self, return_data):
        self.return_data = return_data
        self.generate_json = AsyncMock(return_value=return_data)


def test_tag_batch_success():
    tagger = QshalaTagger()
    
    mock_response = [
        {
            "topic": "Finance",
            "subtopic": "Stock Markets",
            "difficulty": 2,
            "tags": ["BSE", "Sensex", "Equities"],
        },
        {
            "topic": "Business",
            "subtopic": "Brand Heritage & Identity",
            "difficulty": 3,
            "tags": ["Logo", "Rebrand", "Nike"],
        },
        {
            "topic": "Economy",
            "subtopic": "Banking System",
            "difficulty": 5,
            "tags": ["RBI", "Repo Rate", "Inflation"],
        },
    ]
    
    tagger.provider = MockBatchGemini(mock_response)
    
    questions = [
        {"id": "q1", "question_text": "What does BSE stand for?", "answer": "Bombay Stock Exchange"},
        {"id": "q2", "question_text": "Identify this swoosh logo.", "answer": "Nike", "explanation": "Famous athletic brand."},
        {"id": "q3", "question_text": "Who sets the repo rate in India?", "answer": "RBI"},
    ]
    
    results = asyncio.run(tagger.tag_batch(questions))
    
    assert len(results) == 3
    assert results[0]["topic"] == "Finance"
    assert results[0]["subtopic"] == "Stock Markets"
    assert results[0]["difficulty"] == 2
    assert results[0]["tags"] == ["BSE", "Sensex", "Equities"]
    
    assert results[1]["topic"] == "Business"
    assert results[1]["difficulty"] == 3
    assert "Nike" in results[1]["tags"]
    
    assert results[2]["topic"] == "Economy"
    assert results[2]["difficulty"] == 5
    assert results[2]["tags"] == ["RBI", "Repo Rate", "Inflation"]


def test_tag_batch_validation_fallback():
    tagger = QshalaTagger()
    
    # Second item has an invalid topic that doesn't exist in taxonomy
    mock_response = [
        {
            "topic": "Finance",
            "subtopic": "Stock Markets",
            "difficulty": 2,
            "tags": ["Stocks"],
        },
        {
            "topic": "NonExistentTopic12345",
            "subtopic": "Unknown",
            "difficulty": 4,
            "tags": ["Invalid"],
        },
    ]
    
    mock_provider = MockBatchGemini(mock_response)
    tagger.provider = mock_provider
    # Mock tag_one fallback
    tagger.tag_one = AsyncMock(return_value={
        "topic": "Finance",
        "subtopic": "Stock Markets",
        "difficulty": 3,
        "tags": ["FallbackTag"],
    })
    
    questions = [
        {"id": "q1", "question_text": "Question 1", "answer": "Answer 1"},
        {"id": "q2", "question_text": "Question 2", "answer": "Answer 2"},
    ]
    
    results = asyncio.run(tagger.tag_batch(questions))
    assert len(results) == 2
    assert results[0]["topic"] == "Finance"
    # Second question triggered tag_one fallback
    assert tagger.tag_one.called
    assert results[1]["tags"] == ["FallbackTag"]


def test_is_image_dependent_question_heuristic():
    # 1. No images at all -> never image dependent
    q_no_img = {
        "question_text": "Short text",
        "image_paths": [],
        "question_images": [],
        "image_refs": [],
    }
    assert is_image_dependent_question(q_no_img) is False

    # 2. Has image, but question_text is short while explanation is long (> 15 words combined) -> not image dependent
    q_long_explanation = {
        "question_text": "Connect clue 1",
        "explanation": "This is a detailed paragraph explaining the historical background of the company founded in 1920 in Bangalore with multiple subsidiaries.",
        "question_images": ["img1.png"],
    }
    assert is_image_dependent_question(q_long_explanation) is False

    # 3. Has image, text is genuinely short (< 15 words total) -> image dependent
    q_genuinely_short = {
        "question_text": "Identify this person.",
        "explanation": "Founder of Apple.",
        "question_images": ["img1.png"],
    }
    assert is_image_dependent_question(q_genuinely_short) is True

    # 4. Has image, long text, but contains visual cue regex -> image dependent
    q_visual_cue = {
        "question_text": "Look at the photo of this famous architect who designed the building shown here in 1950 after returning from Europe.",
        "explanation": "He is well known worldwide.",
        "question_images": ["img1.png"],
    }
    assert is_image_dependent_question(q_visual_cue) is True
