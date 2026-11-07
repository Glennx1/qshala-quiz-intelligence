"""One shared httpx client for the prompt-quiz LLM calls, so each call reuses an open connection instead of
paying a new TLS handshake. The client is rebuilt if httpx.Client is swapped out (tests patch it)."""
from __future__ import annotations

import threading
from typing import Any

import httpx

_lock = threading.Lock()
_client: Any = None
_client_cls: Any = None


def get_client() -> Any:
    global _client, _client_cls
    cls = httpx.Client
    if _client is None or _client_cls is not cls:
        with _lock:
            if _client is None or _client_cls is not cls:
                _client = cls()
                _client_cls = cls
    return _client
