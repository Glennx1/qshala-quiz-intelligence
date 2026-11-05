import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base
from backend.app.models.question import Question
from backend.app.models.document import Document
from backend.app.services.prompt_quiz.curator_llm import curate_quiz_with_gemini
from backend.app.services.prompt_quiz import engine


@pytest.fixture
def mock_candidates():
    return [
        {
            "id": f"q_{i}",
            "question_text": f"Question {i} about technology and startups in India",
            "answer": f"Answer {i}",
            "topic": "Technology",
            "subtopic_l2": "Startups",
            "difficulty": "Medium",
            "difficulty_score": 0.50,
            "question_format": "STANDARD_QA",
            "score": 10.0 - i
        }
        for i in range(1, 15)
    ]


def test_curator_validation_gate_rejects_hallucinated_ids(mock_candidates):
    """
    Zero-Hallucination Invariant:
    If Gemini hallucinates or outputs an ID not in the candidate pool,
    curate_quiz_with_gemini MUST filter it out and pad only with legitimate candidate IDs.
    """
    fake_gemini_resp = {
        "selected_ids": ["q_1", "hallucinated_fake_id_999", "q_3", "q_4", "another_fake_id"],
        "narrative_arc": "From humble origins to tech titans."
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": str(fake_gemini_resp).replace("'", '"')}]
                    }
                }
            ]
        }
        mock_client.post.return_value = mock_resp
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        with patch("backend.app.config.settings.GEMINI_API_KEY", "test_key_abc"):
            res = curate_quiz_with_gemini(
                prompt="5 questions on startups",
                target_count=5,
                candidates=mock_candidates
            )

    assert res is not None
    selected = res["selected_ids"]
    assert len(selected) == 5

    # Check: hallucinated IDs MUST NOT be present
    assert "hallucinated_fake_id_999" not in selected
    assert "another_fake_id" not in selected

    # Every single ID in selected must be from mock_candidates
    valid_ids = {c["id"] for c in mock_candidates}
    for qid in selected:
        assert qid in valid_ids, f"ID {qid} is not in valid candidate pool!"


def test_curator_fallback_on_gemini_timeout(mock_candidates):
    """
    Failsafe Invariant:
    If Gemini times out or raises an exception, it must return None cleanly
    without raising an unhandled exception.
    """
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.post.side_effect = TimeoutError("Gemini request timed out after 4.0s")
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        with patch("backend.app.config.settings.GEMINI_API_KEY", "test_key_abc"):
            res = curate_quiz_with_gemini(
                prompt="5 questions on startups",
                target_count=5,
                candidates=mock_candidates
            )

    assert res is None, "Curator should return None on timeout to trigger deterministic fallback"


def test_build_draft_invokes_curator_and_attaches_narrative_arc():
    """
    Integration test: build_draft uses curator when available and sets narrative_arc.
    """
    db_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db_engine)
    TestingSession = sessionmaker(bind=db_engine)
    db = TestingSession()

    try:
        doc = Document(id="doc_t1", filename="startups.pptx", title="Bangalore Startups", file_type="pptx", storage_path="/tmp")
        db.add(doc)
        distinct_topics = [
            ("Flipkart was founded in a two-bedroom apartment in which Bengaluru neighbourhood?", "Koramangala"),
            ("Which food delivery platform began with bundled deliveries in Bengaluru in 2014?", "Swiggy"),
            ("Ather Energy pioneered electric smart scooters developed primarily in which tech hub?", "Bengaluru"),
            ("Which ride-hailing company was started by Bhavish Aggarwal and Ankit Bhati in Karnataka?", "Ola Cabs"),
            ("Zerodha revolutionized discount broking from their headquarters on Outer Ring Road in which city?", "Bengaluru"),
            ("Which coffee chain known for filter coffee and quick service went viral in Indiranagar?", "Third Wave Coffee"),
            ("Postman, the API development platform, began its journey in which Silicon Valley of India?", "Bengaluru"),
            ("Which logistics unicorn was founded by Sahil Barua and Kapil Bharati in India?", "Delhivery"),
            ("PhonePe was acquired by Flipkart and powers digital UPI transactions from its base in which city?", "Bengaluru"),
            ("Biocon was founded by Kiran Mazumdar-Shaw in a garage in which city?", "Bengaluru"),
        ]
        for i, (q_txt, a_txt) in enumerate(distinct_topics, 1):
            q = Question(
                id=f"q_startup_{i}",
                document_id="doc_t1",
                question_text=q_txt,
                answer=a_txt,
                topic="Technology",
                subtopic="Startups",
                difficulty="Medium",
                difficulty_score=0.50,
            )
            db.add(q)
        db.commit()

        fake_curation = {
            "selected_ids": ["q_startup_5", "q_startup_2", "q_startup_8", "q_startup_1", "q_startup_9"],
            "narrative_arc": "Starts with early Koramangala garage ventures and builds up to unicorn IPOs."
        }

        engine.invalidate_bank_cache()
        with patch("backend.app.services.prompt_quiz.curator_llm.curate_quiz_with_gemini", return_value=fake_curation):
            draft = engine.build_draft(
                db=db,
                prompt="5 questions on Bangalore startups",
                count=5,
            )

        assert len(draft["questions"]) == 5
        assert draft["narrative_arc"] == "Starts with early Koramangala garage ventures and builds up to unicorn IPOs."
        assert "Curator" in draft["stages"]
        # Check order was preserved from curator
        delivered_ids = [q["id"] for q in draft["questions"]]
        assert delivered_ids == fake_curation["selected_ids"]
    finally:
        engine.invalidate_bank_cache()
        db.close()
