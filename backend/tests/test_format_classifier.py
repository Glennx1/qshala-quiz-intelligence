"""
test_format_classifier.py
-------------------------
Tests for multi-signal format classifier (format_classifier.py):
1. Structural Layer: image count + answer length (image-only Connect 4)
2. Text Layer: regex on question & answer text
3. Round Layer: round name keywords
4. classify_and_extract payload building
"""

import pytest
from backend.app.services.tagging.format_classifier import (
    classify_format,
    classify_and_extract,
    STANDARD_QA,
    CONNECT_4,
    STEPPED_CLUE,
    ARRANGE_ORDER,
)


class TestStructuralConnect4:
    """Image-count signal catches image-only Connect 4 questions."""

    def test_four_images_short_answer(self):
        """The Puneeth Rajkumar case: 4 brand logos, 1-word answer, no text signal."""
        assert classify_format(
            "",  # no question text
            "Puneeth Rajkumar",
            question_images=["img1.png", "img2.png", "img3.png", "img4.png"],
        ) == CONNECT_4

    def test_four_images_with_text(self):
        """Even with some text, 4 images + short answer = Connect 4."""
        assert classify_format(
            "Identify the common element",
            "Lays",
            question_images=["a.png", "b.png", "c.png", "d.png"],
        ) == CONNECT_4

    def test_one_image_not_connect(self):
        """A regular question with 1 image should NOT be Connect 4."""
        assert classify_format(
            "Who founded this company?",
            "Elon Musk",
            question_images=["logo.png"],
        ) == STANDARD_QA

    def test_two_images_not_connect(self):
        """2 images is ambiguous — not enough for Connect 4."""
        assert classify_format(
            "Compare these two",
            "They are different",
            question_images=["a.png", "b.png"],
        ) == STANDARD_QA


class TestTextFormats:
    def test_stepped_clue_points(self):
        q = "Clue 1 (+20/-15): Founder started in 1910. Clue 2 (+15/-10): Famous for pens."
        assert classify_format(q, "Parker") == STEPPED_CLUE

    def test_stepped_clue_numbered_sections(self):
        q = "Clue 1: Something obscure\nClue 2: Moderate hint\nClue 3: Giveaway"
        assert classify_format(q, "Answer") == STEPPED_CLUE

    def test_arrange_order_keywords(self):
        q = "Arrange the following companies by market cap (from lowest to highest):"
        assert classify_format(q, "A -> B -> C -> D") == ARRANGE_ORDER

    def test_arrange_order_sequence_answer(self):
        q = "Put these in chronological order"
        assert classify_format(q, "B -> C -> A -> D") == ARRANGE_ORDER

    def test_connect_answer_link(self):
        q = "Look at these four items"
        assert classify_format(q, "The common link is they are all Nobel laureates") == CONNECT_4

    def test_standard_qa(self):
        assert classify_format("What is the capital of France?", "Paris") == STANDARD_QA


class TestRoundNameFallback:
    def test_portfolio_builder_round(self):
        assert classify_format("What is this company?", "Infosys", round_name="Portfolio Builder") == STEPPED_CLUE

    def test_ticker_tangle_round(self):
        assert classify_format("What order did they launch?", "A, B, C", round_name="Ticker Tangle") == ARRANGE_ORDER

    def test_connect_round(self):
        assert classify_format("Look closely", "Mahatma Gandhi", round_name="Market Indicators Round") == CONNECT_4


class TestClassifyAndExtract:
    def test_connect4_auto_populates_elements(self):
        fmt, data = classify_and_extract(
            "",
            "Apollo 11",
            question_images=["img1.png", "img2.png", "img3.png", "img4.png"],
        )
        assert fmt == CONNECT_4
        assert data is not None
        assert data["type"] == "CONNECT_4"
        assert len(data["elements"]) == 4
        assert data["elements"][0]["image_url"] == "img1.png"
        assert data["common_link"] == "Apollo 11"
