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
        return await self.generate_multimodal(prompt, [{"mime_type": mime_type, "data": b64_data}])

    async def transcribe_audio(self, audio_bytes: bytes, mime_type: str = "audio/mp3") -> str:
        b64_data = base64.b64encode(audio_bytes).decode("utf-8")
        prompt = (
            "Listen to this audio clip from a quiz presentation. "
            "Transcribe all spoken words word-for-word. "
            "If there is music, theme music, or sound effects, describe them in brackets (e.g. [Dramatic fanfare], [Birdsong])."
        )
        return await self.generate_multimodal(prompt, [{"mime_type": mime_type, "data": b64_data}])

class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or settings.GEMINI_API_KEY or ""
        key = key.strip()
        if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
            key = key[1:-1].strip()
        self.api_key = key
        self.model = "text-embedding-004"

    async def get_embedding(self, text: str) -> List[float]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]}
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                if resp.is_error:
                    logger.error(f"[GeminiEmbeddingProvider] API error ({resp.status_code}): {resp.text}")
                resp.raise_for_status()
                data = resp.json()
                return data["embedding"]["values"]
        except Exception as e:
            logger.warning(f"[GeminiEmbeddingProvider] API call failed ({e}), falling back to local deterministic embedding.")
            from backend.app.services.ai.local_provider import LocalEmbeddingProvider
            return await LocalEmbeddingProvider(dim=settings.EMBEDDING_DIM).get_embedding(text)

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        # Batch or loop
        res = []
        for text in texts:
            emb = await self.get_embedding(text)
            res.append(emb)
        return res
