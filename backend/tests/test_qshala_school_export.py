import io
import pytest
from pptx import Presentation
from backend.app.services.export.exporter import QuizExporter
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_qshala_school_pptx_export_structure():
    sample_quiz = {
        "id": "quiz_qshala_demo_001",
        "title": "Wildlife and Biodiversity Challenge",
        "topic": "Environment & Nature",
        "questions": [
            {
                "order_index": 1,
                "question_text": "Which national park in Assam is famous for the one-horned rhinoceros?",
                "answer": "Kaziranga National Park",
                "explanation": "Kaziranga holds two-thirds of the world's great one-horned rhinoceroses and is a UNESCO World Heritage Site.",
                "options": ["Jim Corbett", "Kaziranga", "Gir Forest", "Sundarbans"],
                "is_approved": True,
                "retrieval_sources": [
                    {"document_title": "Assam_Eco_Tour.pptx", "slide_number": 8}
                ]
            },
            {
                "order_index": 2,
                "question_text": "What is the fastest land animal on Earth?",
                "answer": "Cheetah",
                "explanation": "Cheetahs can accelerate from 0 to 60 mph in just 3 seconds.",
                "is_approved": True
            }
        ]
    }

    # 1. Standard export with divider
    pptx_bytes = QuizExporter.to_pptx(
        sample_quiz,
        quiz_type="qshala_school",
        custom_title="Inter-School Wildlife Olympiad",
        custom_subtitle="Grades 6 - 8 • Annual Science Festival",
        show_answer_divider=True
    )
    assert len(pptx_bytes) > 2000
    prs = Presentation(io.BytesIO(pptx_bytes))
    
    # Expected slides:
    # 1. Cover
    # 2. Q1
    # 3. Answer Divider 1
    # 4. Answer 1
    # 5. Q2
    # 6. Answer Divider 2
    # 7. Answer 2
    assert len(prs.slides) == 7

    # Verify Cover Slide
    cover_slide = prs.slides[0]
    cover_text = " ".join([shape.text_frame.text for shape in cover_slide.shapes if shape.has_text_frame])
    assert "Inter-School Wildlife Olympiad" in cover_text
    assert "Grades 6 - 8" in cover_text

    # Verify Q1 Slide
    q1_slide = prs.slides[1]
    q1_text = " ".join([shape.text_frame.text for shape in q1_slide.shapes if shape.has_text_frame])
    assert "Question 1" in q1_text
    assert "Kaziranga" in q1_text
    assert q1_slide.has_notes_slide
    notes_q1 = q1_slide.notes_slide.notes_text_frame.text
    assert "Official Answer: Kaziranga National Park" in notes_q1
    assert "Assam_Eco_Tour.pptx" in notes_q1

    # Verify Answer Divider Slide
    ans_div_slide = prs.slides[2]
    div_text = " ".join([shape.text_frame.text for shape in ans_div_slide.shapes if shape.has_text_frame])
    assert "Answer" in div_text

    # Verify Answer Reveal Slide
    ans1_slide = prs.slides[3]
    ans1_text = " ".join([shape.text_frame.text for shape in ans1_slide.shapes if shape.has_text_frame])
    assert "Kaziranga National Park" in ans1_text
    assert "UNESCO" in ans1_text
    assert ans1_slide.has_notes_slide
    notes_a1 = ans1_slide.notes_slide.notes_text_frame.text
    assert "Presenter Talking Points:" in notes_a1


def test_qshala_school_pptx_export_without_divider():
    sample_quiz = {
        "id": "quiz_qshala_no_div",
        "title": "Quick Trivia",
        "questions": [
            {
                "order_index": 1,
                "question_text": "What is the capital of France?",
                "answer": "Paris",
                "explanation": "Paris is located along the Seine River.",
                "is_approved": True
            }
        ]
    }

    pptx_bytes = QuizExporter.to_pptx(
        sample_quiz,
        quiz_type="qshala_school",
        show_answer_divider=False
    )
    prs = Presentation(io.BytesIO(pptx_bytes))
    # 1. Cover, 2. Q1, 3. Answer 1 -> total 3 slides
    assert len(prs.slides) == 3


def test_quizzes_export_api_router_qshala_school():
    sample_quiz = {
        "id": "quiz_api_export_test",
        "title": "Astronomy Quiz",
        "topic": "Astronomy",
        "questions": [
            {
                "order_index": 1,
                "question_text": "Which planet is known as the Red Planet?",
                "answer": "Mars",
                "explanation": "Mars appears red due to iron oxide on its surface.",
                "is_approved": True
            }
        ]
    }

    # Test POST /api/v1/quizzes/export with quiz_type=qshala_school
    response = client.post(
        "/api/v1/quizzes/export?format=pptx&quiz_type=qshala_school&custom_title=Cosmic+Journey",
        json=sample_quiz
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert len(response.content) > 1000

    prs = Presentation(io.BytesIO(response.content))
    assert len(prs.slides) >= 3
    cover_text = " ".join([shape.text_frame.text for shape in prs.slides[0].shapes if shape.has_text_frame])
    assert "Cosmic Journey" in cover_text
