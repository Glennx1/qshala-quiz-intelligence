"""The static-file fallback must never serve files outside its fallback folders (audit Q2)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.main import MultiDirStaticFiles


def _client(tmp_path):
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    primary.mkdir()
    fallback.mkdir()
    (fallback / "ok.txt").write_text("inside")
    (tmp_path / "secret.txt").write_text("outside")
    app = FastAPI()
    app.mount("/static", MultiDirStaticFiles(directory=str(primary), fallback_dirs=[fallback]))
    return TestClient(app)


def test_fallback_still_serves_files_inside_the_folder(tmp_path):
    r = _client(tmp_path).get("/static/ok.txt")
    assert r.status_code == 200 and r.text == "inside"


def test_fallback_blocks_traversal_out_of_the_folder(tmp_path):
    c = _client(tmp_path)
    for p in ("/static/%2e%2e/secret.txt", "/static/..%2fsecret.txt", "/static/../secret.txt",
              "/static/%2e%2e%2fsecret.txt"):
        r = c.get(p)
        assert r.status_code == 404, (p, r.status_code, r.text)
        assert "outside" not in r.text
