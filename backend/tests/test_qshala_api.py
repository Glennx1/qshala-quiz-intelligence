import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import SessionLocal
from backend.app.models.question import Question
from backend.app.models.qshala_tag import QshalaTag, QshalaTagChange, QshalaQuestionMetadata


@pytest.fixture
def client():
    return TestClient(app)


def test_get_taxonomy_endpoint(client):
    res = client.get("/api/v1/qshala/taxonomy")
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == "v5.1"
    assert len(data["domains"]) == 8
    assert len(data["l2_descriptions"]) == 78


def test_review_queue_endpoint(client):
    res = client.get("/api/v1/qshala/review-queue")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_search_questions_endpoint(client):
    res = client.get("/api/v1/qshala/questions")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "items" in data
    assert isinstance(data["items"], list)


def test_deck_tag_summary_empty(client):
    res = client.get("/api/v1/qshala/deck/non-existent-deck/tag-summary")
    assert res.status_code == 200
    data = res.json()
    assert data["total_questions"] == 0
    assert data["confirmed"] == 0
    assert data["estimated_cost_inr"] == 0.0


def test_review_action_and_bulk_accept(client):
    db = SessionLocal()
    try:
        # Create a test question
        q = Question(
            id="test-q-review-1",
            question_text="Which Indian carmaker launched the Sierra EV in 2025?",
            answer="Tata Motors",
            topic="Business",
            document_id="test-doc-review"
        )
        db.merge(q)

        # Create a draft tag
        t = QshalaTag(
            id="test-tag-draft-1",
            question_id="test-q-review-1",
            source="LLM",
            status="draft",
            topic_l1="Companies & Business",
            subtopic_l2="Consumer Brands",
            confidence=0.75,
            tokens_in=200,
            tokens_out=80,
            latency_ms=1800
        )
        db.merge(t)
        db.commit()

        # Test single review action: ACCEPT
        res = client.post(
            "/api/v1/qshala/review/test-tag-draft-1/action",
            json={"action": "accept", "actor": "tester_alice", "notes": "Looks solid"}
        )
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        assert res.json()["action"] == "accept"
        assert res.json()["tag"]["status"] == "confirmed"
        assert res.json()["tag"]["verified_by"] == "tester_alice"

        # Verify audit change was recorded
        audit = db.query(QshalaTagChange).filter(QshalaTagChange.to_tag_id == "test-tag-draft-1").first()
        assert audit is not None
        assert audit.actor == "tester_alice"
        assert audit.change_type == "ACCEPT_DRAFT"

        # Create a second draft tag to test bulk-accept
        t2 = QshalaTag(
            id="test-tag-draft-2",
            question_id="test-q-review-1",
            source="LLM",
            status="draft",
            topic_l1="Companies & Business",
            subtopic_l2="Company Origins",
            confidence=0.60
        )
        db.merge(t2)
        db.commit()

        res_bulk = client.post(
            "/api/v1/qshala/review/bulk-accept",
            json={"tag_ids": ["test-tag-draft-2"], "actor": "tester_bob"}
        )
        assert res_bulk.status_code == 200
        assert res_bulk.json()["accepted"] == 1

        # Test summary endpoint for test-doc-review
        res_summary = client.get("/api/v1/qshala/deck/test-doc-review/tag-summary")
        assert res_summary.status_code == 200
        sdata = res_summary.json()
        assert sdata["total_questions"] == 1
        assert sdata["confirmed"] == 1

    finally:
        # Cleanup
        db.query(QshalaTagChange).filter(QshalaTagChange.question_id == "test-q-review-1").delete()
        db.query(QshalaTag).filter(QshalaTag.question_id == "test-q-review-1").delete()
        db.query(Question).filter(Question.id == "test-q-review-1").delete()
        db.commit()
        db.close()


def test_batch_tag_skips_human_confirmed(client):
    db = SessionLocal()
    try:
        q = Question(
            id="test-q-human-protect",
            question_text="Who is the founder of Infosys?",
            answer="Narayana Murthy",
            topic="Business",
            document_id="test-doc-protect"
        )
        db.merge(q)

        # Create a HUMAN confirmed tag
        t = QshalaTag(
            id="test-tag-human-1",
            question_id="test-q-human-protect",
            source="HUMAN",
            status="confirmed",
            topic_l1="Companies & Business",
            subtopic_l2="Business Leaders",
            confidence=1.0,
            verified_by="human_expert"
        )
        db.merge(t)
        db.commit()

        # Run batch-tag on this question
        res = client.post(
            "/api/v1/qshala/batch-tag",
            json={
                "question_ids": ["test-q-human-protect"],
                "chunk_size": 1,
                "throttle_seconds": 0.0,
                "actor": "system_bot"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert data["processed"] == 1
        assert data["results"][0]["status"] == "SKIPPED_HUMAN_CONFIRMED"
        assert data["results"][0]["tag"]["subtopic_l2"] == "Business Leaders"
        assert data["results"][0]["tag"]["source"] == "HUMAN"

    finally:
        db.query(QshalaTagChange).filter(QshalaTagChange.question_id == "test-q-human-protect").delete()
        db.query(QshalaTag).filter(QshalaTag.question_id == "test-q-human-protect").delete()
        db.query(Question).filter(Question.id == "test-q-human-protect").delete()
        db.commit()
        db.close()


def test_search_vault_endpoint(client):
    """Test GET /qshala/search with free text and filters."""
    db = SessionLocal()
    try:
        # Seed test question and rich presentation metadata
        q = Question(
            id="zvq-blr-001",
            question_text="Epipremnum aureum, is the botanical name for an evergreen vine that is symbolic of wealth, growth and positivity in many Asian cultures. In 2002, Karnataka Bank adopted the common English name of this plant to brand its automated electronic banking infrastructure. Which plant?",
            answer="Money plant",
            topic="Banking & Money",
            document_id="test-doc-vault"
        )
        db.merge(q)

        meta = QshalaQuestionMetadata(
            question_id="zvq-blr-001",
            quiz_name="Zircon Vault Quiz 2026",
            round_stage="Prelims",
            source_presentation="zvq_prelims_blr.pptx"
        )
        db.merge(meta)

        t = QshalaTag(
            id="test-tag-vault-1",
            question_id="zvq-blr-001",
            source="LLM",
            status="draft",
            topic_l1="Banking & Money",
            subtopic_l2="Banking",
            confidence=0.75,
            search_summary="Karnataka Bank named its automated banking after Epipremnum aureum, the money plant."
        )
        db.merge(t)
        db.commit()

        # Test free text search
        res = client.get("/qshala/search?q=Epipremnum")
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "results" in data
        assert data["total"] >= 1
        hit = data["results"][0]
        assert hit["id"] == "zvq-blr-001"
        assert hit["answer"] == "Money plant"
        assert hit["subtopic_l2"] == "Banking"
        # Verify rich base-excel metadata is present
        assert "quiz_name" in hit
        assert "round_stage" in hit
        assert "source_presentation" in hit
    finally:
        db.query(QshalaQuestionMetadata).filter(QshalaQuestionMetadata.question_id == "zvq-blr-001").delete()
        db.query(QshalaTagChange).filter(QshalaTagChange.question_id == "zvq-blr-001").delete()
        db.query(QshalaTag).filter(QshalaTag.question_id == "zvq-blr-001").delete()
        db.query(Question).filter(Question.id == "zvq-blr-001").delete()
        db.commit()
        db.close()

