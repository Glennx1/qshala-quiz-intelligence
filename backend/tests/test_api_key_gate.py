"""API key gate (audit Q15): constant-time compare and an optional fail-closed mode."""
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import settings

client = TestClient(main.app)
PROTECTED = "/api/v1/stats/dashboard"


def test_open_by_default_when_no_secret(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_SECRET", None)
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)
    assert client.get(PROTECTED).status_code != 401
    assert client.get(PROTECTED).status_code != 503


def test_fail_closed_refuses_protected_routes_without_a_secret(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_SECRET", None)
    monkeypatch.setenv("REQUIRE_API_KEY", "1")
    assert client.get(PROTECTED).status_code == 503
    assert client.get("/openapi.json").status_code != 503       # public routes are not gated
    assert client.options(PROTECTED, headers={"Origin": "http://localhost:3000",
                                              "Access-Control-Request-Method": "GET"}).status_code != 503


def test_wrong_and_missing_key_are_rejected_and_right_key_passes(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_SECRET", "s3cret-value")
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)
    assert client.get(PROTECTED).status_code == 401
    assert client.get(PROTECTED, headers={"X-API-Key": "s3cret-valuf"}).status_code == 401
    assert client.get(PROTECTED, headers={"X-API-Key": "s3cret-value"}).status_code not in (401, 503)


def test_comparison_is_constant_time_and_handles_non_ascii():
    assert main._api_key_matches("abc", "abc") and not main._api_key_matches("abd", "abc")
    assert not main._api_key_matches("\u00e9", "e")                # no TypeError on non-ASCII input
