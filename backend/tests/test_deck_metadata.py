"""Filename parser, format tracker, star detection and numbering - all pure functions."""
from backend.app.services.ingestion import deck_metadata as dm


def test_convention_name_full():
    d = dm.parse_deck_filename("2024-03-15 PES University Bengaluru Prelims ZVQ Business Quiz English.pptx")
    assert d.deck_date == "2024-03-15" and d.deck_year == 2024
    assert d.college == "PES University"
    assert d.city == "Bengaluru"
    assert d.round_stage == "Prelims"
    assert d.quiz_name == "ZVQ Business Quiz"
    assert d.language == "English"
    assert d.primary_audience == "College"
    assert d.is_varsity is True
    assert d.parsed_ok


def test_indian_date_order_and_underscores():
    d = dm.parse_deck_filename("15-03-2024_IIM_Bangalore_Finals_Open_Quiz.pptx")
    assert d.deck_date == "2024-03-15"
    assert d.city == "Bengaluru"            # alias normalised
    assert d.round_stage == "Finals"
    assert d.college == "IIM"
    assert d.quiz_name == "Open Quiz"
    assert d.is_varsity is False


def test_month_name_date_and_multiword_city():
    d = dm.parse_deck_filename("12 Feb 2023 Delhi Public School New Delhi Prelims Brain Wars.pptx")
    assert d.deck_date == "2023-02-12"
    assert d.city == "New Delhi"
    assert d.round_stage == "Prelims"
    assert d.college == "Delhi Public School"
    assert d.primary_audience == "School"


def test_zvq_only_in_name_is_varsity():
    assert dm.parse_deck_filename("ZVQ 2022 Mumbai Finals.pptx").is_varsity is True
    assert dm.parse_deck_filename("zvq_prelims_pune.pptx").is_varsity is True
    assert dm.parse_deck_filename("Zerodha Varsity Quiz IIT Madras Prelims.pptx").is_varsity is True
    assert dm.parse_deck_filename("Quiz about divorce.pptx").is_varsity is False


def test_language_token():
    d = dm.parse_deck_filename("2023-01-10 Christ University Bengaluru Prelims Quizzify Hindi.pptx")
    assert d.language == "Hindi"
    assert d.quiz_name == "Quizzify"


def test_non_conforming_name_never_raises():
    for name in ["", None, "final_v2 (1).pptx", "????.pptx", "Untitled presentation.pptx", "2024.pptx"]:
        d = dm.parse_deck_filename(name, title="Some title")
        assert d.quiz_name is not None or name in ("", None)
    d = dm.parse_deck_filename("Untitled presentation.pptx")
    assert d.parsed_ok is False
    assert d.quiz_name == "Untitled presentation"
    assert d.city is None and d.college is None and d.round_stage is None


def test_corporate_audience():
    d = dm.parse_deck_filename("2024-05-01 Infosys Corporate Bengaluru Prelims Offsite Quiz.pptx")
    assert d.primary_audience == "Corporate"


def _slide(n, stype, title="", text=""):
    return {"slide_number": n, "slide_type": stype, "title": title, "extracted_text": text}


def test_format_tracker_sections():
    slides = [
        _slide(1, "TITLE", "Welcome"),
        _slide(2, "SECTION_MARKER", "Round 1", "Direct questions"),
        _slide(3, "QUESTION", "", "Q1 text"),
        _slide(4, "ANSWER", "", "A1"),
        _slide(5, "SECTION_MARKER", "Round 2", "The following questions are Connect questions"),
        _slide(6, "QUESTION", "", "Q2"),
        _slide(7, "SECTION_MARKER", "Round 3", "3 clue round"),
        _slide(8, "QUESTION", "", "Q3"),
        _slide(9, "SECTION_MARKER", "Round 4"),
        _slide(10, "QUESTION", "", "Q4"),
        _slide(11, "CONTENT", "Buzzer round", "Buzzer questions next"),
        _slide(12, "QUESTION", "", "Q5"),
    ]
    f = dm.infer_formats(slides)
    assert f[3] == "QA"
    assert f[6] == "CONNECT"
    assert f[8] == "THREE_CLUE"
    assert f[10] == "QA"           # a round marker with no format words resets to QA
    assert f[12] == "BUZZER"


def test_connect_word_in_long_slide_is_not_a_header():
    slides = [
        _slide(1, "ANNOUNCEMENT", "Follow us", "Connect with us on Instagram and Twitter for more quizzes and updates every week"),
        _slide(2, "QUESTION", "", "Q"),
    ]
    assert dm.infer_formats(slides)[2] == "QA"


