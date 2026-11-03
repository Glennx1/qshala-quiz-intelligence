import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_draft_swap_save():
    r = client.post("/api/v1/prompt-quiz/draft", json={"prompt": "8 questions on banking"})
    assert r.status_code == 200
    d = r.json()
    assert d["brief"]["count"] == 8 and "Interpreter" in d["stages"]
    qs = d["questions"]
    if not qs:
        return  # empty bank in CI
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids))
    s = client.post("/api/v1/prompt-quiz/swap", json={"prompt": "banking", "question_id": ids[0], "keep_ids": ids})
    assert s.status_code in (200, 404)
    if s.status_code == 200:
        assert s.json()["id"] not in ids
    sv = client.post("/api/v1/prompt-quiz/save", json={"prompt": "banking", "question_ids": ids})
    assert sv.status_code == 200 and sv.json()["count"] == len(ids)
    assert client.get(f"/api/v1/quizzes/{sv.json()['quiz_id']}").status_code == 200


def test_starters():
    assert len(client.get("/api/v1/prompt-quiz/starters").json()["starters"]) >= 3


def test_refine_add_question_preserves_quiz():
    # Initial draft
    r1 = client.post('/api/v1/prompt-quiz/draft', json={'prompt': '3 questions on technology'})
    assert r1.status_code == 200
    d1 = r1.json()
    qs1 = d1['questions']
    if len(qs1) < 2:
        return  # Bank too small in some CI environments

    ids1 = [q['id'] for q in qs1]

    # Refine: add 1 question based on bengaluru
    r2 = client.post('/api/v1/prompt-quiz/draft', json={
        'prompt': 'add 1 question based on bengaluru',
        'previous_brief': d1['brief'],
        'current_questions': [{'id': q['id'], 'question_text': q['question_text']} for q in qs1]
    })
    assert r2.status_code == 200
    d2 = r2.json()
    qs2 = d2['questions']

    # All initial questions must be preserved
    assert len(qs2) == len(qs1) + 1
    for i in range(len(qs1)):
        assert qs2[i]['id'] == ids1[i]
    assert 'Added 1 question based on bengaluru' in d2['message']


def test_refine_remove_question():
    r1 = client.post('/api/v1/prompt-quiz/draft', json={'prompt': '4 questions on technology'})
    assert r1.status_code == 200
    d1 = r1.json()
    qs1 = d1['questions']
    if len(qs1) < 3:
        return

    ids1 = [q['id'] for q in qs1]

    r2 = client.post('/api/v1/prompt-quiz/draft', json={
        'prompt': 'remove question 2',
        'previous_brief': d1['brief'],
        'current_questions': [{'id': q['id'], 'question_text': q['question_text']} for q in qs1]
    })
    assert r2.status_code == 200
    d2 = r2.json()
    qs2 = d2['questions']

    assert len(qs2) == len(qs1) - 1
    assert qs2[0]['id'] == ids1[0]
    assert qs2[1]['id'] == ids1[2]
