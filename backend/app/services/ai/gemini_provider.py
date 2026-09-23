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
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = "gemini-1.5-flash"

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
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

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

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)

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
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

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
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = "text-embedding-004"

    async def get_embedding(self, text: str) -> List[float]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]}
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["embedding"]["values"]

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        # Batch or loop
        res = []
        for text in texts:
            emb = await self.get_embedding(text)
            res.append(emb)
        return res
