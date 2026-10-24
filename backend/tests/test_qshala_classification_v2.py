import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.models.qshala_tag import QshalaTag
from backend.app.services.tagging.qshala_batch import (
    recent_human_exemplars,
    tag_deck_batched,
    _batch_schema,
)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _create_test_doc(db):
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        filename=f"test_{doc_id}.pptx",
        title=f"Test Deck {doc_id}",
        year=2024,
        file_type="pptx",
        storage_path=f"/tmp/test_{doc_id}.pptx",
        file_size_bytes=1000,
        processing_status="COMPLETED",
    )
    db.add(doc)
    db.commit()
    return doc


def test_recent_human_exemplars(db_session):
    doc = _create_test_doc(db_session)
    tag_id = str(uuid.uuid4())
    q_id = str(uuid.uuid4())
    
    exemplars = recent_human_exemplars(db_session, limit=5)
    initial_count = len(exemplars)

    q = Question(
        id=q_id,
        document_id=doc.id,
        content_hash=f"hash_{q_id}",
        question_text="Which Indian conglomerate was founded in 1868 by Jamsetji Tata?",
        answer="Tata Group",
        topic="Uncategorised",
    )
    db_session.add(q)
    db_session.flush()

    tag = QshalaTag(
        id=tag_id,
        question_id=q_id,
        taxonomy_version="v6",
        model_version="human",
        source="HUMAN",
        status="confirmed",
        topic_l1="Business",
        subtopic_l2="Founder Stories",
        keywords_l3=["Jamsetji Tata", "Conglomerate"],
        confidence=1.0,
        fit="good",
    )
    db_session.add(tag)
    db_session.commit()

    try:
        exemplars = recent_human_exemplars(db_session, limit=10)
        assert len(exemplars) == initial_count + 1
        matched = [e for e in exemplars if "Jamsetji Tata" in e["q"]]
        assert len(matched) == 1
        assert matched[0]["theme"] == "Business"
        assert matched[0]["subtopic"] == "Founder Stories"
    finally:
        db_session.delete(tag)
        db_session.delete(q)
        db_session.delete(doc)
        db_session.commit()


def test_chunk_failure_parks_in_review(db_session):
    doc = _create_test_doc(db_session)

    class FailingProvider:
        async def generate_json_schema(self, *args, **kwargs):
            raise RuntimeError("Gemini 500 internal error or connection timeout")

    q1_id = str(uuid.uuid4())
    q2_id = str(uuid.uuid4())
    q1 = Question(id=q1_id, document_id=doc.id, content_hash=f"h_{q1_id}", question_text="Q1 text", answer="A1", topic="Uncategorised")
    q2 = Question(id=q2_id, document_id=doc.id, content_hash=f"h_{q2_id}", question_text="Q2 text", answer="A2", topic="Uncategorised")
    db_session.add_all([q1, q2])
    db_session.commit()

    try:
        stats = asyncio.run(tag_deck_batched(
            db_session,
            [q1, q2],
            provider=FailingProvider(),
            model="gemini-test",
            actor="test_runner",
        ))

        assert stats["failed_chunks"] == 1
        assert stats["draft"] == 2
        assert stats["confirmed"] == 0

        # Verify QshalaTag rows are parked in review with draft status
        t1 = db_session.query(QshalaTag).filter(QshalaTag.question_id == q1_id).first()
        t2 = db_session.query(QshalaTag).filter(QshalaTag.question_id == q2_id).first()
        assert t1 is not None and t1.status == "draft"
        assert "needs review" in t1.verification_notes
        assert t2 is not None and t2.status == "draft"
        assert "needs review" in t2.verification_notes
    finally:
        db_session.query(QshalaTag).filter(QshalaTag.question_id.in_([q1_id, q2_id])).delete()
        db_session.delete(q1)
        db_session.delete(q2)
        db_session.delete(doc)
        db_session.commit()


