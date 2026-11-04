"""Gemini retry policy (audit Q14): exponential backoff, Retry-After, retry on timeouts."""
import asyncio

import httpx
import pytest

from backend.app.services.ai import gemini_provider as gp
from backend.app.services.tagging import qshala_batch


class FakeClient:
    """Plays back a script of responses/exceptions, one per post()."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def post(self, url, json=None, headers=None, **kw):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _resp(status, headers=None):
    return httpx.Response(status, headers=headers or {}, request=httpx.Request("POST", "https://x.test"))


@pytest.fixture
def sleeps(monkeypatch):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(gp.asyncio, "sleep", fake_sleep)
    return waits


def run(client, **kw):
    return asyncio.run(gp._post_with_retry(client, "https://x.test", {}, "k", **kw))


def test_backoff_is_exponential_and_stops_after_max_retries(sleeps):
    client = FakeClient([_resp(429)] * 4)
    resp = run(client)
    assert resp.status_code == 429 and client.calls == 4          # 1 try + 3 retries
    assert len(sleeps) == 3
    assert 2.0 <= sleeps[0] < 3.0 and 4.0 <= sleeps[1] < 5.0 and 8.0 <= sleeps[2] < 9.0


def test_retry_after_header_is_honoured_up_to_the_cap(sleeps):
    client = FakeClient([_resp(429, {"retry-after": "20"}), _resp(200)])
    assert run(client).status_code == 200
    assert sleeps == [20.0]
    sleeps.clear()
    client = FakeClient([_resp(503, {"retry-after": "9999"}), _resp(200)])
    assert run(client).status_code == 200
    assert sleeps == [gp.RETRY_AFTER_CAP_S]


def test_small_retry_after_never_shortens_the_backoff(sleeps):
    client = FakeClient([_resp(429, {"retry-after": "1"}), _resp(200)])
    run(client)
    assert sleeps[0] >= 2.0


def test_timeouts_and_connection_errors_are_retried(sleeps):
    client = FakeClient([httpx.ReadTimeout("slow"), httpx.ConnectError("reset"), _resp(200)])
    assert run(client).status_code == 200
    assert client.calls == 3 and len(sleeps) == 2


def test_timeout_is_raised_once_retries_are_used_up(sleeps):
    client = FakeClient([httpx.ReadTimeout("slow")] * 4)
    with pytest.raises(httpx.ReadTimeout):
        run(client)
    assert client.calls == 4


def test_timeout_retry_can_be_switched_off(sleeps, monkeypatch):
    monkeypatch.setattr(gp, "RETRY_ON_TRANSPORT_ERROR", False)
    client = FakeClient([httpx.ReadTimeout("slow"), _resp(200)])
    with pytest.raises(httpx.ReadTimeout):
        run(client)
    assert client.calls == 1


def test_other_errors_are_returned_immediately_without_retry(sleeps):
    for status in (400, 401, 404, 500):
        client = FakeClient([_resp(status)])
        assert run(client).status_code == status and client.calls == 1
    assert sleeps == []


def test_tagging_chunk_timeout_is_longer_than_the_http_request_timeout():
    assert qshala_batch.CHUNK_TIMEOUT_S > 90.0
