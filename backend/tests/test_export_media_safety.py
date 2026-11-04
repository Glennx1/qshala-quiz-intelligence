"""Exporter media handling is safe against SSRF, path escape and cache collisions (audit Q10)."""
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.services.export import exporter as ex


@pytest.fixture
def dns(monkeypatch):
    """Fake DNS: name -> address list, so the tests never touch the network."""
    table = {
        "cdn.example.test": ["93.184.216.34"],
        "internal.example.test": ["10.1.2.3"],
        "rebind.example.test": ["93.184.216.34", "127.0.0.1"],
        "meta.example.test": ["169.254.169.254"],
        "v6.example.test": ["2606:4700:4700::1111"],
        "v6loop.example.test": ["::1"],
        "cgnat.example.test": ["100.64.0.5"],            # shared address space: not private, not global
        "mapped.example.test": ["::ffff:127.0.0.1"],     # IPv4-mapped loopback
    }
    ex._HOST_CACHE.clear()                               # results are remembered for a minute: start clean

    def fake_getaddrinfo(host, port, *a, **k):
        if host in table:
            return [(2, 1, 6, "", (addr, 0)) for addr in table[host]]
        raise OSError("unknown host")

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)
    return table


def test_only_public_http_urls_are_allowed(dns):
    assert ex._url_allowed("https://cdn.example.test/slides/a.png")
    assert ex._url_allowed("http://cdn.example.test/a.png")
    assert ex._url_allowed("https://v6.example.test/a.png")
    for bad in (
        "http://127.0.0.1/a.png", "http://localhost/a.png", "http://[::1]/a.png",
        "http://169.254.169.254/latest/meta-data/", "http://meta.example.test/x",
        "http://internal.example.test/x", "http://rebind.example.test/x", "http://v6loop.example.test/x",
        "http://cgnat.example.test/x", "http://100.64.0.5/x", "http://mapped.example.test/x",
        "http://0.0.0.0/x", "http://192.168.1.10/x", "file:///etc/passwd", "ftp://cdn.example.test/x",
        "https:///nohost", "gopher://cdn.example.test/", "http://unknown.example.test/x",
    ):
        assert not ex._url_allowed(bad), bad


def test_host_allowlist_narrows_further(dns, monkeypatch):
    monkeypatch.setenv("EXPORT_ALLOWED_MEDIA_HOSTS", "cdn.example.test, other.example.test")
    assert ex._url_allowed("https://cdn.example.test/a.png")
    assert not ex._url_allowed("https://v6.example.test/a.png")        # public, but not on the list


def test_redirects_to_internal_hosts_are_refused(dns):
    handler = next(h for h in ex._OPENER.handlers if h.__class__.__name__ == "_SafeRedirect")
    req = urllib.request.Request("https://cdn.example.test/a.png")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, "http://169.254.169.254/latest/meta-data/")
    ok = handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, "https://cdn.example.test/b.png")
    assert ok is not None and ok.full_url == "https://cdn.example.test/b.png"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_refused_urls_are_never_requested(dns, tmp_path, monkeypatch):
    calls = []

    class Opener:
        def open(self, req, timeout=None):
            calls.append(req.full_url)
            return FakeResp(b"x" * 100)

    monkeypatch.setattr(ex, "_OPENER", Opener())
    assert ex._download_url_to_file("http://169.254.169.254/latest/meta-data/x.png", tmp_path) is None
    assert ex._resolve_media_path("http://127.0.0.1:8080/secret.png", download_dir=tmp_path) is None
    assert calls == []


def test_same_basename_from_different_decks_no_longer_collides(dns, tmp_path, monkeypatch):
    bodies = {
        "https://cdn.example.test/slides/deckA/media/slide_3_img_1.png": b"AAAA" * 50,
        "https://cdn.example.test/slides/deckB/media/slide_3_img_1.png": b"BBBB" * 50,
    }
    calls = []

    class Opener:
        def open(self, req, timeout=None):
            calls.append(req.full_url)
            return FakeResp(bodies[req.full_url])

    monkeypatch.setattr(ex, "_OPENER", Opener())
    a = ex._download_url_to_file("https://cdn.example.test/slides/deckA/media/slide_3_img_1.png", tmp_path)
    b = ex._download_url_to_file("https://cdn.example.test/slides/deckB/media/slide_3_img_1.png", tmp_path)
    assert a != b and a.read_bytes() == b"AAAA" * 50 and b.read_bytes() == b"BBBB" * 50
    assert a.name.endswith("slide_3_img_1.png")                 # extension / name kept for type detection
    again = ex._download_url_to_file("https://cdn.example.test/slides/deckA/media/slide_3_img_1.png", tmp_path)
    assert again == a and len(calls) == 2                       # the cache still works for the same URL


def test_static_paths_cannot_climb_out_of_their_root(tmp_path, monkeypatch):
    slides = tmp_path / "slides"
    (slides / "deck").mkdir(parents=True)
    (slides / "deck" / "a.png").write_bytes(b"png")
    (tmp_path / "secret.png").write_bytes(b"secret")
    monkeypatch.setattr(settings, "SLIDES_DIR", slides)
    assert ex._resolve_media_path("/static/slides/deck/a.png") == slides / "deck" / "a.png"
    assert ex._resolve_media_path("/static/slides/../secret.png") is None
    assert ex._resolve_media_path("/static/slides/deck/../../secret.png") is None
    assert ex._resolve_media_path("/static/slides/..\\secret.png") is None


def test_direct_paths_only_resolve_inside_the_apps_own_folders(tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x" * 10)
    assert ex._resolve_media_path(str(outside)) is None
    inside = Path(settings.UPLOAD_DIR) / "export_safety_probe.png"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_bytes(b"x" * 10)
    try:
        assert ex._resolve_media_path(str(inside)) == inside
    finally:
        inside.unlink()
