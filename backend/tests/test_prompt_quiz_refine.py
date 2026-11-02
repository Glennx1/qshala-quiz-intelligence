import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_refine_difficulty_modifier():
    """Verify refining with 'make it harder' preserves topic and sets hard_bias='hard'."""
    r1 = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "5 questions on banking"})
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert len(d1["questions"]) == 5
    assert "bank" in d1["brief"]["query"].lower()

    # Follow-up refine: make it harder
    r2 = client.post("/api/v1/prompt-quiz/draft", json={
        "prompt": "make it harder",
        "previous_brief": d1["brief"],
        "current_questions": d1["questions"],
    })
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["brief"]["hard_bias"] == "hard"
    assert "bank" in d2["brief"]["query"].lower()
    assert len(d2["questions"]) == 5


def test_refine_with_locked_slots():
    """Verify locked questions are preserved in their exact slots while unlocked slots are replaced."""
    r1 = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "5 questions on finance"})
    assert r1.status_code == 200
    d1 = r1.json()
    q_list = d1["questions"]
    assert len(q_list) >= 5

    locked_q1 = q_list[0]
    locked_q3 = q_list[2]
    locked_ids = [locked_q1["id"], locked_q3["id"]]

    # Refine to tech, but keep Q1 and Q3 locked
    r2 = client.post("/api/v1/prompt-quiz/draft", json={
        "prompt": "replace finance with technology",
        "previous_brief": d1["brief"],
        "keep_ids": locked_ids,
        "current_questions": q_list[:5],
    })
    assert r2.status_code == 200
    d2 = r2.json()
    q2_list = d2["questions"]

    # Q1 must be at index 0, Q3 must be at index 2
    assert q2_list[0]["id"] == locked_q1["id"]
    assert q2_list[2]["id"] == locked_q3["id"]
    assert "locked" in d2.get("message", "").lower()


def test_refine_single_slot_replacement():
    """Verify 'replace question 2 with cricket' targets only slot 2 and keeps slots 1, 3, 4, 5."""
    r1 = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "5 questions on banking"})
    assert r1.status_code == 200
    d1 = r1.json()
    q_list = d1["questions"][:5]

    target_slot = 2
    old_slot2_id = q_list[1]["id"]
    old_other_ids = [q["id"] for i, q in enumerate(q_list) if i != 1]

    r2 = client.post("/api/v1/prompt-quiz/draft", json={
        "prompt": "replace question 2 with cricket",
        "previous_brief": d1["brief"],
        "current_questions": q_list,
    })
    assert r2.status_code == 200
    d2 = r2.json()
    q2_list = d2["questions"]

    # Slot 2 must have changed
    assert q2_list[1]["id"] != old_slot2_id
    # Other slots must remain intact
    new_other_ids = [q["id"] for i, q in enumerate(q2_list) if i != 1]
    assert new_other_ids == old_other_ids
    assert "replaced question 2" in d2.get("message", "").lower()


def test_refine_count_expansion():
    """Verify 'give me 3 more' expands count without losing existing questions."""
    r1 = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "5 questions on startups"})
    assert r1.status_code == 200
    d1 = r1.json()
    q1_ids = [q["id"] for q in d1["questions"][:5]]

    r2 = client.post("/api/v1/prompt-quiz/draft", json={
        "prompt": "give me 3 more",
        "previous_brief": d1["brief"],
        "current_questions": d1["questions"][:5],
    })
    assert r2.status_code == 200
    d2 = r2.json()
    assert len(d2["questions"]) >= 7  # Expanded from 5
    # The original 5 questions should be present
    q2_ids = {q["id"] for q in d2["questions"]}
    for qid in q1_ids:
        assert qid in q2_ids


def test_refine_with_excluded_ids():
    """Verify explicitly excluded questions are never picked in refined result."""
    r1 = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "5 questions on banking"})
    assert r1.status_code == 200
    d1 = r1.json()
    disliked_id = d1["questions"][1]["id"]

    r2 = client.post("/api/v1/prompt-quiz/draft", json={
        "prompt": "give me 5 questions on banking",
        "previous_brief": d1["brief"],
        "exclude_ids": [disliked_id],
    })
    assert r2.status_code == 200
    d2 = r2.json()
    q2_ids = {q["id"] for q in d2["questions"]}
    assert disliked_id not in q2_ids


def test_refine_audience_modifier():
    """Verify 'make it for middle school kids' shifts audience to school and enables school_safe."""
    r1 = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "5 questions on finance"})
    assert r1.status_code == 200
    d1 = r1.json()

    r2 = client.post("/api/v1/prompt-quiz/draft", json={
        "prompt": "make it for middle school kids",
        "previous_brief": d1["brief"],
        "current_questions": d1["questions"],
    })
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["brief"]["filters"].get("audience") == "school"
    assert d2["brief"]["filters"].get("school_safe") is True


def test_refine_partial_replacement_preserves_total_count():
    """Verify 'change 3 questions to tech' on a 10-question quiz keeps 10 questions total (does not shrink to 3)."""
    r1 = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "10 questions on banking"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert len(d1["questions"]) == 10
    q1_ids = [q["id"] for q in d1["questions"]]

    r2 = client.post("/api/v1/prompt-quiz/draft", json={
        "prompt": "change 3 questions to tech",
        "previous_brief": d1["brief"],
        "current_questions": d1["questions"],
    })
    assert r2.status_code == 200
    d2 = r2.json()
    # Total count MUST be 10, NOT 3!
    assert len(d2["questions"]) == 10
    # First 7 questions from the original quiz should be kept
    for i in range(7):
        assert d2["questions"][i]["id"] == q1_ids[i]
    assert "replaced 3 questions" in d2.get("message", "").lower()
