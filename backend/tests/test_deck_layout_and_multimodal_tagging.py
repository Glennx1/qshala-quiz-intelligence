import pytest
from backend.app.services.ingestion.slide_classifier import SlideClassifier
from backend.app.services.ingestion.question_extractor import QuestionExtractor
from backend.app.services.tagging.difficulty_engine import DifficultyEngine

def test_deck_layout_detection_two_section():
    classifier = SlideClassifier()
    
    # Mock slides for a 2-section tournament prelim deck
    # Section 1: Questions 1 to 5 (no answers)
    slides = [
        {"slide_number": 1, "title": "Prelims - Tournament 2024", "extracted_text": "Welcome to the quiz"},
        {"slide_number": 2, "title": "Rules", "extracted_text": "20 questions, write on sheets"},
        {"slide_number": 3, "title": "1.", "extracted_text": "1. Which country launched Sputnik?"},
        {"slide_number": 4, "title": "2.", "extracted_text": "2. What is the currency of Japan?"},
        {"slide_number": 5, "title": "3.", "extracted_text": "3. Who painted the Mona Lisa?"},
        {"slide_number": 6, "title": "4.", "extracted_text": "4. What is the chemical symbol for Gold?"},
        # Divider Slide
        {"slide_number": 7, "title": "PLEASE HAND IN YOUR SHEETS", "extracted_text": "ANSWERS FOLLOW"},
        {"slide_number": 8, "title": "LET'S DISCUSS THE ANSWERS", "extracted_text": "Let us check the scores"},
        # Section 2: Questions with answers
        {"slide_number": 9, "title": "1.", "extracted_text": "1. Which country launched Sputnik?"},
        {"slide_number": 10, "title": "ANSWER", "extracted_text": "ANSWER"},
        {"slide_number": 11, "title": "USSR", "extracted_text": "USSR\nFirst artificial satellite in 1957."},
        {"slide_number": 12, "title": "2.", "extracted_text": "2. What is the currency of Japan?"},
        {"slide_number": 13, "title": "ANSWER", "extracted_text": "ANSWER"},
        {"slide_number": 14, "title": "Yen", "extracted_text": "Yen"},
    ]

    layout_info = classifier.detect_deck_layout(slides)
    assert layout_info["layout_type"] == "TWO_SECTION"
    assert layout_info["answers_section_start"] == 6 # index of the divider

    # Verify classification marks section 1 questions as QUESTION_PREVIEW
    classified_types = classifier.classify_deck(slides)
    assert classified_types[2] == "QUESTION_PREVIEW"
    assert classified_types[3] == "QUESTION_PREVIEW"
    assert classified_types[4] == "QUESTION_PREVIEW"
    assert classified_types[5] == "QUESTION_PREVIEW"
    
    # Verify section 2 has questions and answers
    assert classified_types[8] == "QUESTION"
    assert classified_types[9] == "ANSWER_TRANSITION"
    assert classified_types[10] == "ANSWER"

def test_deck_layout_detection_interleaved():
    classifier = SlideClassifier()
    slides = [
        {"slide_number": 1, "title": "Finals", "extracted_text": "Welcome to Finals"},
        {"slide_number": 2, "title": "Round 1 - Potpourri", "extracted_text": "Round 1"},
        {"slide_number": 3, "title": "1.", "extracted_text": "1. Identify this company?"},
        {"slide_number": 4, "title": "ANSWER", "extracted_text": "ANSWER"},
        {"slide_number": 5, "title": "Google", "extracted_text": "Google"},
    ]
    layout_info = classifier.detect_deck_layout(slides)
    assert layout_info["layout_type"] == "INTERLEAVED"

def test_question_extractor_transition_bridge():
    extractor = QuestionExtractor()
    slides = [
        {
            "id": "s1",
            "slide_number": 1,
            "slide_type": "QUESTION",
            "title": "1.",
            "extracted_text": "1. Qatar has become the 8th country to join which payment network?",
            "speaker_notes": "https://source.com/reference-url-only",
            "image_paths": ["/static/slides/doc/media/q1.png"],
            "all_media_items": [{"filename": "q1.png", "media_type": "image"}]
        },
        {
            "id": "s2",
            "slide_number": 2,
            "slide_type": "ANSWER_TRANSITION",
            "title": "ANSWER",
            "extracted_text": "ANSWER",
            "speaker_notes": "",
            "image_paths": [],
            "all_media_items": []
        },
        {
            "id": "s3",
            "slide_number": 3,
            "slide_type": "ANSWER",
            "title": "UPI",
            "extracted_text": "UPI\nUnified Payments Interface developed by NPCI.",
            "speaker_notes": "",
            "image_paths": ["/static/slides/doc/media/upi.png"],
            "all_media_items": [{"filename": "upi.png", "media_type": "image"}]
        }
    ]

    questions = extractor.extract_from_slides(slides, "Test Deck", 2024)
    assert len(questions) == 1
    q = questions[0]
    assert "Qatar has become the 8th country" in q["question_text"]
    assert q["answer"] == "UPI"
    assert "Unified Payments Interface" in q["explanation"]
    assert q["source_slide_range"] == "Slide 1–3"
    assert "/static/slides/doc/media/q1.png" in q["image_refs"]
    assert "/static/slides/doc/media/upi.png" in q["image_refs"]
    # Ensure source URL was NOT set as answer
    assert "https://" not in q["answer"]

def test_multimodal_tagging_policy_unrated_difficulty():
    engine = DifficultyEngine()

    # Case A: Visual / Image-based question
    res_multimodal = engine.evaluate(
        question_text="Identify this prominent monument shown in the photograph.",
        answer_text="Eiffel Tower",
        explanation="Constructed in 1889 for the World's Fair in Paris.",
        is_multimodal=True
    )

    assert res_multimodal["difficulty"] == "Unrated"
    assert res_multimodal["difficulty_score"] == 0.0
    assert res_multimodal["is_unrated"] is True
    assert res_multimodal["grade_min"] in [1, 5, 9]

    # Case B: Corporate / Advanced Multimodal question -> Calibrated Grade 9-12
    res_adv_multimodal = engine.evaluate(
        question_text="This chart depicts the tariff and GDP implications for cross-border trade.",
        answer_text="Import Tariff",
        explanation="Taxation on foreign imports.",
        is_multimodal=True
    )
    assert res_adv_multimodal["difficulty"] == "Unrated"
    assert res_adv_multimodal["grade_min"] == 9
    assert res_adv_multimodal["grade_max"] == 12

    # Case C: Pure text question -> Standard Easy/Medium/Hard continuous PDI
    res_text = engine.evaluate(
        question_text="What is the capital of France?",
        answer_text="Paris",
        explanation="Paris is the largest city and capital of France.",
        is_multimodal=False
    )
    assert res_text["difficulty"] == "Easy"
    assert res_text["difficulty_score"] > 0.0
    assert res_text["grade_min"] == 1
    assert res_text["grade_max"] == 4
