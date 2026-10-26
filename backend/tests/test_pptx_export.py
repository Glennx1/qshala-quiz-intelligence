import io
import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.quiz import Quiz, GeneratedQuestion
from backend.app.services.export.exporter import QuizExporter

client = TestClient(app)


def test_pptx_export_bengaluru_south_theme():
    """Verify that export produces a valid 16:9 presentation with Bengaluru South theme."""
    sample_quiz = {
        "id": "test-bengaluru-quiz",
        "title": "Bengaluru South Open Championship",
        "topic": "Karnataka Business & Culture",
        "difficulty": "Medium",
        "questions": [
            {
                "id": "q1",
                "question_text": "Which plant was adopted by Karnataka Bank in 2002 to brand its ATM network?",
                "options": ["A) Money plant", "B) Bamboo", "C) Tulsi", "D) Banyan"],
                "answer": "Money plant",
                "explanation": "Epipremnum aureum, commonly known as money plant, symbolizes prosperity.",
                "difficulty": "Medium",
                "is_approved": True,
            },
            {
                "id": "q2",
                "question_text": "Which iconic IT company was founded in Pune in 1981 but later moved its headquarters to Electronics City, Bengaluru?",
                "options": ["A) Infosys", "B) Wipro", "C) TCS", "D) Mindtree"],
                "answer": "Infosys",
                "explanation": "Infosys relocated to Bengaluru in 1983 and established its landmark campus in Electronics City.",
                "difficulty": "Easy",
                "is_approved": True,
            }
        ]
    }

    # 1. Test direct QuizExporter.to_pptx with Bengaluru South theme
    pptx_bytes = QuizExporter.to_pptx(sample_quiz, theme="bengaluru_south")
    assert isinstance(pptx_bytes, bytes)
    assert len(pptx_bytes) > 1000

    # 2. Verify with python-pptx that it parses cleanly
    prs = Presentation(io.BytesIO(pptx_bytes))
    # 1 Title Slide + 2 Questions (each with 1 Question + 1 Answer slide) = 5 slides total
    assert len(prs.slides) == 5
    assert prs.slide_width.inches == pytest.approx(13.333, 0.01)
    assert prs.slide_height.inches == pytest.approx(7.5, 0.01)

    # Verify slide texts
    title_slide = prs.slides[0]
    title_texts = [p.text for s in title_slide.shapes if s.has_text_frame for p in s.text_frame.paragraphs]
    assert any("Bengaluru South Open Championship" in t for t in title_texts)

    q1_slide = prs.slides[1]
    q1_texts = [p.text for s in q1_slide.shapes if s.has_text_frame for p in s.text_frame.paragraphs]
    assert any("Karnataka Bank" in t for t in q1_texts)
    assert any("1." in t for t in q1_texts)

    ans1_slide = prs.slides[2]
    ans1_texts = [p.text for s in ans1_slide.shapes if s.has_text_frame for p in s.text_frame.paragraphs]
    assert any("Money plant" in t for t in ans1_texts)


def test_pptx_export_minimalist_fallback():
    """Verify fallback to minimalist styling when requested."""
    sample_quiz = {
        "id": "test-minimalist",
        "title": "Minimalist Quiz",
        "topic": "General",
        "questions": [
            {
                "id": "q1",
                "question_text": "What is the capital of India?",
                "answer": "New Delhi",
                "explanation": "New Delhi was inaugurated in 1931.",
                "is_approved": True,
            }
        ]
    }
    pptx_bytes = QuizExporter.to_pptx(sample_quiz, theme="minimalist")
    prs = Presentation(io.BytesIO(pptx_bytes))
    assert len(prs.slides) == 3


def test_pptx_export_api_endpoints():
    """Test both GET /quizzes/{id}/export?format=pptx and POST /quizzes/export?format=pptx."""
    db = SessionLocal()
    quiz = None
    try:
        # Create a test quiz in database
        quiz = Quiz(
            title="API Test Quiz",
            topic="History",
            difficulty="Balanced",
            quiz_format="TOURNAMENT_PRELIMS"
        )
        db.add(quiz)
        db.commit()
        db.refresh(quiz)

        gq = GeneratedQuestion(
            quiz_id=quiz.id,
            question_text="Who was the architect of New Delhi?",
            answer="Sir Edwin Lutyens",
            explanation="Lutyens planned New Delhi with Sir Herbert Baker.",
            order_index=1,
            is_approved=True
        )
        db.add(gq)
        db.commit()

        # Test GET /api/v1/quizzes/{id}/export?format=pptx&theme=bengaluru_south
        res_get = client.get(f"/api/v1/quizzes/{quiz.id}/export?format=pptx&theme=bengaluru_south")
        assert res_get.status_code == 200
        assert "presentationml" in res_get.headers["content-type"]
        assert len(res_get.content) > 1000
        prs_get = Presentation(io.BytesIO(res_get.content))
        assert len(prs_get.slides) == 3

        # Test POST /api/v1/quizzes/export?format=pptx
        payload = {
            "title": "Direct Payload Quiz",
            "topic": "Science",
            "questions": [
                {
                    "question_text": "What is the speed of light in vacuum?",
                    "answer": "Approximately 300,000 km/s",
                    "explanation": "299,792,458 metres per second precisely.",
                    "is_approved": True
                }
            ]
        }
        res_post = client.post("/api/v1/quizzes/export?format=pptx&theme=bengaluru_south", json=payload)
        assert res_post.status_code == 200
        assert len(res_post.content) > 1000

    finally:
        if quiz:
            db.query(GeneratedQuestion).filter(GeneratedQuestion.quiz_id == quiz.id).delete()
            db.query(Quiz).filter(Quiz.id == quiz.id).delete()
            db.commit()
        db.close()
