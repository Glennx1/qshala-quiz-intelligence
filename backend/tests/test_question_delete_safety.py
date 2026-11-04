"""Bulk/single question delete (audit Q3): a bare DELETE must not purge the bank, and the cascade must work."""
import uuid

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.document import Document
from backend.app.models.question import Question
from backend.app.models.question_meta import QuestionRepeat

client = TestClient(app)


def _deck_with_questions(n=2):
    db = SessionLocal()
    try:
        doc_id = str(uuid.uuid4())
        db.add(Document(id=doc_id, filename="del.pptx", title="Delete Test", file_type="pptx",
                        storage_path="dummy", file_size_bytes=1, processing_status="COMPLETED"))
        db.flush()
        ids = []
        for i in range(n):
            q = Question(id=str(uuid.uuid4()), document_id=doc_id, topic="Test",
                         question_text=f"delete test question {doc_id} {i}", answer="x")
            db.add(q)
            ids.append(q.id)
        db.flush()
        # A repeat of the first question found in the same deck's record, to exercise the repeat cascade.
        db.add(QuestionRepeat(question_id=ids[0], document_id=doc_id, match_type="EXACT"))
        db.commit()
        return doc_id, ids
    finally:
        db.close()


def _count(model, **flt):
    db = SessionLocal()
    try:
        return db.query(model).filter_by(**flt).count()
    finally:
        db.close()


def test_bare_delete_is_refused_and_deletes_nothing():
    doc_id, ids = _deck_with_questions()
    before = _count(Question)
    r = client.delete("/api/v1/questions")
    assert r.status_code == 400
    assert _count(Question) == before
    assert _count(Question, document_id=doc_id) == 2


def test_delete_by_document_removes_questions_and_repeats():
    doc_id, ids = _deck_with_questions()
    other_doc, other_ids = _deck_with_questions()
    r = client.delete(f"/api/v1/questions?document_id={doc_id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_count"] == 2
    assert _count(Question, document_id=doc_id) == 0
    assert _count(QuestionRepeat, question_id=ids[0]) == 0
    assert _count(Question, document_id=other_doc) == 2          # other decks untouched


def test_delete_single_question_cascades_its_repeats():
    doc_id, ids = _deck_with_questions()
    r = client.delete(f"/api/v1/questions/{ids[0]}")
    assert r.status_code == 200, r.text
    assert _count(Question, id=ids[0]) == 0
    assert _count(QuestionRepeat, question_id=ids[0]) == 0
    assert _count(Question, id=ids[1]) == 1
