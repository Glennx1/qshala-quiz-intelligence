import base64
import json
import logging
import httpx
from typing import List, Dict, Any, Optional
from backend.app.services.ai.base import LLMProvider, EmbeddingProvider
from backend.app.config import settings

logger = logging.getLogger(__name__)

class GeminiLLMProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.GEMINI_API_KEY or ""
        key = key.strip()
        if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
            key = key[1:-1].strip()
        self.api_key = key
        self.model = settings.GEMINI_MODEL or "gemini-2.5-flash"

    def _extract_text(self, data: Dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            feedback = data.get("promptFeedback", {})
            block_reason = feedback.get("blockReason")
            if block_reason:
                raise ValueError(f"Gemini API blocked the request: {block_reason} (feedback: {feedback})")
            raise ValueError(f"Gemini API returned no candidates: {data}")

        first_candidate = candidates[0]
        content = first_candidate.get("content", {})
        parts = content.get("parts", [])
        if not parts:
            finish_reason = first_candidate.get("finishReason")
            raise ValueError(f"Gemini candidate has no parts (finishReason: {finish_reason}): {first_candidate}")

        # In Gemini 2.5 Flash, reasoning/thoughts are returned as parts with 'thought': True.
        # The final output is in the non-thought part.
        for part in reversed(parts):
            if "text" in part and not part.get("thought", False):
                return part["text"]

        # Fallback to the last part with text if all had thought flag or flag wasn't set
        for part in reversed(parts):
            if "text" in part:
                return part["text"]

        raise ValueError(f"No text part found in Gemini candidate parts: {parts}")

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.is_error:
                logger.error(f"[GeminiLLMProvider] API error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            return self._extract_text(data)

    async def generate_json(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        logger.info(f"[GeminiLLMProvider] Sending generate_json request to model '{self.model}'")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.is_error:
                logger.error(f"[GeminiLLMProvider] API error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            text = self._extract_text(data)
            logger.info(f"[GeminiLLMProvider] Received response from model '{self.model}': {text}")
            clean_text = text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            elif clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            return json.loads(clean_text.strip())

    async def generate_json_schema(
        self,
        prompt: str,
        schema: Dict[str, Any],
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        thinking_level: Optional[str] = None,
        temperature: float = 0.0,
    ) -> tuple[Dict[str, Any], Dict[str, int]]:
        """Generate JSON constrained by `schema` (OpenAPI-style, upper-case types, enums supported).

        Supports per-call model override (so the tagger can run on 3.5 Flash-Lite while the generator
        stays on 2.5 Flash) and a thinking level ('minimal', 'low', 'medium', 'high', or None for default).

        Returns (parsed_json, usage) where usage = {'in', 'out', 'think', 'cached'} (token counts).
        """
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        chosen_model = model or self.model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{chosen_model}:generateContent?key={self.api_key}"
        gen_cfg: Dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": temperature,
        }
        if thinking_level is not None:
            # Gemini 3.x uses thinking_level; 2.5 uses thinking_budget. Pass thinking_level if the model name
            # suggests 3.x, otherwise thinking_budget=0 for minimal. Caller can set thinking_level=None to skip.
            if any(tag in chosen_model for tag in ("3.1", "3.5", "3.6", "3.8", "4-")):
                gen_cfg["thinking_config"] = {"thinking_level": thinking_level.upper()}
            else:
                gen_cfg["thinking_config"] = {"thinking_budget": 0 if thinking_level == "low" else 128}

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
        }
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        logger.info(f"[GeminiLLMProvider] generate_json_schema → {chosen_model}")
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=payload)
            if resp.is_error:
                # If the model rejects thinking_config (older SDK/model), retry once without it.
                if "thinking" in resp.text.lower() and "thinking_config" in gen_cfg:
                    gen_cfg.pop("thinking_config", None)
                    resp = await client.post(url, json=payload)
                if resp.is_error:
                    logger.error(f"[GeminiLLMProvider] API error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()
            data = resp.json()

        text = self._extract_text(data)
        clean = text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        elif clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        parsed = json.loads(clean.strip())

        um = data.get("usageMetadata", {}) or {}
        usage = {
            "in": um.get("promptTokenCount", 0) or 0,
            "out": um.get("candidatesTokenCount", 0) or 0,
            "think": um.get("thoughtsTokenCount", 0) or 0,
            "cached": um.get("cachedContentTokenCount", 0) or 0,
        }
        return parsed, usage

    async def generate_multimodal(
        self,
        prompt: str,
        media_parts: List[Dict[str, str]],
        system_instruction: Optional[str] = None
    ) -> str:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        parts = []
        for media in media_parts:
            parts.append({
                "inline_data": {
                    "mime_type": media["mime_type"],
                    "data": media["data"]
                }
            })
        parts.append({"text": prompt})

        payload = {"contents": [{"parts": parts}]}
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=payload)
            if resp.is_error:
                logger.error(f"[GeminiLLMProvider] API error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            return self._extract_text(data)

    async def describe_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Analyze this quiz presentation image. "
            "1. Transcribe any text visible on the image accurately (OCR). "
            "2. Describe the key visual content (person, monument, diagram, flag, animal, historical event, etc.) "
            "and any visual clues relevant to a quiz question."
        )
        try:
            return await self.generate_multimodal(prompt, [{"mime_type": mime_type, "data": b64_data}])
        finally:
            del b64_data

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/mp3") -> str:
        b64_data = base64.b64encode(audio_bytes).decode("utf-8")
        prompt = (
            "Listen to this audio clip from a quiz presentation. "
            "Transcribe all spoken words word-for-word. "
            "If there is music, theme music, or sound effects, describe them in brackets (e.g. [Dramatic fanfare], [Birdsong])."
        )
        return await self.generate_multimodal(prompt, [{"mime_type": mime_type, "data": b64_data}])

class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google deprecated text-embedding-004 and embedding-001 (confirmed by a Google staff
    reply on the AI developer forum, Nov 2026) -- both now 404 on v1beta's embedContent, with
    no outage window or warning period, and every call was silently falling back to the local
    deterministic embedding (see except block below) instead of a real semantic vector. This
    degraded search/dedup quality for however long the deprecation has been in effect, for
    every question ingested in that window -- a one-time re-embedding backfill of existing
    rows is worth doing once this is confirmed working (see QSHALA_PRIORITY_PLAN_STATUS.md).

    Replacement is gemini-embedding-001, Google's recommended successor. Its default output is
    3072-dim (already L2-normalized), not this app's fixed 768-dim pgvector column
    (settings.EMBEDDING_DIM), so every request asks for a truncated 768-dim output via
    embedContentConfig.outputDimensionality -- and per Google's docs, anything other than the
    3072-dim default comes back NOT normalized and must be normalized by hand, which
    _normalize() below does. taskType is set per call site: RETRIEVAL_QUERY for a search query
    (get_embedding, called from hybrid_retriever.py) vs RETRIEVAL_DOCUMENT for content being
    indexed (get_embeddings, called from pipeline.py during ingestion) -- asymmetric embeddings
    perform meaningfully better for retrieval than embedding both sides the same way.
    """
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.GEMINI_API_KEY or ""
        key = key.strip()
        if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
            key = key[1:-1].strip()
        self.api_key = key
        self.model = "gemini-embedding-001"

    @staticmethod
    def _normalize(values: List[float]) -> List[float]:
        """gemini-embedding-001 only auto-normalizes its native 3072-dim output; any truncated
        outputDimensionality (768 here) comes back un-normalized and must be L2-normalized by
        hand for cosine similarity (pgvector's distance op) to behave correctly."""
        norm = sum(v * v for v in values) ** 0.5
        if norm == 0:
            return values
        return [v / norm for v in values]

    @classmethod
    def _coerce_dim(cls, values: List[float], text: str) -> List[float]:
        """Confirmed in production (Nov 2 2026): batchEmbedContents returned the native 3072-dim
        output even though every request item carried embedContentConfig.outputDimensionality=768
        -- a psycopg.errors.DataException ("expected 768 dimensions, not 3072") crashed the
        questions INSERT and failed the whole deck. Google's docs don't fully specify whether
        batchEmbedContents honors the same per-item embedContentConfig nesting as the single
        embedContent endpoint, so rather than guess at an undocumented request shape, this
        enforces the output shape instead: gemini-embedding-001 is trained with Matryoshka
        Representation Learning, meaning a prefix of the native 3072-dim vector is itself a valid
        lower-dimensional embedding -- Google's own outputDimensionality truncates this way, so
        doing it client-side when the server didn't is mathematically the same operation, just
        performed locally. Returns an un-normalized dim-length vector for _normalize() to
        L2-normalize as usual (the slice is not normalized, matching every other truncated path).
        Raises ValueError if the vector is shorter than the target dim -- that can't be coerced,
        only reported, so the caller's except block falls back to the local deterministic
        embedding instead of ever inserting a wrong-shaped vector."""
        dim = settings.EMBEDDING_DIM
        if len(values) == dim:
            return values
        if len(values) > dim:
            logger.warning(
                "[GeminiEmbeddingProvider] got %d-dim embedding, expected %d -- truncating "
                "client-side (text=%r)", len(values), dim, text[:80],
            )
            return values[:dim]
        raise ValueError(f"embedding shorter than EMBEDDING_DIM ({len(values)} < {dim})")

    async def get_embedding(self, text: str) -> List[float]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "embedContentConfig": {
                "taskType": "RETRIEVAL_QUERY",
                "outputDimensionality": settings.EMBEDDING_DIM,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                if resp.is_error:
                    logger.error(f"[GeminiEmbeddingProvider] API error ({resp.status_code}): {resp.text}")
                resp.raise_for_status()
                data = resp.json()
                values = self._coerce_dim(data["embedding"]["values"], text)
                return self._normalize(values)
        except Exception as e:
            logger.warning(f"[GeminiEmbeddingProvider] API call failed ({e}), falling back to local deterministic embedding.")
            from backend.app.services.ai.local_provider import LocalEmbeddingProvider
            return await LocalEmbeddingProvider(dim=settings.EMBEDDING_DIM).get_embedding(text)

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not self.api_key:
            from backend.app.services.ai.local_provider import LocalEmbeddingProvider
            local_p = LocalEmbeddingProvider(dim=settings.EMBEDDING_DIM)
            return [await local_p.get_embedding(t) for t in texts]

        # Use batchEmbedContents endpoint in chunks of up to 96
        chunk_size = 96
        results: List[List[float]] = []
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents?key={self.api_key}"

        for i in range(0, len(texts), chunk_size):
            chunk = texts[i:i + chunk_size]
            payload = {
                "requests": [
                    {
                        "model": f"models/{self.model}",
                        "content": {"parts": [{"text": t}]},
                        "embedContentConfig": {
                            "taskType": "RETRIEVAL_DOCUMENT",
                            "outputDimensionality": settings.EMBEDDING_DIM,
                        },
                    }
                    for t in chunk
                ]
            }
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.is_error:
                        logger.warning(f"[GeminiEmbeddingProvider] batchEmbedContents error ({resp.status_code}), falling back to serial")
                        for t in chunk:
                            results.append(await self.get_embedding(t))
                    elif len(data := resp.json().get("embeddings", [])) != len(chunk):
                        # batchEmbedContents returned a different count than requested -- can't
                        # safely zip results back to texts by position, so re-fetch this whole
                        # chunk serially rather than risk silently mismatching embeddings to texts.
                        logger.warning(
                            "[GeminiEmbeddingProvider] batchEmbedContents returned %d embeddings "
                            "for %d texts, falling back to serial for this chunk", len(data), len(chunk),
                        )
                        for t in chunk:
                            results.append(await self.get_embedding(t))
                    else:
                        for t, e in zip(chunk, data):
                            try:
                                values = self._coerce_dim(e["values"], t)
                                results.append(self._normalize(values))
                            except ValueError:
                                # Too short to coerce (see _coerce_dim) -- fall back to a single
                                # get_embedding() call for just this text, which has its own
                                # fallback to the local deterministic embedding on failure. Never
                                # let a wrong-length vector reach the questions.embedding INSERT.
                                logger.warning(
                                    "[GeminiEmbeddingProvider] batch item too short to coerce, "
                                    "refetching serially (text=%r)", t[:80],
                                )
                                results.append(await self.get_embedding(t))
            except Exception as batch_err:
                logger.warning(f"[GeminiEmbeddingProvider] batchEmbedContents failed ({batch_err}), falling back to serial")
                for t in chunk:
                    results.append(await self.get_embedding(t))

        return results
