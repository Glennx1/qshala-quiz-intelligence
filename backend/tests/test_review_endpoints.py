"""The Review toggle's backend: list questions needing review, and accept one."""
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.models.qshala_tag import QshalaTag

client = TestClient(app)
API = "/api/v1"


def _seed(status):
    db = SessionLocal()
    doc_id, q_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(Document(id=doc_id, filename="r.pptx", title="r", year=2022, file_type="pptx",
                    storage_path="x", file_size_bytes=1, processing_status="COMPLETED"))
    db.add(Question(id=q_id, document_id=doc_id, question_text="Who?", answer="A", topic="Sports"))
    db.add(QshalaTag(question_id=q_id, taxonomy_version="v6", source="LLM", status=status,
                     topic_l1="Sports", subtopic_l2="Cricket", fit="weak", confidence=0.5))
    db.commit()
    db.close()
    return doc_id, q_id


def _cleanup(doc_id, q_id):
    db = SessionLocal()
    try:
        db.query(QshalaTag).filter(QshalaTag.question_id == q_id).delete(synchronize_session=False)
        db.query(Question).filter(Question.id == q_id).delete(synchronize_session=False)
        db.query(Document).filter(Document.id == doc_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_draft_question_shows_in_review_and_confirmed_does_not():
    d1, q1 = _seed("draft")
    d2, q2 = _seed("confirmed")
    try:
        ids = {r["id"] for r in client.get(f"{API}/questions/needs-review").json()}
        assert q1 in ids and q2 not in ids
        assert client.get(f"{API}/questions/needs-review/count").json()["count"] >= 1
    finally:
        _cleanup(d1, q1)
        _cleanup(d2, q2)


def test_accept_review_confirms_and_removes_from_queue():
    d, q = _seed("draft")
    try:
        r = client.post(f"{API}/questions/{q}/accept-review")
        assert r.status_code == 200
        db = SessionLocal()
        tag = db.query(QshalaTag).filter(QshalaTag.question_id == q).order_by(
            QshalaTag.created_at.desc()).first()
        assert tag.status == "confirmed" and tag.verified_by == "quizmaster"
        db.close()
        ids = {x["id"] for x in client.get(f"{API}/questions/needs-review").json()}
        assert q not in ids          # left the review queue
    finally:
        _cleanup(d, q)


def test_well_tagged_ai_question_bypasses_review():
    """Questions with canonical taxonomy L2 and fit='good' are well-tagged and must not appear in review."""
    db = SessionLocal()
    doc_id, q_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(Document(id=doc_id, filename="r.pptx", title="r", year=2022, file_type="pptx",
                    storage_path="x", file_size_bytes=1, processing_status="COMPLETED"))
    db.add(Question(id=q_id, document_id=doc_id, question_text="What?", answer="B", topic="History"))
    db.add(QshalaTag(question_id=q_id, taxonomy_version="v6", source="LLM", status="draft",
                     topic_l1="History", subtopic_l2="Modern History", fit="good", confidence=0.88))
    db.commit()
    db.close()
    try:
        ids = {r["id"] for r in client.get(f"{API}/questions/needs-review").json()}
        assert q_id not in ids, "Well-tagged question should bypass the review queue"
    finally:
        _cleanup(doc_id, q_id)


def test_uncategorized_question_without_tags_shows_in_review():
    """A question with no QshalaTag at all is truly uncategorized and must appear in review."""
    db = SessionLocal()
    doc_id, q_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(Document(id=doc_id, filename="r.pptx", title="r", year=2022, file_type="pptx",
                    storage_path="x", file_size_bytes=1, processing_status="COMPLETED"))
    db.add(Question(id=q_id, document_id=doc_id, question_text="Uncategorized Q?", answer="Ans", topic="Uncategorized"))
    db.commit()
    db.close()
    try:
        ids = {r["id"] for r in client.get(f"{API}/questions/needs-review").json()}
        assert q_id in ids, "Untagged question must appear in needs-review"

        # Accepting it confirms it and removes from review queue
        r = client.post(f"{API}/questions/{q_id}/accept-review")
        assert r.status_code == 200
        ids_after = {r["id"] for r in client.get(f"{API}/questions/needs-review").json()}
        assert q_id not in ids_after, "Accepted untagged question should leave the review queue"
    finally:
        _cleanup(doc_id, q_id)


def test_question_with_empty_or_generic_subtopic_shows_in_review():
    """A question whose tag has no L2 or 'Uncategorized' subtopic must appear in review."""
    db = SessionLocal()
    doc_id, q_id = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(Document(id=doc_id, filename="r.pptx", title="r", year=2022, file_type="pptx",
                    storage_path="x", file_size_bytes=1, processing_status="COMPLETED"))
    db.add(Question(id=q_id, document_id=doc_id, question_text="Generic GK?", answer="Ans", topic="General Knowledge"))
    db.add(QshalaTag(question_id=q_id, taxonomy_version="v6", source="LLM", status="draft",
                     topic_l1="General Knowledge", subtopic_l2=None, fit="none", confidence=0.0))
    db.commit()
    db.close()
    try:
        ids = {r["id"] for r in client.get(f"{API}/questions/needs-review").json()}
        assert q_id in ids, "Question with null subtopic must appear in needs-review"
    finally:
        _cleanup(doc_id, q_id)
