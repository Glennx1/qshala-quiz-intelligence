"""Offline tests for the Gemini cost controls: capped image descriptions, pooled HTTP client,
token-usage tracking and the chunked tagger's retry of skipped questions. No network, no API key."""
import asyncio
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.ai import gemini_provider as gp
from backend.app.services.ai.gemini_provider import GeminiLLMProvider


def _ok_response(text="A tower. Eiffel Tower, Paris.", usage=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.is_error = False
    resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": usage or {"promptTokenCount": 300, "candidatesTokenCount": 40, "thoughtsTokenCount": 0},
    }
    return resp


def _provider(model):
    p = GeminiLLMProvider(api_key="TEST_KEY")
    p.model = model
    return p


# --------------------------------------------------------------------- image description payload

def test_describe_image_is_capped_and_minimal_thinking_on_gemini_3():
    gp.usage_snapshot(reset=True)
    post = AsyncMock(return_value=_ok_response())
    with patch("httpx.AsyncClient.post", new=post):
        out = asyncio.run(_provider("gemini-3.5-flash-lite").describe_image(b"\x89PNG", "image/png"))
    assert out.startswith("A tower")
    payload = post.call_args.kwargs["json"]
    cfg = payload["generationConfig"]
    assert cfg["max_output_tokens"] == gp.VISION_MAX_OUTPUT_TOKENS
    assert cfg["thinking_config"] == {"thinking_level": "MINIMAL"}
    prompt = payload["contents"][0]["parts"][-1]["text"]
    assert "70 words" in prompt and "OCR" in prompt          # still asks for the text AND the visual content
    assert "visual clues" in prompt


def test_describe_image_turns_thinking_off_on_gemini_2_5_flash():
    post = AsyncMock(return_value=_ok_response())
    with patch("httpx.AsyncClient.post", new=post):
        asyncio.run(_provider("gemini-2.5-flash").describe_image(b"x", "image/jpeg"))
    assert post.call_args.kwargs["json"]["generationConfig"]["thinking_config"] == {"thinking_budget": 0}


def test_thinking_config_per_model():
    assert gp._thinking_config("gemini-2.5-pro", "minimal") == {"thinking_budget": 128}   # Pro cannot reach 0
    assert gp._thinking_config("gemini-2.0-flash", "minimal") is None                      # no such control


def test_describe_image_records_usage_by_label():
    gp.usage_snapshot(reset=True)
    post = AsyncMock(return_value=_ok_response(usage={"promptTokenCount": 300, "candidatesTokenCount": 40,
                                                       "thoughtsTokenCount": 7}))
    with patch("httpx.AsyncClient.post", new=post):
        asyncio.run(_provider("gemini-3.5-flash-lite").describe_image(b"x", "image/png"))
    assert gp.usage_snapshot()["vision"] == {"calls": 1, "in": 300, "out": 40, "think": 7, "cached": 0}


def test_describe_image_retries_once_with_bigger_cap_when_cut_off_before_any_text():
    cut = MagicMock()
    cut.status_code = 200
    cut.is_error = False
    cut.json.return_value = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}
    post = AsyncMock(side_effect=[cut, _ok_response("Recovered description")])
    with patch("httpx.AsyncClient.post", new=post):
        out = asyncio.run(_provider("gemini-3.5-flash-lite").describe_image(b"x", "image/png"))
    assert out == "Recovered description"
    caps = [c.kwargs["json"]["generationConfig"]["max_output_tokens"] for c in post.call_args_list]
    assert caps == [gp.VISION_MAX_OUTPUT_TOKENS, gp.VISION_MAX_OUTPUT_TOKENS * 3]


def test_plain_multimodal_call_is_unchanged_when_no_caps_requested():
    """transcribe_audio etc. must keep sending exactly the old request (no generationConfig added)."""
    post = AsyncMock(return_value=_ok_response("hello"))
    with patch("httpx.AsyncClient.post", new=post):
        out = asyncio.run(_provider("gemini-3.5-flash-lite").transcribe_audio(b"abc", "audio/mp3"))
    assert out == "hello"
    assert "generationConfig" not in post.call_args.kwargs["json"]


# --------------------------------------------------------------------- pooled client

def test_shared_client_is_reused_within_a_loop_and_replaced_across_loops():
    async def grab():
        return gp.get_shared_client(), gp.get_shared_client()
    a, b = asyncio.run(grab())
    assert a is b                                  # same loop: one pooled client
    c, _ = asyncio.run(grab())
    assert c is not a                              # new loop: a fresh client, never one bound to a dead loop


# --------------------------------------------------------------------- chunked tagger

def _canned(n):
    return {"n": n, "topics": [{"theme": "History", "subtopic_l2": "Modern History", "keywords": ["X"]}],
            "geo_location": "", "india_international": "NA", "relevant_year": 1770,
            "fit": "good", "search_summary": "ok"}


def test_default_chunk_size_is_20():
    from backend.app.services.tagging import qshala_batch
    assert qshala_batch.CHUNK_SIZE == 20


def test_skipped_questions_are_reasked_alone_and_token_usage_is_saved():
    from backend.app.database import SessionLocal
    from backend.app.models.qshala_tag import QshalaTag
    from backend.app.services.tagging import qshala_batch
    from test_ingestion_overhaul import _cleanup, _make_questions

    class DropsLastOnce:
        def __init__(self):
            self.prompts = []

        async def generate_json_schema(self, prompt, schema, **k):
            self.prompts.append(prompt)
            ns = [int(m) for m in re.findall(r"\[n=(\d+)\]", prompt)]
            if len(self.prompts) == 1:
                ns = ns[:-1]                            # first call: model skips the last question
            return {"results": [_canned(n) for n in ns]}, {"in": 1000, "out": 400, "think": 0}

    doc_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        qs = _make_questions(db, doc_id, 5)
        prov = DropsLastOnce()
        stats = asyncio.run(qshala_batch.tag_questions_batched(db, qs, provider=prov, model="fake"))
        db.commit()
        assert len(prov.prompts) == 2                   # the whole chunk, then only the skipped question
        assert prov.prompts[1].count("[n=") == 1
        assert stats["confirmed"] + stats["draft"] == 5
        assert stats["failed_chunks"] == 0
        assert (stats["calls"], stats["tokens_in"], stats["tokens_out"]) == (2, 2000, 800)
        rows = db.query(QshalaTag).filter(QshalaTag.question_id.in_([q.id for q in qs])).all()
        assert len(rows) == 5 and all(r.topic_l1 for r in rows)        # none parked for review
        assert all(r.tokens_in is not None and r.tokens_out is not None for r in rows)
    finally:
        db.close()
        _cleanup(doc_id)
