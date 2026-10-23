"""Backfill: a question stored the old way gets deck details, numbering, Repeated entries and a v6 topic."""
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.document import Document, Slide
from backend.app.models.qshala_tag import QshalaQuestionMetadata, QshalaTag
from backend.app.models.question import Question
from backend.app.models.question_meta import DeckMetadata, QuestionRepeat, QuestionTopicPath
from backend.app.services import backfill_v6
from backend.app.services.ingestion.cancellation import purge_document

client = TestClient(app)


def test_backfill_structure_repeats_and_topic_carry_over():
    d1, d2 = str(uuid.uuid4()), str(uuid.uuid4())
    db = SessionLocal()
    try:
        for did, name in ((d1, "2022-05-10 PES University Bengaluru Prelims ZVQ Old Quiz.pptx"),
                          (d2, "2023-02-11 IIM Bangalore Bengaluru Finals Open Quiz.pptx")):
            db.add(Document(id=did, filename=name, title=name, year=2022, file_type="pptx", storage_path="x",
                            processing_status="COMPLETED"))
        db.flush()
        s1 = Slide(document_id=d1, slide_number=3, slide_type="QUESTION", extracted_text="QUESTION 1\n*Who won the 1983 final?")
        db.add(s1)
        db.flush()
        qid = str(uuid.uuid4())
        db.add(Question(id=qid, document_id=d1, slide_id=s1.id, question_text="*Who won the 1983 final?",
                        answer="India", topic="Sports", subtopic="Cricket", tags=["World Cup"],
                        source_slide_range="Slide 3-4", round_number=1,
                        provenance_decks=[{"document_id": d1}, {"document_id": d2}]))
        db.flush()
        db.add(QshalaTag(question_id=qid, topic_l1="Sports", subtopic_l2="Cricket", taxonomy_version="v5.1", source="LLM"))
        db.commit()

        backfill_v6.STATUS.update(decks=0, questions=0, repeats=0, migrated_topics=0)
        backfill_v6.run_structure(db)

        deck = db.query(DeckMetadata).filter(DeckMetadata.document_id == d1).one()
        assert deck.college == "PES University" and deck.is_varsity is True
        m = db.query(QshalaQuestionMetadata).filter(QshalaQuestionMetadata.question_id == qid).one()
        assert db.query(Question).filter(Question.id == qid).one().question_text == "Who won the 1983 final?"
        assert m.question_number == 1 and m.star_marked is True and m.city_name == "Bengaluru"
        reps = db.query(QuestionRepeat).filter(QuestionRepeat.question_id == qid).all()
        assert len(reps) == 1 and reps[0].document_id == d2
        paths = db.query(QuestionTopicPath).filter(QuestionTopicPath.question_id == qid).all()
        assert [(p.l1, p.l2) for p in paths] == [("Sports", "Cricket")]

        # running it again adds nothing
        backfill_v6.run_structure(db)
        assert db.query(QuestionRepeat).filter(QuestionRepeat.question_id == qid).count() == 1
        assert db.query(QuestionTopicPath).filter(QuestionTopicPath.question_id == qid).count() == 1
        assert qid not in backfill_v6.untagged_question_ids(db)
    finally:
        db.close()
        db = SessionLocal()
        for d in (d1, d2):
            purge_document(db, d)
        db.close()


def test_backfill_endpoints_report_status_and_cancel():
    r = client.get("/api/v1/admin/backfill-v6/status")
    assert r.status_code == 200 and "state" in r.json()
    assert client.post("/api/v1/admin/backfill-v6/cancel").status_code == 200
