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