def test_all_formats_detected():
    cases = {
        "Potpourri": "POTPOURRI", "Arrange the order": "ARRANGE_ORDER", "Image reveal": "IMAGE_REVEAL",
        "List it": "LIST_IT", "Buzzer round": "BUZZER", "Connect round": "CONNECT", "QA round": "QA",
        "Three clue": "THREE_CLUE",
    }
    for header, fmt in cases.items():
        assert dm.detect_format_in_text(header) == fmt, header


def test_star_detection_and_strip():
    assert dm.detect_star("*Which company made Comet shoes?") == (True, "Which company made Comet shoes?")
    assert dm.detect_star("Which company made Comet shoes? *") == (True, "Which company made Comet shoes?")
    assert dm.detect_star("Which company made it?", "*\nWhich company made it?") == (True, "Which company made it?")
    assert dm.detect_star("It costs Rs 100 per share in 2020") == (False, "It costs Rs 100 per share in 2020")
    assert dm.detect_star("Plain question?") == (False, "Plain question?")


def test_language_script_detection():
    assert dm.detect_language("भारत की राजधानी क्या है") == "Hindi"
    assert dm.detect_language("ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ ಯಾವುದು") == "Kannada"
    assert dm.detect_language("What is the capital of India?") == "English"
    assert dm.detect_language("What is the capital?", "Hindi") == "Hindi"


def test_answer_type():
    assert dm.answer_type_for({"answer": "Nike"}) == "TEXT"
    assert dm.answer_type_for({"answer": "Nike", "answer_images": ["/x.png"]}) == "TEXT_IMAGE"
    assert dm.answer_type_for({"answer": "see image", "answer_images": ["/x.png"]}) == "IMAGE"
    assert dm.answer_type_for({"answer": "Nike", "answer_videos": ["/v.mp4"]}) == "TEXT_VIDEO"
    assert dm.answer_type_for({"answer": "", "answer_videos": ["/v.mp4"]}) == "VIDEO"
    assert dm.answer_type_for({"answer": "", "answer_audio": ["/a.mp3"]}) == "AUDIO"


def test_annotate_numbers_per_round_and_star_strip():
    slides = [_slide(1, "SECTION_MARKER", "Round 1"), _slide(2, "QUESTION"), _slide(4, "QUESTION"),
              _slide(5, "SECTION_MARKER", "Round 2", "Connect"), _slide(6, "QUESTION")]
    qs = [
        {"question_text": "*One?", "answer": "a", "slide_number": 2, "round_number": 1},
        {"question_text": "Two?", "answer": "b", "slide_number": 4, "round_number": 1},
        {"question_text": "Three?", "answer": "c", "slide_number": 6, "round_number": 2},
    ]
    deck = dm.parse_deck_filename("2024 PES Bengaluru Prelims Quiz English.pptx")
    dm.annotate_questions(qs, slides, deck)
    assert qs[0]["question_text"] == "One?" and qs[0]["_meta"]["star_marked"] is True
    assert [q["_meta"]["question_number"] for q in qs] == [1, 2, 3]
    assert [q["_meta"]["question_in_round"] for q in qs] == [1, 2, 1]
    assert qs[2]["_meta"]["question_format"] == "CONNECT"
    assert qs[1]["_meta"]["star_marked"] is False
    assert dm.question_label(3, 2, 1) == "Round 2 Q1"
    assert dm.question_label(14, None, None) == "Q14"


def test_filename_with_city_after_stage_and_answers_noise():
    from backend.app.services.ingestion.deck_metadata import parse_deck_filename
    d = parse_deck_filename("Prelim W ANSWERS - Bangalore South Zone - ZVQ 2026.pptx")
    assert d.city == "Bengaluru" and d.round_stage == "Prelims" and d.deck_year == 2026
    assert d.college is None and d.is_varsity is True
    assert d.quiz_name == "Bangalore South Zone ZVQ"


def test_decks_without_round_headers_have_no_round_and_star_shapes_count():
    from backend.app.services.ingestion.deck_metadata import annotate_questions, question_label
    slides = [
        {"slide_number": 1, "title": "ZVQ Prelims", "extracted_text": "ZVQ Prelims", "slide_type": "TITLE"},
        {"slide_number": 2, "title": "Q20", "extracted_text": "QUESTION 20\nWho?", "slide_type": "QUESTION",
         "metadata_json": {"has_star_shape": True}},
        {"slide_number": 3, "title": "Q21", "extracted_text": "QUESTION 21\nWhat?", "slide_type": "QUESTION"},
    ]
    qs = [{"question_text": "Who?", "answer": "a", "slide_number": 2, "round_number": 20},
          {"question_text": "What?", "answer": "b", "slide_number": 3, "round_number": 21}]
    annotate_questions(qs, slides)
    assert [q["_meta"]["round_number"] for q in qs] == [None, None]
    assert [q["_meta"]["star_marked"] for q in qs] == [True, False]
    assert question_label(2, None, 2) == "Q2"
