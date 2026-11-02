import logging
import pytest
from unittest.mock import patch, MagicMock
from backend.app.services.ai.gemini_provider import GeminiLLMProvider, GeminiEmbeddingProvider

@pytest.mark.anyio
async def test_no_api_key_in_logs_or_urls(caplog):
    secret_key = "SECRET_KEY_NEVER_LEAK_9999"
    llm = GeminiLLMProvider(api_key=secret_key)
    embedder = GeminiEmbeddingProvider(api_key=secret_key)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_error = False
    mock_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Hello test"}]}}],
        "embedding": {"values": [0.1] * 768}
    }

    with caplog.at_level(logging.DEBUG):
        with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
            # 1. Test LLM generation
            res = await llm.generate_text("test prompt")
            assert res == "Hello test"

            # Check that secret_key is NOT in URL query string
            called_url = mock_post.call_args[0][0]
            assert "key=" not in called_url
            assert secret_key not in called_url

            # Check that secret_key was passed in x-goog-api-key header
            called_headers = mock_post.call_args[1].get("headers") or {}
            assert called_headers.get("x-goog-api-key") == secret_key

            # 2. Test Embedding
            mock_post.reset_mock()
            emb = await embedder.get_embedding("test embedding")
            assert len(emb) == 768

            called_url = mock_post.call_args[0][0]
            assert "key=" not in called_url
            assert secret_key not in called_url
            called_headers = mock_post.call_args[1].get("headers") or {}
            assert called_headers.get("x-goog-api-key") == secret_key

    # Check all captured log output
    full_log_text = caplog.text
    for record in caplog.records:
        assert secret_key not in record.message
        assert secret_key not in str(record.args)
    assert secret_key not in full_log_text