def test_short_results_array_missing_go_to_review(db_session):
    doc = _create_test_doc(db_session)

    class PartialProvider:
        async def generate_json_schema(self, *args, **kwargs):
            # Returns result ONLY for n=0, missing n=1 and n=2
            return {
                "results": [
                    {
                        "n": 0,
                        "topics": [
                            {"theme": "Business", "subtopic_l2": "Founder Stories", "keywords": ["Founder", "Business"]}
                        ],
                        "geo_location": "Mumbai",
                        "india_international": "IN",
                        "relevant_year": 1932,
                        "fit": "good",
                        "search_summary": "Question about business founder.",
                    }
                ]
            }, {"in": 10, "out": 10}

    q0_id = str(uuid.uuid4())
    q1_id = str(uuid.uuid4())
    q2_id = str(uuid.uuid4())

    q0 = Question(id=q0_id, document_id=doc.id, content_hash=f"h_{q0_id}", question_text="Who founded Air India in 1932?", answer="JRD Tata", topic="Uncategorised")
    q1 = Question(id=q1_id, document_id=doc.id, content_hash=f"h_{q1_id}", question_text="Second question", answer="Answer 2", topic="Uncategorised")
    q2 = Question(id=q2_id, document_id=doc.id, content_hash=f"h_{q2_id}", question_text="Third question", answer="Answer 3", topic="Uncategorised")
    db_session.add_all([q0, q1, q2])
    db_session.commit()

    try:
        stats = asyncio.run(tag_deck_batched(
            db_session,
            [q0, q1, q2],
            provider=PartialProvider(),
            model="gemini-test",
            actor="test_runner",
        ))

        assert stats["confirmed"] == 1
        assert stats["draft"] == 2

        t0 = db_session.query(QshalaTag).filter(QshalaTag.question_id == q0_id).first()
        t1 = db_session.query(QshalaTag).filter(QshalaTag.question_id == q1_id).first()
        t2 = db_session.query(QshalaTag).filter(QshalaTag.question_id == q2_id).first()

        assert t0 is not None and t0.status == "confirmed"
        assert t0.topic_l1 == "Business"
        assert t0.subtopic_l2 == "Founder Stories"

        assert t1 is not None and t1.status == "draft"
        assert "needs review" in t1.verification_notes

        assert t2 is not None and t2.status == "draft"
        assert "needs review" in t2.verification_notes
    finally:
        db_session.query(QshalaTag).filter(QshalaTag.question_id.in_([q0_id, q1_id, q2_id])).delete()
        db_session.delete(q0)
        db_session.delete(q1)
        db_session.delete(q2)
        db_session.delete(doc)
        db_session.commit()


def test_clarify_endpoint_writes_human_row(db_session, monkeypatch):
    client = TestClient(app)
    doc = _create_test_doc(db_session)

    q_id = str(uuid.uuid4())
    q = Question(
        id=q_id,
        document_id=doc.id,
        content_hash=f"h_{q_id}",
        question_text="Which car brand produces the 911 model?",
        answer="Porsche",
        topic="Uncategorised",
    )
    db_session.add(q)
    db_session.commit()

    # Mock the LLM call inside QshalaTagger.tag to return German automotive brand
    async def mock_call_llm(*args, **kwargs):
        return {
            "topics": [
                {"theme": "Business", "subtopic_l2": "Brand Heritage & Identity", "keywords": ["Porsche", "Automotive", "911"]}
            ],
            "geo_location": "Stuttgart, Germany",
            "india_international": "INTL",
            "relevant_year": 1964,
            "fit": "good",
            "search_summary": "Porsche 911 automotive brand.",
        }, {"in": 10, "out": 10, "think": 0}, 150

    monkeypatch.setattr("backend.app.services.tagging.qshala_tagger._call_llm", mock_call_llm)

    try:
        resp = client.post(
            f"/qshala/review/{q_id}/clarify",
            json={
                "hint": "This is definitely automotive brand heritage and identity",
                "actor": "quizmaster_rahul",
                "accept": True,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ok"
        assert data["confirmed"] is True

        human_tag = db_session.query(QshalaTag).filter(
            QshalaTag.question_id == q_id,
            QshalaTag.status == "confirmed"
        ).first()

        assert human_tag is not None
        assert human_tag.source == "HUMAN"
        assert human_tag.verified_by == "quizmaster_rahul"
        assert "clarified: This is definitely automotive brand heritage and identity" in (human_tag.verification_notes or "")
        assert human_tag.subtopic_l2 == "Brand Heritage & Identity"
    finally:
        db_session.query(QshalaTag).filter(QshalaTag.question_id == q_id).delete()
        db_session.delete(q)
        db_session.delete(doc)
        db_session.commit()
